"""PDF OCR Q&A - web app.

Chalane ke liye:
    pip install -r requirements.txt
    uvicorn app:app --host 0.0.0.0 --port 8000
Phir browser mein http://localhost:8000 kholo.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# .env file ho to load karo (bina python-dotenv ke, simple parser)
_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env):
    for _line in open(_env, encoding="utf-8"):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from fastapi import FastAPI, File, Form, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from pdf_ocr_qa import ocr as ocr_mod  # noqa: E402
from pdf_ocr_qa.answer import answer_question, llm_status  # noqa: E402
from pdf_ocr_qa.extract import extract_pdf  # noqa: E402
from pdf_ocr_qa.store import Store  # noqa: E402

app = FastAPI(title="PDF OCR Q&A")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])
store = Store()
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


@app.get("/")
def home():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/api/status")
def status():
    return {"llm": llm_status(), "ocr_engine": ocr_mod.detect_engine(),
            "docs": len(store.docs)}


@app.get("/api/docs")
def docs():
    return store.list_docs()


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...),
                 ocr_mode: str = Form("auto")):
    results, errors = [], []
    for f in files:
        try:
            data = await f.read()
            if not data[:4] == b"%PDF":
                errors.append({"name": f.filename, "error": "Ye PDF file nahi hai"})
                continue
            tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "data", f"_tmp_{os.getpid()}_{f.filename}")
            os.makedirs(os.path.dirname(tmp), exist_ok=True)
            with open(tmp, "wb") as fh:
                fh.write(data)
            try:
                extracted = extract_pdf(tmp, ocr_mode=ocr_mode)
            finally:
                os.remove(tmp)
            if extracted["total_chars"] < 20:
                errors.append({"name": f.filename,
                               "error": "Is PDF se text nahi nikal paya. "
                                        "OCR mode 'always' karke dobara try karo."})
                continue
            results.append(store.add_document(f.filename, data, extracted))
        except Exception as e:  # ek file fail ho to baki rukni nahi chahiye
            errors.append({"name": f.filename, "error": str(e)[:300]})
    return {"added": results, "errors": errors}


@app.delete("/api/docs/{doc_id}")
def delete_doc(doc_id: str):
    return {"deleted": store.delete(doc_id)}


@app.get("/api/docs/{doc_id}/text")
def doc_text(doc_id: str):
    d = store.docs.get(doc_id)
    if not d:
        return JSONResponse({"error": "doc not found"}, status_code=404)
    return {"name": d["name"], "pages": d["pages"]}


class AskBody(BaseModel):
    question: str
    doc_id: str | None = None


@app.post("/api/ask")
def ask(body: AskBody):
    q = body.question.strip()
    if not q:
        return JSONResponse({"error": "Sawaal khali hai"}, status_code=400)
    if not store.docs:
        return {"answer": "Pehle kam se kam ek PDF upload karo, phir sawaal puchho.",
                "sources": [], "mode": "offline"}
    return answer_question(store, q, doc_id=body.doc_id or None)
