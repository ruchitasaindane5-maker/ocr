"""PDF OCR + Database Q&A (bina AI) - web app.

    pip install -r requirements.txt
    uvicorn app:app --host 0.0.0.0 --port 8000
Browser mein http://localhost:8000 kholo. Sab data data/pdf_qa.db
(SQLite database) mein save hota hai.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, File, Form, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from pdf_ocr_qa import ocr as ocr_mod  # noqa: E402
from pdf_ocr_qa.answer import answer_question  # noqa: E402
from pdf_ocr_qa.extract import extract_pdf  # noqa: E402
from pdf_ocr_qa.store import Store  # noqa: E402

app = FastAPI(title="PDF OCR Q&A (No AI, SQLite)")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])
store = Store()
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


@app.get("/")
def home():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/api/status")
def status():
    return {"mode": "no-ai (database search)", "ocr_engine": ocr_mod.detect_engine(),
            "database": store.stats()}


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
            if data[:4] != b"%PDF":
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
                                        "OCR 'always' karke dobara try karo."})
                continue
            saved = store.add_document(f.filename, data, extracted)
            saved["saved_in_db"] = True
            results.append(saved)
        except Exception as e:  # ek file fail ho to baki rukni nahi chahiye
            errors.append({"name": f.filename, "error": str(e)[:300]})
    return {"added": results, "errors": errors}


@app.delete("/api/docs/{doc_id}")
def delete_doc(doc_id: str):
    return {"deleted": store.delete(doc_id)}


@app.get("/api/docs/{doc_id}/text")
def doc_text(doc_id: str):
    d = store.get_document(doc_id)
    if not d:
        return JSONResponse({"error": "doc not found"}, status_code=404)
    return {"name": d["name"], "pages": d["pages"]}


@app.get("/api/docs/{doc_id}/export")
def export_doc(doc_id: str, format: str = "txt"):
    d = store.get_document(doc_id)
    if not d:
        return JSONResponse({"error": "doc not found"}, status_code=404)
    base = os.path.splitext(d["name"])[0]
    if format == "json":
        payload = {**d, "chunks": store.all_chunks(doc_id)}
        return Response(json.dumps(payload, ensure_ascii=False, indent=1),
                        media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{base}.json"'})
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["document", "page", "method", "chars", "text"])
        for p in d["pages"]:
            w.writerow([d["name"], p["page"], p["method"], len(p["text"]), p["text"]])
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{base}.csv"'})
    txt = "\n".join(f"\n===== Page {p['page']} [{p['method']}] =====\n{p['text']}"
                    for p in d["pages"])
    return Response(txt, media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{base}.txt"'})


class AskBody(BaseModel):
    question: str
    doc_id: str | None = None


@app.post("/api/ask")
def ask(body: AskBody):
    q = body.question.strip()
    if not q:
        return JSONResponse({"error": "Sawaal khali hai"}, status_code=400)
    if not store.stats()["docs"]:
        return {"answer": "Pehle kam se kam ek PDF upload karo, phir sawaal puchho.",
                "sources": [], "mode": "database-search"}
    return answer_question(store, q, doc_id=body.doc_id or None)
