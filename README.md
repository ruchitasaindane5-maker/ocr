# 📄 PDF OCR + Prisma Database Q&A — bina AI ke

**Jo bhi PDF daalo, uska data proper nikal kar Prisma ORM se SQLite
database mein save hota hai, aur sawaal ka jawab database search se
milta hai. Koi AI nahi, koi API key nahi.**

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
     Sawaal ─► database search ─► jawab + (file, page) source
```

---

## ▶️ Chalane ka tareeka (step-by-step)

### Pehle ye dono install hone chahiye
- **Node.js 18+** — https://nodejs.org
- **Python 3.10+** — https://python.org (Windows par install ke time
  *"Add Python to PATH"* tick karna)

### Step 1 — Project folder mein aao
```bash
cd ocr_pdf
```

### Step 2 — Python (PDF/OCR) ki libraries
```bash
pip install -r requirements.txt
```
Windows par kabhi `pip` ki jagah `py -m pip install -r requirements.txt`.

### Step 3 — Node + Prisma install
```bash
npm install
```
Ye `@prisma/client`, `prisma`, `express` sab install karega aur
Prisma Client generate karega.

### Step 4 — Database banao (ek hi baar)
```bash
npm run db:setup
```
Isse `data/pdf_qa.db` ban jayega aur models ke tables
(`documents`, `pages`, `chunks` + FTS5 index) ready ho jayenge.
*(Standard Prisma wala tareeka chahiye to: `npx prisma db push` —
dono ka result same hai.)*

Database dekhna ho to Prisma Studio:
```bash
npm run db:studio
```

### Step 5 — Server chalao
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
- Bina AI ke jawab *"likha hua"* nahi hota — PDF ke relevant hisse
  page number ke saath milte hain. Sawaal mein PDF ke exact shabd
  rakho: `"UPI QR kaise banta hai?"`, `"Laptop price stock"`.

## 🔍 OCR engine

Priority: **Tesseract → EasyOCR → RapidOCR** (jo pehle mil jaye).
Hindi ke liye: Ubuntu `sudo apt install tesseract-ocr tesseract-ocr-hin`
· Windows par UB-Mannheim Tesseract installer mein *Hindi (hin)* tick
karo, phir `pip install pytesseract Pillow`. Default RapidOCR sirf
`pip install` se chal jata hai.

## 📁 Files

| File | Kaam |
|---|---|
| `prisma/schema.prisma` | Prisma models (Document/Page/Chunk) |
| `prisma.config.ts` | Prisma + SQLite path config |
| `server/index.ts` | Express API + web UI serve |
| `server/store.ts` | Prisma ORM se saare DB operations |
| `server/search.ts` · `server/answer.ts` | FTS5/BM25 + TF-IDF search, jawab |
| `server/worker.ts` | Python extraction worker ko bulana |
| `worker.py` + `pdf_ocr_qa/` | PDF padhna + OCR (Python/PyMuPDF) |
| `static/index.html` | Browser UI (upload, DB panel, chat, export) |
| `scripts/init-db.mjs` | `prisma db push` ke bina tables banane ka pakka tareeka |
| `data/pdf_qa.db` | Tumhara database (auto-banta hai, git mein nahi jata) |

Har PDF card par **⬇ TXT / CSV / JSON export** hai — data proper
aaya ya nahi, khud check kar sakte ho.
