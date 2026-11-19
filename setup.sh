#!/usr/bin/env bash
# ============================================================
#  PDF Q&A — one-command setup (Linux / macOS)
#  Run:  bash setup.sh     then:  npm start
# ============================================================
set -e
cd "$(dirname "$0")"
echo "==> [1/4] Python virtual environment (.venv)"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip

echo "==> [2/4] Python packages (PDF + OCR)"
.venv/bin/pip install -q -r requirements.txt
# rapidocr pulls in the GUI opencv-python, which gives a libGL error on
# headless systems (server/WSL). Remove it and reinstall the headless
# build at the end — this order is what works.
.venv/bin/pip uninstall -y -q opencv-python 2>/dev/null || true
.venv/bin/pip install -q --force-reinstall --no-cache-dir opencv-python-headless
.venv/bin/python -c "import sys; sys.path.insert(0,'.'); from pdf_ocr_qa import ocr; print('   OCR engine:', ocr.detect_engine() or 'NOT FOUND — scanned PDFs will use the text layer only')"

echo "==> [3/4] Node packages + Prisma Client"
npm install

echo "==> [4/4] Database tables (Prisma/SQLite)"
npm run db:setup

echo ""
echo "✅ Setup done! Now run:   npm start"
echo "   Then open in the browser:  http://localhost:8000"
echo "   (for AI, put keys in the .env file — see .env.example)"
