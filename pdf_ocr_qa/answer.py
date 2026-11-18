"""Sawaal -> database search -> jawab. 100% bina AI ke.

Koi LLM, koi API key, koi embedding model nahi. Jawab SQLite database
mein FTS5/BM25 search se mile sabse relevant page-hisso ko jod kar
banta hai, har hisse ke saath (file, page) citation ke saath.

Sach baat: bina AI ke system jawab "likhta" nahi hai - ye PDF mein se
wo hisse nikal kar deta hai jinmein tumhare sawaal ke shabd mile hain.
Isliye sawaal mein PDF ke hi shabd (jaise "UPI QR", "Step 3") use
karne se sabse sahi result milta hai.
"""
from __future__ import annotations

import re

from .store import STOPWORDS, Store, tokenize


def _extractive_answer(question: str, hits: list[dict], store: Store) -> str:
    """Sabse matching line ke aas-paas ka pura hissa uthao (table/context
    akeli line katne se toot jata hai)."""
    q_terms = {t for t in tokenize(question) if t not in STOPWORDS}
    if not q_terms:
        q_terms = set(tokenize(question))
    candidates = []
    for hit_rank, h in enumerate(hits):
        lines = [ln.strip() for ln in h["text"].splitlines()]
        for i, line in enumerate(lines):
            if len(line) < 15 or "trademark" in line.lower():
                continue
            matched = q_terms & set(tokenize(line))
            if not matched:
                continue
            # rare shabd (zyada IDF) milna aam shabd se zyada important
            score = sum(store.term_idf(t) for t in matched) - hit_rank * 0.3
            window = " ".join(x for x in lines[max(0, i - 1): i + 5] if x)
            candidates.append((score, window, h))
    candidates.sort(key=lambda x: -x[0])
    # Milte-julte hisse dobara mat dikhao (shabd-overlap se pehchano)
    picked, picked_tokens = [], []
    for _, window, h in candidates:
        toks = set(tokenize(window))
        if any(len(toks & pt) / max(1, min(len(toks), len(pt))) > 0.6
               for pt in picked_tokens):
            continue
        picked.append((window, h))
        picked_tokens.append(toks)
        if len(picked) >= 3:
            break
    if not picked:
        picked = [(hits[0]["text"][:500], hits[0])]
    lines = ["Database mein mile sabse relevant hisso ke hisaab se:\n"]
    for window, h in picked:
        lines.append(f"• {window}  — ({h['doc_name']}, page {h['page']})")
    return "\n".join(lines)


def answer_question(store: Store, question: str, doc_id: str | None = None,
                    top_k: int = 5) -> dict:
    hits = store.search(question, doc_id=doc_id, top_k=top_k)
    if not hits:
        docs = ", ".join(d["name"] for d in store.list_docs()) or "koi PDF nahi"
        return {"answer": "Is sawaal ke shabd kisi PDF mein nahi mile.\n"
                          f"Database mein abhi ye PDFs hain: {docs}\n"
                          "Tip: PDF mein use hue exact shabd try karo "
                          "(jaise heading ya step ka naam).",
                "sources": [], "mode": "database-search"}
    sources, seen = [], set()
    for h in hits:
        key = (h["doc_id"], h["page"])
        if key in seen:
            continue
        seen.add(key)
        sources.append({"doc_id": h["doc_id"], "doc_name": h["doc_name"],
                        "page": h["page"], "score": h["score"],
                        "method": h["method"], "passage": h["text"][:600]})
    return {"answer": _extractive_answer(question, hits, store),
            "sources": sources, "mode": "database-search"}
