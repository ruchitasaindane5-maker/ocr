"""Sawaal -> search -> jawab.

Do mode:
  1. LLM mode (best): agar `.env`/environment mein koi API key mile
     (Anthropic / OpenAI-compatible / Ollama) to mile hue passages ko
     LLM ko dekar sahi, apni bhasha mein jawab banwate hain.
  2. Offline extractive mode (default, bina key ke bhi chalega):
     PDF se sabse relevant sentences chun kar jawab + citations dete
     hain. Koi internet/model nahi chahiye.

Dono mode mein har jawab ke saath source (file + page) diya jata hai,
taaki galat jawab pakda ja sake.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

from .store import Store, tokenize

STOPWORDS = set(
    """the a an is are was were what how why when where who which in on of to for
    and or ke ka ki hai hain kya kaise karna kare mujhe batao bataiye me mein ye
    yeh wo woh se par bhi nahi to the tha thi thein ho hota hoti""".split()
)


def llm_status() -> dict:
    if os.getenv("ANTHROPIC_API_KEY"):
        return {"mode": "llm", "provider": "Anthropic (Claude)",
                "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")}
    if os.getenv("OPENAI_API_KEY"):
        return {"mode": "llm", "provider": "OpenAI-compatible",
                "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini")}
    if os.getenv("OLLAMA_HOST"):
        return {"mode": "llm", "provider": "Ollama (local)",
                "model": os.getenv("OLLAMA_MODEL", "llama3.1")}
    return {"mode": "offline", "provider": None, "model": None}


def _post_json(url: str, payload: dict, headers: dict, timeout: int = 120) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode())


def _llm_answer(question: str, hits: list[dict]) -> str | None:
    status = llm_status()
    if status["mode"] != "llm":
        return None
    context = "\n\n".join(
        f"[Source: {h['doc_name']}, page {h['page']}]\n{h['text']}" for h in hits)
    prompt = (
        "Tum ek PDF assistant ho. Neeche diye gaye PDF passages ki base par hi "
        "jawab do - bahar ki jaankari mat jodo. Agar jawab passages mein nahi "
        "hai to saaf kaho ki PDF mein nahi mila. Jawab usi bhasha/style mein do "
        "jismein sawaal puchha gaya hai (Hindi/Hinglish/English). Jawab ke "
        "akhir mein sources is format mein likho: (Source: file-name, page X)\n\n"
        f"PASSAGES:\n{context}\n\nSAWAAL: {question}\n\nJAWAB:")
    try:
        if status["provider"].startswith("Anthropic"):
            out = _post_json(
                "https://api.anthropic.com/v1/messages",
                {"model": status["model"], "max_tokens": 1024,
                 "messages": [{"role": "user", "content": prompt}]},
                {"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                 "anthropic-version": "2023-06-01"})
            return "".join(b.get("text", "") for b in out.get("content", []))
        if status["provider"].startswith("Ollama"):
            out = _post_json(
                os.environ["OLLAMA_HOST"].rstrip("/") + "/api/chat",
                {"model": status["model"], "stream": False,
                 "messages": [{"role": "user", "content": prompt}]}, {})
            return out.get("message", {}).get("content", "")
        base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        out = _post_json(
            base + "/chat/completions",
            {"model": status["model"],
             "messages": [{"role": "user", "content": prompt}]},
            {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"})
        return out["choices"][0]["message"]["content"]
    except Exception:
        return None  # LLM fail ho to offline mode par gir jao, crash nahi


def _extractive_answer(question: str, hits: list[dict], store: Store) -> str:
    """Line ko akele katne se table/context toot jata hai, isliye sabse
    matching line ke aas-paas ka pura hissa (window) uthate hain."""
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
            # rare (high-IDF) shabd milna aam shabd milne se zyada important
            score = sum(store._idf.get(t, 1.0) for t in matched) - hit_rank * 0.3
            window = " ".join(x for x in lines[max(0, i - 1): i + 5] if x)
            candidates.append((score, window, h))
    candidates.sort(key=lambda x: -x[0])
    picked, seen_keys = [], set()
    for _, window, h in candidates:
        key = re.sub(r"\W+", "", window.lower())[:80]
        if key in seen_keys or any(key in s or s in key for s in seen_keys if len(s) > 40):
            continue  # overlapping chunks se duplicate hisse na aaye
        seen_keys.add(key)
        picked.append((window, h))
        if len(picked) >= 3:
            break
    if not picked:  # koi line match nahi - top chunk ka shuru dikha do
        picked = [(hits[0]["text"][:500], hits[0])]
    lines = ["PDF mein mile sabse relevant hisso ke hisaab se:\n"]
    for window, h in picked:
        lines.append(f"• {window}  — ({h['doc_name']}, page {h['page']})")
    lines.append("\n(Tip: upar Sources mein pura page-passage padh sakte ho. "
                 "AI mode on karne par yahi jawab saaf bhasha mein milega.)")
    return "\n".join(lines)


def answer_question(store: Store, question: str, doc_id: str | None = None,
                    top_k: int = 5) -> dict:
    hits = store.search(question, doc_id=doc_id, top_k=top_k)
    status = llm_status()
    if not hits:
        return {"answer": "Is sawaal se related content kisi uploaded PDF mein "
                          "nahi mila. Pehle PDF upload/process karke dekho, ya "
                          "sawaal dusre shabdon mein puchho.",
                "sources": [], "mode": status["mode"]}
    text = _llm_answer(question, hits)
    mode_used = "llm" if text else "offline"
    if not text:
        text = _extractive_answer(question, hits, store)
    sources, seen = [], set()
    for h in hits:
        key = (h["doc_id"], h["page"])
        if key in seen:
            continue
        seen.add(key)
        sources.append({"doc_id": h["doc_id"], "doc_name": h["doc_name"],
                        "page": h["page"], "score": h["score"],
                        "method": h["method"],
                        "passage": h["text"][:600]})
    return {"answer": text, "sources": sources, "mode": mode_used,
            "provider": status["provider"] if mode_used == "llm" else None}
