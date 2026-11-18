"""Chunking + TF-IDF search index + disk persistence.

Koi heavy dependency nahi: TF-IDF aur cosine similarity pure Python mein
hai, isliye ye offline aur bina model-download ke kahin bhi chalega.
Data `data/` folder mein JSON ke roop mein save hota hai.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections import Counter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
STORE_FILE = os.path.join(DATA_DIR, "store.json")
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
    return [t.lower() for t in TOKEN_RE.findall(text) if len(t) > 1 or t.isdigit()]


def chunk_page_text(text: str, target: int = CHUNK_TARGET, overlap: int = CHUNK_OVERLAP) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n{2,}|\n", text) if p.strip()]
    chunks, cur = [], ""
    for para in paras:
        if len(cur) + len(para) + 1 <= target:
            cur = f"{cur}\n{para}" if cur else para
        else:
            if cur:
                chunks.append(cur)
            # bahut lamba paragraph ho to window se kaato
            while len(para) > target:
                chunks.append(para[:target])
                para = para[target - overlap:]
            cur = para
    if cur.strip():
        chunks.append(cur)
    # pichle chunk ka tail agle ke saath overlap (context na toote)
    out = []
    for i, c in enumerate(chunks):
        if i and overlap:
            c = chunks[i - 1][-overlap:] + "\n" + c
        out.append(c.strip())
    return [c for c in out if len(c) >= 30]


class Store:
    def __init__(self):
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        self.docs: dict[str, dict] = {}
        self._idf: dict[str, float] = {}
        self._chunk_vecs: list[dict[str, float]] = []
        self._load()

    # ---------- persistence ----------
    def _load(self):
        if os.path.exists(STORE_FILE):
            try:
                with open(STORE_FILE, encoding="utf-8") as f:
                    self.docs = json.load(f).get("docs", {})
            except Exception:
                self.docs = {}
        self._rebuild_index()

    def _save(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(STORE_FILE, "w", encoding="utf-8") as f:
            json.dump({"docs": self.docs}, f, ensure_ascii=False)

    # ---------- documents ----------
    def add_document(self, name: str, file_bytes: bytes, extracted: dict) -> dict:
        doc_id = hashlib.sha256(file_bytes).hexdigest()[:12]
        chunks = []
        for page in extracted["pages"]:
            for text in chunk_page_text(page["text"]):
                chunks.append(
                    {"doc_id": doc_id, "doc_name": name, "page": page["page"],
                     "method": page["method"], "text": text}
                )
        with open(os.path.join(UPLOAD_DIR, f"{doc_id}.pdf"), "wb") as f:
            f.write(file_bytes)
        self.docs[doc_id] = {
            "id": doc_id, "name": name, "page_count": extracted["page_count"],
            "total_chars": extracted["total_chars"], "ocr_engine": extracted["ocr_engine"],
            "ocr_pages": extracted["ocr_pages"],
            "pages": extracted["pages"], "chunks": chunks,
        }
        self._save()
        self._rebuild_index()
        return self.doc_summary(doc_id)

    def doc_summary(self, doc_id: str) -> dict:
        d = self.docs[doc_id]
        return {"id": d["id"], "name": d["name"], "pages": d["page_count"],
                "chars": d["total_chars"], "chunks": len(d["chunks"]),
                "ocr_engine": d["ocr_engine"], "ocr_pages": d["ocr_pages"]}

    def list_docs(self) -> list[dict]:
        return [self.doc_summary(i) for i in self.docs]

    def delete(self, doc_id: str) -> bool:
        if doc_id not in self.docs:
            return False
        del self.docs[doc_id]
        try:
            os.remove(os.path.join(UPLOAD_DIR, f"{doc_id}.pdf"))
        except OSError:
            pass
        self._save()
        self._rebuild_index()
        return True

    def all_chunks(self, doc_id: str | None = None) -> list[dict]:
        if doc_id and doc_id in self.docs:
            return self.docs[doc_id]["chunks"]
        out = []
        for d in self.docs.values():
            out.extend(d["chunks"])
        return out

    # ---------- TF-IDF index ----------
    def _rebuild_index(self):
        chunks = self.all_chunks()
        df: Counter = Counter()
        vecs = []
        for c in chunks:
            counts = Counter(tokenize(c["text"]))
            vecs.append(counts)
            for term in counts:
                df[term] += 1
        n = max(len(chunks), 1)
        self._idf = {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}
        self._chunk_vecs = []
        for counts in vecs:
            vec = {t: (1 + math.log(v)) * self._idf.get(t, 1.0) for t, v in counts.items()}
            norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
            self._chunk_vecs.append({t: v / norm for t, v in vec.items()})

    def search(self, query: str, doc_id: str | None = None, top_k: int = 5) -> list[dict]:
        chunks = self.all_chunks(doc_id)
        if not chunks or not self._chunk_vecs:
            return []
        # global index se is subset ke vector uthao
        if doc_id:
            offset = 0
            for did, d in self.docs.items():
                if did == doc_id:
                    break
                offset += len(d["chunks"])
            vecs = self._chunk_vecs[offset: offset + len(chunks)]
        else:
            vecs = self._chunk_vecs
        q_counts = Counter(tokenize(query))
        # stopwords hatao - "kya/kaise/hai" jaise shabd har Hindi page par
        # milte hain aur asal topic words (WhatsApp, steps) ko duba dete hain
        meaningful = Counter({t: c for t, c in q_counts.items() if t not in STOPWORDS})
        if meaningful:
            q_counts = meaningful
        if not q_counts:
            return []
        q_vec = {t: (1 + math.log(v)) * self._idf.get(t, 1.0) for t, v in q_counts.items()}
        q_norm = math.sqrt(sum(v * v for v in q_vec.values())) or 1.0
        q_vec = {t: v / q_norm for t, v in q_vec.items()}
        # phrase bonus: "command center" jaise exact jod (bigram) milna
        # akela shabd milne se zyada pakka sanket hai
        q_tokens = tokenize(query.lower())
        bigrams = {" ".join(q_tokens[i:i + 2]) for i in range(len(q_tokens) - 1)
                   if q_tokens[i] not in STOPWORDS and q_tokens[i + 1] not in STOPWORDS}
        scored = []
        for chunk, vec in zip(chunks, vecs):
            score = sum(q_vec.get(t, 0.0) * v for t, v in vec.items() if t in q_vec)
            if bigrams:
                text_low = chunk["text"].lower()
                score += 0.04 * sum(1 for b in bigrams if b in text_low)
            if score > 0.02:
                scored.append({**chunk, "score": round(float(score), 4)})
        scored.sort(key=lambda x: -x["score"])
        return scored[:top_k]
