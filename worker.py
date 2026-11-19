"""PDF extraction worker (Python) — called by the Node server.

Prisma/Node handles only the database and API; reading PDFs and OCR is
PyMuPDF/Python's job. This script processes one PDF and writes the result
to a JSON file:

    python worker.py <pdf_path> <auto|always|never> <output.json>
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pdf_ocr_qa.extract import extract_pdf  # noqa: E402


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: worker.py <pdf> <ocr_mode> <out.json>", file=sys.stderr)
        return 2
    pdf_path, ocr_mode, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    # One "PROGRESS done total" line per page — the Node server reads these
    # to show progress and to tell a slow-but-working PDF from a stuck one.
    def progress(done: int, total: int) -> None:
        print(f"PROGRESS {done} {total}", flush=True)

    result = extract_pdf(pdf_path, ocr_mode=ocr_mode, progress=progress)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    print(f"pages={result['page_count']} chars={result['total_chars']} "
          f"ocr_pages={result['ocr_pages']} tables={result['tables_found']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
