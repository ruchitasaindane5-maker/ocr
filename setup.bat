@echo off
REM ============================================================
REM  PDF Q&A - ek-command setup (Windows)
REM  Chalao:  setup.bat        phir:  npm start
REM ============================================================
cd /d %~dp0
echo ==^> [1/4] Python virtual environment (.venv)
if not exist .venv (python -m venv .venv)
.venv\Scripts\pip install -q --upgrade pip

echo ==^> [2/4] Python packages (PDF + OCR)
.venv\Scripts\pip install -q -r requirements.txt
REM rapidocr apne saath GUI wala opencv-python laata hai jo kuch
REM systems par libGL/DLL error deta hai - headless ko aakhir mein lagate hain.
.venv\Scripts\pip uninstall -y -q opencv-python 2>nul
.venv\Scripts\pip install -q --force-reinstall --no-cache-dir opencv-python-headless
.venv\Scripts\python -c "import sys; sys.path.insert(0,'.'); from pdf_ocr_qa import ocr; print('   OCR engine:', ocr.detect_engine() or 'NAHI MILA')"

echo ==^> [3/4] Node packages + Prisma Client
call npm install

echo ==^> [4/4] Database tables (Prisma/SQLite)
call npm run db:setup

echo.
echo ✅ Setup ho gaya! Ab chalao:   npm start
echo    Phir browser mein kholo:  http://localhost:8000
echo    (AI ke liye .env file mein keys lagana - .env.example dekho)
pause
