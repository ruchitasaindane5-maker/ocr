"""Command-line istemal (bina browser ke).

    python cli.py add "file1.pdf" "file2.pdf" [--ocr auto|always|never]
    python cli.py list
    python cli.py ask "WhatsApp agent banane ke liye kya kya chahiye?"
    python cli.py remove <doc_id>
    python cli.py text <doc_id>          # extracted text dekho
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pdf_ocr_qa.answer import answer_question, llm_status  # noqa: E402
from pdf_ocr_qa.extract import extract_pdf  # noqa: E402
from pdf_ocr_qa.store import Store  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="PDF OCR + Q&A (CLI)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("add", help="PDF add/process karo")
    p_add.add_argument("files", nargs="+")
    p_add.add_argument("--ocr", choices=["auto", "always", "never"], default="auto")
    sub.add_parser("list", help="Add ki gayi PDFs dekho")
    p_ask = sub.add_parser("ask", help="Sawaal puchho")
    p_ask.add_argument("question")
    p_ask.add_argument("--doc", default=None, help="sirf is doc_id mein dhundho")
    p_rm = sub.add_parser("remove")
    p_rm.add_argument("doc_id")
    p_tx = sub.add_parser("text", help="Extracted text print karo")
    p_tx.add_argument("doc_id")
    args = ap.parse_args()
    store = Store()

    if args.cmd == "add":
        for path in args.files:
            print(f"Processing: {path} ...")
            with open(path, "rb") as f:
                data = f.read()
            info = store.add_document(
                os.path.basename(path), data,
                extract_pdf(path, ocr_mode=args.ocr))
            print(f"  OK -> id={info['id']} pages={info['pages']} "
                  f"chars={info['chars']} chunks={info['chunks']} "
                  f"ocr_pages={info['ocr_pages']} engine={info['ocr_engine']}")
    elif args.cmd == "list":
        docs = store.list_docs()
        if not docs:
            print("Koi PDF add nahi hai. Pehle: python cli.py add file.pdf")
        for d in docs:
            print(f"{d['id']}  {d['name']}  pages={d['pages']} "
                  f"chunks={d['chunks']} chars={d['chars']}")
        print("LLM:", llm_status())
    elif args.cmd == "ask":
        out = answer_question(store, args.question, doc_id=args.doc)
        print("\n" + out["answer"] + "\n")
        print(f"[mode: {out['mode']}"
              + (f" / {out['provider']}" if out.get("provider") else "") + "]")
    elif args.cmd == "remove":
        print("deleted" if store.delete(args.doc_id) else "not found")
    elif args.cmd == "text":
        d = store.docs.get(args.doc_id)
        if not d:
            print("doc not found")
            return
        for p in d["pages"]:
            print(f"\n===== {d['name']} - page {p['page']} [{p['method']}] =====\n{p['text']}")


if __name__ == "__main__":
    main()
