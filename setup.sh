#!/usr/bin/env bash
# ============================================================
#  PDF Q&A — ek-command setup (Linux / macOS)
#  Chalao:  bash setup.sh     phir:  npm start
# ============================================================
set -e
cd "$(dirname "$0")"
echo "==> [1/4] Python virtual environment (.venv)"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip

echo "==> [2/4] Python packages (PDF + OCR)"
.venv/bin/pip install -q -r requirements.txt
# rapidocr apne saath GUI wala opencv-python laata hai jo headless
# systems (server/WSL) par libGL error deta hai. Use hatakar headless
# ko aakhir mein dobara lagate hain — yehi order kaam karta hai.
.venv/bin/pip uninstall -y -q opencv-python 2>/dev/null || true
.venv/bin/pip install -q --force-reinstall --no-cache-dir opencv-python-headless
.venv/bin/python -c "import sys; sys.path.insert(0,'.'); from pdf_ocr_qa import ocr; print('   OCR engine:', ocr.detect_engine() or 'NAHI MILA — scanned PDF par text-layer hi chalega')"

echo "==> [3/4] Node packages + Prisma Client"
npm install

echo "==> [4/4] Database tables (Prisma/SQLite)"
npm run db:setup

echo ""
echo "✅ Setup ho gaya! Ab chalao:   npm start"
echo "   Phir browser mein kholo:  http://localhost:8000"
echo "   (AI ke liye .env file mein keys lagana — .env.example dekho)"
