"""Question -> database search -> answer. 100% without AI.

No LLM, no API key, no embedding model. The answer is built by joining the
most relevant page passages found by FTS5/BM25 search in the SQLite
database, each with a (file, page) citation.

To be honest: without AI the system does not "write" an answer - it pulls
out the passages of the PDF that contain the words of your question.
So using the PDF's own words in the question (such as "UPI QR", "Step 3")
gives the most accurate results.
"""
from __future__ import annotations

import re

from .store import STOPWORDS, Store, tokenize


def _extractive_answer(question: str, hits: list[dict], store: Store) -> str:
    """Take the whole passage around the best-matching line (a lone line
    breaks tables/context)."""
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
            # matching a rare word (higher IDF) matters more than a common one
            score = sum(store.term_idf(t) for t in matched) - hit_rank * 0.3
            window = " ".join(x for x in lines[max(0, i - 1): i + 5] if x)
            candidates.append((score, window, h))
    candidates.sort(key=lambda x: -x[0])
    # Don't show near-duplicate passages (detected by word overlap)
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
    lines = ["Based on the most relevant passages found in the database:\n"]
    for window, h in picked:
        lines.append(f"• {window}  — ({h['doc_name']}, page {h['page']})")
    return "\n".join(lines)


def answer_question(store: Store, question: str, doc_id: str | None = None,
                    top_k: int = 5) -> dict:
    hits = store.search(question, doc_id=doc_id, top_k=top_k)
    if not hits:
        docs = ", ".join(d["name"] for d in store.list_docs()) or "no PDFs"
        return {"answer": "The words in this question were not found in any PDF.\n"
                          f"PDFs currently in the database: {docs}\n"
                          "Tip: try the exact words used in the PDF "
                          "(such as a heading or step name).",
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
