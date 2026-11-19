# 📄 PDF OCR + Prisma Database Q&A + AI Fallback Chain

**Drop in any PDF and its data is properly extracted and saved to a SQLite
database via Prisma ORM. Questions are answered first by the AI fallback
chain (Ollama local → GLM → NVIDIA → OpenRouter → Gemini); if no AI works,
you still get the database-search answer — the app never stops.
The whole system works even without any key.**

```
Browser ─► Node/Express server ─► Python worker (PDF + OCR: PyMuPDF)
                    │                         │
                    │      extracted pages (JSON)
                    │◄────────────────────────┘
                    ▼
          Prisma ORM (models: Document · Page · Chunk)
                    ▼
          SQLite database — data/pdf_qa.db
          (+ FTS5 full-text index, BM25 search)
                    ▼
  Question ─► search (pages) ─► AI chain: Ollama → GLM → NVIDIA → OpenRouter → Gemini
                    │                    │ all fail
                    └────────────────────▼
                  database-search answer + (file, page) source
```

---

## ▶️ How to run (step by step)

> **Quick Windows guide:** [HOW_TO_RUN.md](HOW_TO_RUN.md) — setup, keys, Ollama, large PDFs and troubleshooting on one page.

**Video guides:** [Setup, code-flow deep dive and AWS deploy](brag-output/video-guide.md) (Hinglish audio) — MP4 downloads, chapter timestamps and copy-paste commands.
**Prototype + technology film (English audio):** [prototype-tech-video.mp4](brag-output/prototype-tech-video.mp4) — 3:22, real app screenshots, architecture, the AI fallback chain, every library and model, and the five open-source repositories behind the build. English + Hinglish subtitle tracks. The presentable stack document is [docs/Prototype_Technology_Stack.docx](docs/Prototype_Technology_Stack.docx).

### These two must be installed first
- **Node.js 20.19+** — https://nodejs.org
- **Python 3.10+** — https://python.org (on Windows, tick
  *"Add Python to PATH"* during install)

### Step 1 — Go to the project folder
```bash
cd ocr_pdf
```

### Easiest way — one-command setup (recommended)

```bash
bash setup.sh        # Linux/Mac   (on Windows: setup.bat)
npm start
```

`setup.sh` creates `.venv` itself, installs all Python/Node libraries in
the right order (it also handles the headless-OpenCV libGL hassle),
generates the Prisma Client and prepares the database tables. Then open
**http://localhost:8000** in the browser.

### Doing it by hand

### Step 2 — Python (PDF/OCR) libraries
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# rapidocr brings the GUI opencv-python, which gives a libGL error on
# some systems — so always run these two commands at the end:
.venv/bin/pip uninstall -y opencv-python
.venv/bin/pip install --force-reinstall opencv-python-headless
```
On Windows use `.venv\Scripts\pip` instead of `.venv/bin/pip`.

### Step 3 — Node + Prisma install
```bash
npm install
```
This installs `@prisma/client`, `prisma`, `express` etc. and generates
the Prisma Client.

### Step 4 — Database (optional)
```bash
npm run db:setup
```
This creates `data/pdf_qa.db` and prepares the model tables
(`documents`, `pages`, `chunks` + FTS5 index).
*(It's fine if you forget this step — the server creates the tables
itself on first boot. The standard Prisma way: `npx prisma db push`.)*

To browse the database, use Prisma Studio:
```bash
npm run db:studio
```

### Step 5 (A) — Set up local Ollama (best option — just for your PC)

Your laptop: **16 GB RAM + 6 GB graphics card** — the perfect model for
it is **`qwen2.5:7b`** (~4.7 GB download):

1. Install Ollama from https://ollama.com (the Windows app keeps running in the tray)
2. Download the model in a terminal:
   ```bash
   ollama pull qwen2.5:7b
   ```
3. That's it — when the server starts, Ollama is **automatically first in
   the chain**. No key, no internet, no cost.

Why this model is best for your (16 GB RAM) laptop:
- The model is ~4.7 GB — most of it stays in 6 GB VRAM (graphics card),
  so it runs comfortably on 16 GB RAM and answers come fast
  (about 4–10 sec)
- Qwen handles Hindi/Hinglish best (your PDFs are mixed)
- The code sets context `num_ctx 8192`, so long PDF passages are not
  truncated
- ⚠️ Don't use `qwen2.5:14b` on 16 GB RAM — the 9 GB model fills the RAM
  and the laptop may slow down/hang. Stick with 7B.
- If it still feels slow (e.g. with many Chrome tabs open), set
  `OLLAMA_MODEL=qwen2.5:3b` in `.env` — a lighter model with simpler but
  faster answers. Keep heavy apps closed while the model runs for the
  best speed.

### Step 5 (B) — Add free AI keys (optional, as backup)
Copy `.env.example` to `.env` and fill in the keys
(adding all of them is recommended — the fallback chain only works then):

| API | Where to get a free key | In .env |
|---|---|---|
| **GLM (z.ai)** | https://z.ai/manage-apikey/apikey-list — free model `glm-4.7-flash` | `GLM_API_KEY=` |
| **NVIDIA NIM** | https://build.nvidia.com → *Get API Key* (`nvapi-...`) | `NVIDIA_API_KEY=` |
| **OpenRouter** | https://openrouter.ai/keys — free `:free` models (`sk-or-...`) | `OPENROUTER_API_KEY=` |
| **Google Gemini** | https://aistudio.google.com/apikey | `GEMINI_API_KEY=` |

After adding keys and starting the server, the website's left panel
shows ✅ for each one, and the **"🔑 Test All AI"** button tests every
key live.

**How the fallback works:** for a question, the relevant PDF pages are
found first, then sent to the AI in the order **Ollama (local) → GLM →
NVIDIA → OpenRouter → Gemini**. If Ollama is down it is silently skipped
and the cloud chain runs. If an API fails (wrong key, rate-limit 429,
timeout, server down) the next one is tried automatically — the answer
footer even shows *"failed first: GLM"* so you know the next API was used.
If all of them fail, you get the database-search answer.
To change the order, set something like `AI_PROVIDER_ORDER=gemini,glm,nvidia`
in `.env`; to turn AI off completely, `AI_MODE=off`.

### Step 6 — Run the server
```bash
npm start
```
Open in the browser: **http://localhost:8000**

Then: **① upload a PDF → ② "Saved to database" appears →
③ ask a question.** Stop the server with `Ctrl+C`. When you run
`npm start` again, the old data loads from the database automatically —
no need to upload again.

> **Windows note:** if upload shows a "Python worker failed to start"
> error, copy `.env.example` to `.env` and set `PYTHON_BIN=python` in it
> (`python3` on Linux/Mac).

### Old Python-only way (optional)
`app.py` (FastAPI) and `cli.py` are still in the repo and use the same
database file, but **the main server is now Node + Prisma**.

### ☁️ Deploying to AWS?
See the full step-by-step guide: **[AWS_DEPLOY.md](AWS_DEPLOY.md)**
(The Docker image is ready — `Dockerfile` + `docker-compose.yml` +
`/api/health` health check. On EC2, `docker compose up -d --build`
runs the whole product; there Ollama is skipped and the cloud AI chain
runs.)

---

## 🗄️ Prisma Models (prisma/schema.prisma)

| Model | What is saved |
|---|---|
| `Document` | PDF name, sha256, size, total pages/chars, OCR stats, when it was added |
| `Page` | Each page's extracted text + method (`text` / `ocr:...`) |
| `Chunk` | ~900 char pieces for search, with the page number |
| `chunks_fts` | FTS5 virtual table (can't be a Prisma model — created with raw SQL, search uses BM25 ranking) |

All database operations go through Prisma Client
(`server/store.ts`, `server/prisma.ts`) — `document.upsert`,
`page.createMany`, `chunk.findMany` etc. Database file:
**`data/pdf_qa.db`**. Uploading the same PDF again does not create a
duplicate — the same `Document` is updated.

## ❓ "Will it work with any PDF?"

Yes — every effort is made to extract text from any PDF that opens.
All of this has been tested and verified:

| PDF condition | Result |
|---|---|
| Normal digital PDF (made from Word/Chrome) | ✅ Text layer, in reading order |
| Multi-column PDF | ✅ The whole left column first, then the right column |
| PDF with tables | ✅ In `Product \| 55000 \| 12` format — easy to find rates |
| Scanned PDF (image only, 0 text) | ✅ Text extracted via OCR (test: 1,328 chars) and saved to DB |
| Screenshot/Canva PDF (both of your guides) | ✅ Text + OCR merged, duplicates removed |
| Broken/garbled text layer | ✅ OCR text used when quality check fails |
| PDF with forms | ✅ Form values included in the text |
| Same header/footer on every page | ✅ Removed automatically (keeps search clean) |

**Honest limitations (hiding them would be wrong):**
- 🔒 Password-protected PDFs must be unlocked first (a clear error is shown).
- ✍️ OCR won't read handwriting well — printed text works best.
- 🇮🇳 Tesseract (hin) is best for printed Hindi text
  (see below); the default RapidOCR is strong in English.
- If no AI key is set (or all of them fail), the answer is not
  *"written"* — you get the relevant PDF passages with page numbers.
  Use the PDF's exact words in your question:
  `"How is a UPI QR created?"`, `"Laptop price stock"`. As soon as AI keys
  are added, the AI turns those same passages into a clean answer.

## 🔍 OCR engine

Priority: **Tesseract → EasyOCR → RapidOCR** (whichever is found first).
For Hindi: Ubuntu `sudo apt install tesseract-ocr tesseract-ocr-hin`
· on Windows tick *Hindi (hin)* in the UB-Mannheim Tesseract installer,
then `pip install pytesseract Pillow`. The default RapidOCR works with
just `pip install`.

## 📁 Files

| File | Purpose |
|---|---|
| `setup.sh` · `setup.bat` | One-command setup (venv, libraries, Prisma, DB) |
| `prisma/schema.prisma` | Prisma models (Document/Page/Chunk) |
| `prisma.config.ts` | Prisma + SQLite path config |
| `server/index.ts` | Express API + serves the web UI |
| `server/store.ts` | All DB operations via Prisma ORM |
| `server/search.ts` · `server/answer.ts` | FTS5/BM25 + TF-IDF search, answers |
| `server/ai.ts` | AI fallback chain (Ollama → GLM → NVIDIA → OpenRouter → Gemini) |
| `server/worker.ts` | Calls the Python extraction worker (with a timeout) |
| `worker.py` + `pdf_ocr_qa/` | PDF reading + OCR (Python/PyMuPDF) |
| `static/index.html` | Browser UI (upload, DB panel, AI panel, chat, export) |
| `scripts/init-db.mjs` | Reliable way to create tables without `prisma db push` |
| `data/pdf_qa.db` | Your database (created automatically, not committed to git) |

Every PDF card has **⬇ TXT / CSV / JSON export** — so you can check for
yourself whether the data came out properly.

## 🔧 What was fixed in the full audit (Nov 2026)

- **The server crashed on a fresh DB** — the tables were never created.
  Now the server prepares the schema itself on boot.
- **OCR failed silently** (libGL error from the GUI `opencv-python`) —
  the setup script now installs the headless build in the right order,
  and if no engine is found a clear warning is shown on upload.
- **A filename could run a script in the UI (XSS)** — names are now
  always set as text; the server sanitises names too.
- An API error no longer **crashes the whole server** (you get clean JSON
  errors); path traversal and header-breaking names on upload/download
  are blocked; limits on large files (1 GB, configurable) and long questions (2000
  characters).
- No more unique-constraint crash when the same PDF is uploaded twice /
  concurrently — everything is saved in one transaction.
- **Stall timeout** on the Python worker — it is stopped only if no page
  finishes for 10 minutes, so 1000+ page scanned PDFs can run for hours
  while a stuck OCR still can't hang the system; the UI shows live page
  progress with time left; leftover temp files are cleaned up automatically.
  Uploads up to 1 GB per file (`MAX_UPLOAD_MB`).
- Answers no longer repeat **near-duplicate passages**; answers are faster
  on large databases (IDF is built only once).
- New UI: toast notifications, upload progress + timer, typing
  indicator, example-question chips, answer copy button, chat first on
  mobile, banner when the server is down, confirmation before delete.
