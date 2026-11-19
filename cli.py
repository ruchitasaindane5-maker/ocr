"""Command-line usage (no browser, no AI).

    python cli.py add "file1.pdf" ["file2.pdf"] [--ocr auto|always|never]
    python cli.py list                 # PDFs saved in the database
    python cli.py status               # database info
    python cli.py ask "How is a UPI QR created?"
    python cli.py text <doc_id>        # view extracted text
    python cli.py export <doc_id> --format txt|csv|json
    python cli.py remove <doc_id>
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pdf_ocr_qa.answer import answer_question  # noqa: E402
from pdf_ocr_qa.extract import extract_pdf  # noqa: E402
from pdf_ocr_qa.store import Store  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="PDF OCR + Database Q&A (No AI)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("add", help="Process PDFs and save them to the database")
    p_add.add_argument("files", nargs="+")
    p_add.add_argument("--ocr", choices=["auto", "always", "never"], default="auto")
    sub.add_parser("list")
    sub.add_parser("status")
    p_ask = sub.add_parser("ask")
    p_ask.add_argument("question")
    p_ask.add_argument("--doc", default=None)
    p_rm = sub.add_parser("remove")
    p_rm.add_argument("doc_id")
    p_tx = sub.add_parser("text")
    p_tx.add_argument("doc_id")
    p_ex = sub.add_parser("export")
    p_ex.add_argument("doc_id")
    p_ex.add_argument("--format", choices=["txt", "csv", "json"], default="txt")
    args = ap.parse_args()
    store = Store()

    if args.cmd == "add":
        for path in args.files:
            print(f"Processing: {path} ...")
            try:
                if not os.path.isfile(path):
                    print(f"  ERROR: file not found: {path}")
                    continue
                with open(path, "rb") as f:
                    data = f.read()
                if data[:4] != b"%PDF":
                    print("  ERROR: this is not a PDF file")
                    continue
                info = store.add_document(os.path.basename(path), data,
                                          extract_pdf(path, ocr_mode=args.ocr))
            except Exception as e:  # one failing file must not stop the rest
                print(f"  ERROR: {str(e)[:300]}")
                continue
            print(f"  SAVED IN DB -> id={info['id']} pages={info['pages']} "
                  f"chars={info['chars']} chunks={info['chunks']} "
                  f"tables={info['tables_found']} ocr_pages={info['ocr_pages']}")
    elif args.cmd == "list":
        docs = store.list_docs()
        if not docs:
            print("Database is empty. First run: python cli.py add file.pdf")
        for d in docs:
            print(f"{d['id']}  {d['name']}  pages={d['pages']} chunks={d['chunks']} "
                  f"chars={d['chars']} added={d['created_at']}")
    elif args.cmd == "status":
        print(json.dumps(store.stats(), indent=1, ensure_ascii=False))
    elif args.cmd == "ask":
        out = answer_question(store, args.question, doc_id=args.doc)
        print("\n" + out["answer"] + "\n\n[mode: database-search, no AI]")
    elif args.cmd == "remove":
        print("deleted" if store.delete(args.doc_id) else "not found")
    elif args.cmd == "text":
        d = store.get_document(args.doc_id)
        if not d:
            print("doc not found")
            return
        for p in d["pages"]:
            print(f"\n===== {d['name']} - page {p['page']} [{p['method']}] =====\n{p['text']}")
    elif args.cmd == "export":
        d = store.get_document(args.doc_id)
        if not d:
            print("doc not found")
            return
        base = os.path.splitext(d["name"])[0]
        base = "".join(c if c not in '\\/:*?"<>|' else "_" for c in base)[:120] or "document"
        out_path = f"{base}_extracted.{args.format}"
        if args.format == "json":
            payload = {**d, "chunks": store.all_chunks(args.doc_id)}
            open(out_path, "w", encoding="utf-8").write(
                json.dumps(payload, ensure_ascii=False, indent=1))
        elif args.format == "csv":
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["document", "page", "method", "chars", "text"])
            for p in d["pages"]:
                w.writerow([d["name"], p["page"], p["method"], len(p["text"]), p["text"]])
            open(out_path, "w", encoding="utf-8", newline="").write(buf.getvalue())
        else:
            open(out_path, "w", encoding="utf-8").write("\n".join(
                f"\n===== Page {p['page']} [{p['method']}] =====\n{p['text']}"
                for p in d["pages"]))
        print(f"Exported -> {out_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as e:  # a clean message instead of a traceback
        print(f"Error: {str(e)[:400]}")
        raise SystemExit(1)
