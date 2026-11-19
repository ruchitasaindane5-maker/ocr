# How to Run PDF Q&A (Windows)

A short, practical guide to get the app running on a Windows PC.
For the full feature list see [README.md](README.md); for cloud hosting see [AWS_DEPLOY.md](AWS_DEPLOY.md).

---

## 1. Install the prerequisites (one time)

| Tool | Version | Get it from | Check with |
|---|---|---|---|
| Node.js | 20.19 or newer | https://nodejs.org | `node --version` |
| Python | 3.10 or newer (3.13 works) | https://python.org — tick **"Add Python to PATH"** | `python --version` |
| Ollama *(optional, local AI)* | latest | https://ollama.com or `winget install Ollama.Ollama` | `ollama --version` |

## 2. Set up the project (one time)

Open a terminal in the project folder and run:

```bat
cd C:\Users\LENOVO\Desktop\ocr_pdf
setup.bat
```

`setup.bat` does everything:
1. Creates the Python virtual environment in `.venv`
2. Installs the PDF/OCR libraries (and swaps in headless OpenCV)
3. Runs `npm install` and generates the Prisma Client
4. Creates the database at `data\pdf_qa.db`

When it finishes it prints the OCR engine it found — it should say `rapidocr`.

## 3. Add AI keys (optional)

The app works **without any AI** (it answers with the matching PDF passages).
For written answers, create the `.env` file:

```bat
copy .env.example .env
notepad .env
```

Fill in any keys you have — each one is optional:

| Provider | Key in `.env` | Free key from |
|---|---|---|
| GLM (z.ai) | `GLM_API_KEY=` | https://z.ai/manage-apikey/apikey-list |
| NVIDIA NIM | `NVIDIA_API_KEY=` | https://build.nvidia.com |
| OpenRouter | `OPENROUTER_API_KEY=` | https://openrouter.ai/keys |
| Google Gemini | `GEMINI_API_KEY=` | https://aistudio.google.com/apikey |

> Never commit `.env` or share your keys — `.gitignore` already excludes it.

## 4. Set up local AI with Ollama (optional, free, offline)

```bat
ollama pull qwen2.5:7b
```

This downloads ~4.7 GB once. Keep the Ollama app running (it sits in the system tray).
The app uses Ollama **first**, then falls back to GLM → NVIDIA → OpenRouter → Gemini.
If your PC feels slow, add `OLLAMA_MODEL=qwen2.5:3b` to `.env` for a lighter model.

## 5. Start the app

```bat
npm start
```

Wait for:

```
PDF OCR + Prisma Q&A running at: http://localhost:8000
```

Then open **http://localhost:8000** in your browser. Stop the server with `Ctrl+C`.

## 6. Use it

1. **Upload** — drag PDFs into the upload box, or click it and pick several with `Ctrl`/`Shift` (up to 20 at once, 1 GB each).
2. **Wait** — the box shows live progress: `Page 240 / 960 · 25% · about 45m left`.
3. **Ask** — type a question; the answer shows the source file and page number.
4. **Manage** — each PDF card has **📖 View data**, **💬 Ask this PDF**, **TXT/CSV/JSON** export and **🗑 Delete**. **🗑 Delete all** appears when there are 2+ PDFs.

Your data stays in `data\pdf_qa.db` — it is still there after a restart, no need to upload again.

## 7. Check the AI keys

In the app, click **🔑 Test All AI** in the left panel. Each provider shows ✅ with its response time, or ❌ with the reason.

---

## Large scanned PDFs — what to expect

Scanned PDFs (photos of pages, no text layer) need OCR on **every page**, about **4–5 seconds per page**:

| Pages | Approx. time |
|---|---|
| 100 | ~8 min |
| 660 | ~45 min |
| 1,000 | ~1 hr 10 min |

- There is **no total time limit**. A PDF is only stopped if no page finishes for 10 minutes (OCR stuck). Change this with `WORKER_TIMEOUT_MS` in `.env`.
- **Don't stop or restart the server** while a big PDF is processing — the work in progress is lost and must be uploaded again.
- Upload one big PDF at a time; two at once just makes both slower.
- Refreshing the browser is fine — the progress reappears in the upload box.

## Useful settings in `.env`

| Setting | Default | Meaning |
|---|---|---|
| `PORT` | `8000` | Port the app runs on |
| `MAX_UPLOAD_MB` | `1024` | Max size per uploaded file |
| `WORKER_TIMEOUT_MS` | `600000` (10 min) | Stop a PDF if no page finishes for this long |
| `AI_PROVIDER_ORDER` | `ollama,glm,nvidia,openrouter,gemini` | Order in which AIs are tried |
| `AI_MODE` | *(on)* | Set to `off` to use database search only |
| `OLLAMA_MODEL` | `qwen2.5:7b` | Local model name |

## Troubleshooting

| Problem | Fix |
|---|---|
| `setup.bat` fails on `rapidocr-onnxruntime` | Pull the latest `requirements.txt` (it pins a version that works on Python 3.13) and run `setup.bat` again |
| "Python worker failed to start" on upload | Run `setup.bat` again. Don't set `PYTHON_BIN` in `.env` unless you know you need it — the app finds `.venv` by itself |
| Page says it can't connect to the server | Make sure `npm start` is still running in the terminal |
| Port 8000 already in use | Close the other server, or set `PORT=8001` in `.env` |
| Ollama shows "not running" | Open the Ollama app (or run `ollama serve`) and refresh the page |
| Ollama shows "model not downloaded" | `ollama pull qwen2.5:7b` |
| An AI shows `HTTP 429` / `503` | That provider is overloaded or rate-limited; the next one in the chain answers automatically |
| An AI shows `HTTP 404` / `410` (model gone) | The provider retired that model — set a current one, e.g. `GEMINI_MODEL=` / `NVIDIA_MODEL=` in `.env` |
| Scanned PDF gives "no OCR engine" warning | Run `setup.bat` again; it must print `OCR engine: rapidocr` |
| Hindi text in scans reads poorly | Install Tesseract with the Hindi (hin) language, then `.venv\Scripts\pip install pytesseract Pillow` |

## Command cheat sheet

```bat
setup.bat                 :: one-time setup
npm start                 :: run the app  ->  http://localhost:8000
npm run db:studio         :: browse the database in Prisma Studio
ollama pull qwen2.5:7b    :: download the local AI model
ollama list               :: see downloaded models
```
