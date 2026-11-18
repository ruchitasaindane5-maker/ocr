# 📄 PDF OCR + Prisma Database Q&A + AI Fallback Chain

**Jo bhi PDF daalo, uska data proper nikal kar Prisma ORM se SQLite
database mein save hota hai. Sawaal ka jawab pehle AI fallback chain
(Ollama local → GLM → NVIDIA → Gemini) se aata hai; koi AI na chale
to database search ka jawab mil hi jata hai — app kabhi rukti nahi.
Bina kisi key ke bhi poora system chalta hai.**

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
     Sawaal ─► search (pages) ─► AI chain: Ollama → GLM → NVIDIA → Gemini
                    │                    │ sab fail
                    └────────────────────▼
                  database-search jawab + (file, page) source
```

---

## ▶️ Chalane ka tareeka (step-by-step)

### Pehle ye dono install hone chahiye
- **Node.js 20.19+** — https://nodejs.org
- **Python 3.10+** — https://python.org (Windows par install ke time
  *"Add Python to PATH"* tick karna)

### Step 1 — Project folder mein aao
```bash
cd ocr_pdf
```

### Sabse aasan tareeka — ek-command setup (recommended)

```bash
bash setup.sh        # Linux/Mac   (Windows par: setup.bat)
npm start
```

`setup.sh` khud `.venv` banata hai, saari Python/Node libraries sahi
order mein install karta hai (OpenCV headless wala libGL-jhanjhat
bhi khud sambhalta hai), Prisma Client generate karta hai aur
database tables ready karke deta hai. Phir browser mein
**http://localhost:8000** kholo.

### Haath se karna ho to

### Step 2 — Python (PDF/OCR) ki libraries
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# rapidocr apne saath GUI-wala opencv-python laata hai jo kuch systems
# par libGL error deta hai — isiliye aakhir mein ye do command zaroor:
.venv/bin/pip uninstall -y opencv-python
.venv/bin/pip install --force-reinstall opencv-python-headless
```
Windows par `.venv/bin/pip` ki jagah `.venv\Scripts\pip` use karo.

### Step 3 — Node + Prisma install
```bash
npm install
```
Ye `@prisma/client`, `prisma`, `express` sab install karega aur
Prisma Client generate karega.

### Step 4 — Database (optional)
```bash
npm run db:setup
```
Isse `data/pdf_qa.db` ban jayega aur models ke tables
(`documents`, `pages`, `chunks` + FTS5 index) ready ho jayenge.
*(Ye step bhool bhi jao to koi baat nahi — server khud pehle boot par
tables bana deta hai. Standard Prisma wala tareeka: `npx prisma db push`.)*

Database dekhna ho to Prisma Studio:
```bash
npm run db:studio
```

### Step 5 (A) — Ollama local lagao (sabse best — sirf tumhare PC ke liye)

Tumhara laptop: **16 GB RAM + 6 GB graphics card** — iske liye
perfect model hai **`qwen2.5:7b`** (~4.7 GB download):

1. https://ollama.com se Ollama install karo (Windows app tray mein chalti rehti hai)
2. Terminal mein model download karo:
   ```bash
   ollama pull qwen2.5:7b
   ```
3. Bas — server start karne par Ollama **apne aap chain mein pehle
   number par** use hoga. Koi key nahi, koi internet nahi, koi paisa nahi.

Kyun yahi model tumhare (16 GB RAM) laptop ke liye best hai:
- Model ~4.7 GB ka hai — bada hissa 6 GB VRAM (graphics card) mein
  rahega, isliye 16 GB RAM par bhi aaram se chalega aur jawab fast
  aayega (lagbhag 4–10 sec)
- Hindi/Hinglish Qwen par sabse achhi hai (tumhari PDFs mixed hain)
- Code mein context `num_ctx 8192` set hai, taaki lambe PDF passages
  naa katein
- ⚠️ `qwen2.5:14b` 16 GB RAM par mat lagana — 9 GB ka model RAM
  bhar dega, laptop slow/hang ho sakta hai. 7B hi sahi rahega.
- Agar phir bhi slow lage (jaise saath mein Chrome ke bahut tabs
  khule hon), to `.env` mein `OLLAMA_MODEL=qwen2.5:3b` kar do —
  halka model hai, jawab thode simple lekin tez aayenge. Model
  chalate waqt bhaari apps band rakhna to speed best rahegi.

### Step 5 (B) — Free AI keys lagao (optional, backup ke liye)
`.env.example` ko `.env` naam se copy karo aur teeno keys bharo
(teeno lagane ki salah hai — fallback chain tabhi kaam karegi):

| API | Free key kahan se milegi | .env mein |
|---|---|---|
| **GLM (z.ai)** | https://z.ai/manage-apikey/apikey-list — free model `glm-4.7-flash` | `GLM_API_KEY=` |
| **NVIDIA NIM** | https://build.nvidia.com → *Get API Key* (`nvapi-...`) | `NVIDIA_API_KEY=` |
| **Google Gemini** | https://aistudio.google.com/apikey | `GEMINI_API_KEY=` |

Keys bhar kar server start karne par website ke left panel mein
teeno ka status ✅ dikhega, aur **"🔑 API Keys Test Karo"** button se
har key ko live test bhi kar sakte ho.

**Fallback aise kaam karta hai:** sawaal par pehle PDF se relevant
pages nikalte hain, phir **Ollama (local) → GLM → NVIDIA → Gemini**
order mein AI ko bhejte hain. Ollama band ho to wo chup-chaap skip
ho jata hai aur cloud wali chain chalti hai. Koi API fail hui (galat key, rate-limit 429, timeout,
server down) to agli apne aap try hoti hai — jawab ke neeche dikhega
bhi ki *"Pehele fail hui: GLM — isliye agli API use hui"*. Teeno fail
ho jayein to purana database-search jawab mil jata hai.
Order badalna ho to `.env` mein `AI_PROVIDER_ORDER=gemini,glm,nvidia`
jaisa set karo; AI pura band karna ho to `AI_MODE=off`.

### Step 6 — Server chalao
```bash
npm start
```
Browser mein kholo: **http://localhost:8000**

Phir: **① PDF upload karo → ② "Database mein save ho gaya" dikhega →
③ sawaal puchho.** Server band karna ho to `Ctrl+C`. Dobara `npm start`
karne par purana data database se apne aap aa jayega — dobara upload
nahi karna padega.

> **Windows note:** agar upload par "Python worker start nahi hua"
> error aaye, to `.env.example` ko `.env` naam se copy karke usmein
> `PYTHON_BIN=python` set karo (Linux/Mac par `python3`).

### Purana Python-only tareeka (optional)
`app.py` (FastAPI) aur `cli.py` abhi bhi repo mein hain aur wahi
database file use karte hain, lekin **main server ab Node + Prisma hai**.

### ☁️ AWS par deploy karna hai?
Poori step-by-step guide dekho: **[AWS_DEPLOY.md](AWS_DEPLOY.md)**
(Docker image ready hai — `Dockerfile` + `docker-compose.yml` +
`/api/health` health check. EC2 par `docker compose up -d --build`
se poora product chal jayega; wahan Ollama skip hokar cloud AI
chain chalti hai.)

---

## 🗄️ Prisma Models (prisma/schema.prisma)

| Model | Kya save hota hai |
|---|---|
| `Document` | PDF ka naam, sha256, size, total pages/chars, OCR stats, kab add hui |
| `Page` | Har page ka extracted text + method (`text` / `ocr:...`) |
| `Chunk` | Search ke liye ~900 char ke hisse, page number ke saath |
| `chunks_fts` | FTS5 virtual table (Prisma model nahi ho sakti — raw SQL se banti hai, search BM25 ranking se hoti hai) |

Saare database operations Prisma Client se hote hain
(`server/store.ts`, `server/prisma.ts`) — `document.upsert`,
`page.createMany`, `chunk.findMany` vagera. Database file:
**`data/pdf_qa.db`**. Ek hi PDF dobara daalo to duplicate nahi
banta — wahi `Document` update ho jata hai.

## ❓ "Konsi bhi PDF par work karega na?"

Haan — jo PDF file khulti hai, uska text nikalne ki har koshish hoti
hai. Ye sab test karke verified hai:

| PDF ki halat | Result |
|---|---|
| Normal digital PDF (Word/Chrome se bani) | ✅ Text layer, reading-order ke saath |
| Multi-column PDF | ✅ Pehle poora left column, phir right column |
| Table wali PDF | ✅ `Product \| 55000 \| 12` format mein — rate/dhoondhna aasaan |
| Scanned PDF (sirf photo, 0 text) | ✅ OCR se text nikla (test: 1,328 chars) aur DB mein save |
| Screenshot/Canva wali PDF (aapki dono guides) | ✅ Text + OCR merge, duplicate saaf karke |
| Kharab/garbled text layer | ✅ Quality fail hone par OCR wala text |
| Form wali PDF | ✅ Form values bhi text mein |
| Har page par same header/footer | ✅ Apne aap hat jata hai (search saaf rehta hai) |

**Sach wali limitations (chhupana galat hoga):**
- 🔒 Password-protected PDF pehle unlock karni padegi (saaf error aata hai).
- ✍️ Handwriting OCR se theek nahi padhegi — printed text best hai.
- 🇮🇳 Hindi printed text ke liye Tesseract (hin) best hai
  (neeche dekho); default RapidOCR English mein strong hai.
- Agar koi AI key na lagi ho (ya teeno fail ho jayein) to jawab
  *"likha hua"* nahi hota — PDF ke relevant hisse page number ke
  saath milte hain. Sawaal mein PDF ke exact shabd rakho:
  `"UPI QR kaise banta hai?"`, `"Laptop price stock"`. AI keys
  lagte hi wahi hisse AI saaf bhasha mein jawab bana deta hai.

## 🔍 OCR engine

Priority: **Tesseract → EasyOCR → RapidOCR** (jo pehle mil jaye).
Hindi ke liye: Ubuntu `sudo apt install tesseract-ocr tesseract-ocr-hin`
· Windows par UB-Mannheim Tesseract installer mein *Hindi (hin)* tick
karo, phir `pip install pytesseract Pillow`. Default RapidOCR sirf
`pip install` se chal jata hai.

## 📁 Files

| File | Kaam |
|---|---|
| `setup.sh` · `setup.bat` | Ek-command setup (venv, libraries, Prisma, DB) |
| `prisma/schema.prisma` | Prisma models (Document/Page/Chunk) |
| `prisma.config.ts` | Prisma + SQLite path config |
| `server/index.ts` | Express API + web UI serve |
| `server/store.ts` | Prisma ORM se saare DB operations |
| `server/search.ts` · `server/answer.ts` | FTS5/BM25 + TF-IDF search, jawab |
| `server/ai.ts` | AI fallback chain (Ollama → GLM → NVIDIA → Gemini) |
| `server/worker.ts` | Python extraction worker ko bulana (timeout ke saath) |
| `worker.py` + `pdf_ocr_qa/` | PDF padhna + OCR (Python/PyMuPDF) |
| `static/index.html` | Browser UI (upload, DB panel, AI panel, chat, export) |
| `scripts/init-db.mjs` | `prisma db push` ke bina tables banane ka pakka tareeka |
| `data/pdf_qa.db` | Tumhara database (auto-banta hai, git mein nahi jata) |

Har PDF card par **⬇ TXT / CSV / JSON export** hai — data proper
aaya ya nahi, khud check kar sakte ho.

## 🔧 Full audit mein kya-kya theek hua (Nov 2026)

- **Fresh DB par server crash hota tha** — tables hi nahi banti thi.
  Ab server boot par khud schema ready kar deta hai.
- **OCR chup-chaap fail ho jata tha** (GUI `opencv-python` ka libGL
  error) — ab setup script headless ko sahi order mein lagata hai,
  aur engine na mile to upload par saaf chetaavni dikhti hai.
- **UI mein filename se script chal sakta tha (XSS)** — ab naam
  hamesha text ki tarah lagta hai; server par bhi naam saaf hota hai.
- Koi bhi API error ab **poora server crash nahi** karta (saaf JSON
  error milta hai); upload/download par path-traversal aur header
  todne wale naam band; badi file (100 MB) aur bada sawaal (2000
  akshar) par limit.
- Ek hi PDF do baar/ek saath upload par unique-constraint crash
  band — sab kuch ek transaction mein save hota hai.
- Python worker par **15 minute timeout** — badi PDF par system
  hamesha ke liye nahi atkta; bachi hui temp files apne aap saaf.
- Jawab mein **milte-julte hisse dobara nahi** aate; bade database
  par jawab ab tez (IDF ek hi baar banta hai).
- UI naya: toast notifications, upload progress + timer, typing
  indicator, example-sawaal chips, jawab copy button, mobile par
  chat pehle, server down ho to banner, delete se pehle confirm.
