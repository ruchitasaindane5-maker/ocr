"""SQLite database storage + search (koi AI nahi).

Sab data `data/pdf_qa.db` (SQLite) mein save hota hai:
  documents  - PDF ki jaankari (name, hash, pages, kab add hui)
  pages      - har page ka extracted text (method: text / ocr)
  chunks     - search ke liye kate hue hisse
  chunks_fts - SQLite FTS5 full-text index (BM25 ranking) - ye database
               ki apni classic search hai, koi AI/LLM/embedding nahi.

Search do tarike se hoti hai:
  1. FTS5 BM25 (primary, database ke andar, bahut tez)
  2. TF-IDF fallback (agar FTS se kam result mile, jaise aadha shabd)

Purani `store.json` ho to pehli baar chalane par uska data khud
database mein migrate ho jata hai.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import threading
from collections import Counter
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_FILE = os.environ.get("PDF_QA_DB", os.path.join(DATA_DIR, "pdf_qa.db"))
OLD_JSON = os.path.join(DATA_DIR, "store.json")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")

STOPWORDS = set(
    """the a an is are was were what how why when where who which in on of to for
    and or ke ka ki hai hain kya kaise karna kare mujhe batao bataiye me mein ye
    yeh wo woh se par bhi nahi to tha thi ho hota hoti aur ya lekin""".split()
)

TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
CHUNK_TARGET = 900
CHUNK_OVERLAP = 150


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(text or "") if len(t) > 1 or t.isdigit()]


def chunk_page_text(text: str, target: int = CHUNK_TARGET, overlap: int = CHUNK_OVERLAP) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n{2,}|\n", text) if p.strip()]
    chunks, cur = [], ""
    for para in paras:
        if len(cur) + len(para) + 1 <= target:
            cur = f"{cur}\n{para}" if cur else para
        else:
            if cur:
                chunks.append(cur)
            while len(para) > target:
                chunks.append(para[:target])
                para = para[target - overlap:]
            cur = para
    if cur.strip():
        chunks.append(cur)
    out = []
    for i, c in enumerate(chunks):
        if i and overlap:
            c = chunks[i - 1][-overlap:] + "\n" + c
        out.append(c.strip())
    return [c for c in out if len(c) >= 30]


SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    sha256 TEXT UNIQUE NOT NULL,
    file_size INTEGER DEFAULT 0,
    page_count INTEGER DEFAULT 0,
    total_chars INTEGER DEFAULT 0,
    ocr_engine TEXT,
    ocr_pages INTEGER DEFAULT 0,
    tables_found INTEGER DEFAULT 0,
    metadata TEXT DEFAULT '{}',
    stored_file TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_no INTEGER NOT NULL,
    method TEXT DEFAULT 'text',
    text TEXT DEFAULT '',
    char_count INTEGER DEFAULT 0,
    UNIQUE(doc_id, page_no)
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_no INTEGER NOT NULL,
    method TEXT DEFAULT 'text',
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pages_doc ON pages(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, doc_id UNINDEXED, page_no UNINDEXED, chunk_id UNINDEXED,
    tokenize='unicode61'
);
"""


class Store:
    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._idf_cache: dict[str, float] | None = None
        self._migrate_old_json()

    # ---------- internal ----------
    def _migrate_old_json(self):
        """Purani store.json (v1) ka data database mein le aao, ek hi baar."""
        if self.stats()["docs"] or not os.path.exists(OLD_JSON):
            return
        try:
            old = json.load(open(OLD_JSON, encoding="utf-8")).get("docs", {})
        except Exception:
            return
        for doc_id, d in old.items():
            extracted = {"pages": d.get("pages", []), "page_count": d.get("page_count", 0),
                         "total_chars": d.get("total_chars", 0),
                         "ocr_engine": d.get("ocr_engine"), "ocr_pages": d.get("ocr_pages", 0),
                         "tables_found": 0, "metadata": {"migrated_from": "store.json"}}
            self._insert(doc_id, d["name"], doc_id, 0, extracted,
                         os.path.join(UPLOAD_DIR, f"{doc_id}.pdf"))

    def _insert(self, doc_id, name, sha, file_size, extracted, stored_file):
        chunks = []
        for page in extracted["pages"]:
            for text in chunk_page_text(page["text"]):
                chunks.append((doc_id, page["page"], page["method"], text))
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM chunks_fts WHERE doc_id=?", (doc_id,))
            self._conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
            self._conn.execute("DELETE FROM pages WHERE doc_id=?", (doc_id,))
            self._conn.execute(
                """INSERT INTO documents(id,name,sha256,file_size,page_count,total_chars,
                   ocr_engine,ocr_pages,tables_found,metadata,stored_file,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name,
                     file_size=excluded.file_size, page_count=excluded.page_count,
                     total_chars=excluded.total_chars, ocr_pages=excluded.ocr_pages,
                     tables_found=excluded.tables_found,
                     created_at=excluded.created_at""",
                (doc_id, name, sha, file_size, extracted["page_count"],
                 extracted["total_chars"], extracted.get("ocr_engine"),
                 extracted.get("ocr_pages", 0), extracted.get("tables_found", 0),
                 json.dumps(extracted.get("metadata", {}), ensure_ascii=False),
                 stored_file, datetime.now().isoformat(timespec="seconds")))
            self._conn.executemany(
                "INSERT INTO pages(doc_id,page_no,method,text,char_count) VALUES(?,?,?,?,?)",
                [(doc_id, p["page"], p["method"], p["text"], len(p["text"]))
                 for p in extracted["pages"]])
            cur = self._conn.executemany(
                "INSERT INTO chunks(doc_id,page_no,method,text) VALUES(?,?,?,?)", chunks)
            ids = [r[0] for r in self._conn.execute(
                "SELECT id FROM chunks WHERE doc_id=? ORDER BY id", (doc_id,))]
            self._conn.executemany(
                "INSERT INTO chunks_fts(text,doc_id,page_no,chunk_id) VALUES(?,?,?,?)",
                [(text, d, pg, cid) for (d, pg, _m, text), cid in zip(chunks, ids)])
        self._idf_cache = None

    # ---------- documents ----------
    def add_document(self, name: str, file_bytes: bytes, extracted: dict) -> dict:
        sha = hashlib.sha256(file_bytes).hexdigest()
        doc_id = sha[:12]
        stored = os.path.join(UPLOAD_DIR, f"{doc_id}.pdf")
        with open(stored, "wb") as f:
            f.write(file_bytes)
        self._insert(doc_id, name, sha, len(file_bytes), extracted, stored)
        return self.doc_summary(doc_id)

    def doc_summary(self, doc_id: str) -> dict:
        r = self._conn.execute(
            """SELECT d.*, (SELECT COUNT(*) FROM chunks c WHERE c.doc_id=d.id) AS chunks
               FROM documents d WHERE d.id=?""", (doc_id,)).fetchone()
        if r is None:
            raise KeyError(doc_id)
        return {"id": r["id"], "name": r["name"], "pages": r["page_count"],
                "chars": r["total_chars"], "chunks": r["chunks"],
                "ocr_engine": r["ocr_engine"], "ocr_pages": r["ocr_pages"],
                "tables_found": r["tables_found"], "file_size": r["file_size"],
                "created_at": r["created_at"]}

    def list_docs(self) -> list[dict]:
        ids = [r[0] for r in self._conn.execute("SELECT id FROM documents ORDER BY created_at")]
        return [self.doc_summary(i) for i in ids]

    def get_document(self, doc_id: str) -> dict | None:
        if not self._conn.execute("SELECT 1 FROM documents WHERE id=?", (doc_id,)).fetchone():
            return None
        summary = self.doc_summary(doc_id)
        pages = [{"page": r["page_no"], "text": r["text"], "method": r["method"]}
                 for r in self._conn.execute(
                     "SELECT * FROM pages WHERE doc_id=? ORDER BY page_no", (doc_id,))]
        return {**summary, "name": summary["name"], "pages": pages}

    def delete(self, doc_id: str) -> bool:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM chunks_fts WHERE doc_id=?", (doc_id,))
            self._conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
            self._conn.execute("DELETE FROM pages WHERE doc_id=?", (doc_id,))
            cur = self._conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        try:
            os.remove(os.path.join(UPLOAD_DIR, f"{doc_id}.pdf"))
        except OSError:
            pass
        self._idf_cache = None
        return cur.rowcount > 0

    def all_chunks(self, doc_id: str | None = None) -> list[dict]:
        q = ("SELECT c.*, d.name AS doc_name FROM chunks c JOIN documents d ON d.id=c.doc_id")
        args: tuple = ()
        if doc_id:
            q += " WHERE c.doc_id=?"
            args = (doc_id,)
        return [{"id": r["id"], "doc_id": r["doc_id"], "doc_name": r["doc_name"],
                 "page": r["page_no"], "method": r["method"], "text": r["text"]}
                for r in self._conn.execute(q, args)]

    def stats(self) -> dict:
        one = lambda sql: self._conn.execute(sql).fetchone()[0]  # noqa: E731
        size = sum(os.path.getsize(self.db_path + suf)
                   for suf in ("", "-wal", "-shm")
                   if os.path.exists(self.db_path + suf))
        return {"db_path": self.db_path,
                "db_size_kb": round(size / 1024, 1),
                "docs": one("SELECT COUNT(*) FROM documents"),
                "pages": one("SELECT COUNT(*) FROM pages"),
                "chunks": one("SELECT COUNT(*) FROM chunks")}

    # ---------- search (bina AI) ----------
    def term_idf(self, term: str) -> float:
        if self._idf_cache is None:
            df: Counter = Counter()
            rows = self._conn.execute("SELECT text FROM chunks").fetchall()
            for (text,) in rows:
                for t in set(tokenize(text)):
                    df[t] += 1
            n = max(len(rows), 1)
            self._idf_cache = {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}
        return self._idf_cache.get(term, 1.0)

    def search(self, query: str, doc_id: str | None = None, top_k: int = 5) -> list[dict]:
        terms = [t for t in tokenize(query) if t not in STOPWORDS] or tokenize(query)
        if not terms:
            return []
        hits = self._fts_search(terms, doc_id, top_k)
        if len(hits) < top_k:  # FTS se kam mila to TF-IDF se bhar do
            seen = {(h["doc_id"], h["page"], h["text"][:60]) for h in hits}
            for h in self._tfidf_search(terms, doc_id, top_k):
                if (h["doc_id"], h["page"], h["text"][:60]) not in seen:
                    hits.append(h)
                if len(hits) >= top_k:
                    break
        return hits[:top_k]

    def _fts_search(self, terms, doc_id, top_k) -> list[dict]:
        match = " OR ".join(f'"{t}"' for t in dict.fromkeys(terms))
        sql = """SELECT c.id, c.doc_id, c.page_no, c.method, c.text, d.name AS doc_name,
                        bm25(chunks_fts) AS rank
                 FROM chunks_fts JOIN chunks c ON c.id=chunks_fts.chunk_id
                 JOIN documents d ON d.id=c.doc_id
                 WHERE chunks_fts MATCH ?"""
        args: list = [match]
        if doc_id:
            sql += " AND c.doc_id=?"
            args.append(doc_id)
        sql += " ORDER BY rank LIMIT ?"
        args.append(top_k * 2)
        try:
            rows = self._conn.execute(sql, args).fetchall()
        except sqlite3.Error:
            return []
        out = []
        for r in rows:
            a = abs(float(r["rank"]))
            score = a / (1.0 + a)  # BM25 (negative) -> 0..1 relevance
            out.append({"id": r["id"], "doc_id": r["doc_id"], "doc_name": r["doc_name"],
                        "page": r["page_no"], "method": r["method"], "text": r["text"],
                        "score": round(float(score), 4)})
        return out

    def _tfidf_search(self, terms, doc_id, top_k) -> list[dict]:
        chunks = self.all_chunks(doc_id)
        if not chunks:
            return []
        q = Counter(terms)
        q_vec = {t: (1 + math.log(v)) * self.term_idf(t) for t, v in q.items()}
        q_norm = math.sqrt(sum(v * v for v in q_vec.values())) or 1.0
        q_vec = {t: v / q_norm for t, v in q_vec.items()}
        scored = []
        for c in chunks:
            counts = Counter(tokenize(c["text"]))
            if not counts:
                continue
            vec = {t: (1 + math.log(v)) * self.term_idf(t) for t, v in counts.items()}
            norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
            score = sum(q_vec.get(t, 0.0) * v / norm for t, v in vec.items() if t in q_vec)
            if score > 0.02:
                scored.append({**c, "score": round(float(score), 4)})
        scored.sort(key=lambda x: -x["score"])
        return scored[:top_k]
