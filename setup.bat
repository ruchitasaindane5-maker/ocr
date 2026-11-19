@echo off
REM ============================================================
REM  PDF Q&A - one-command setup (Windows)
REM  Run:  setup.bat        then:  npm start
REM ============================================================
cd /d %~dp0
echo ==^> [1/4] Python virtual environment (.venv)
if not exist .venv (python -m venv .venv)
.venv\Scripts\pip install -q --upgrade pip

echo ==^> [2/4] Python packages (PDF + OCR)
.venv\Scripts\pip install -q -r requirements.txt
REM rapidocr pulls in the GUI opencv-python, which gives libGL/DLL errors on
REM some systems - the headless build is installed at the end.
.venv\Scripts\pip uninstall -y -q opencv-python 2>nul
.venv\Scripts\pip install -q --force-reinstall --no-cache-dir opencv-python-headless
.venv\Scripts\python -c "import sys; sys.path.insert(0,'.'); from pdf_ocr_qa import ocr; print('   OCR engine:', ocr.detect_engine() or 'NOT FOUND')"

echo ==^> [3/4] Node packages + Prisma Client
call npm install

echo ==^> [4/4] Database tables (Prisma/SQLite)
call npm run db:setup

echo.
echo ✅ Setup done! Now run:   npm start
echo    Then open in the browser:  http://localhost:8000
echo    (for AI, put keys in the .env file - see .env.example)
pause
