# 📄 PDF OCR Q&A — PDF se Sawaal-Jawab System

**Haan, bilkul aisa ban sakta hai — aur ye wahi system hai.** 👇

Tumhe jaisi PDFs milti hain (setup guides, scanned documents, screenshots
wali PDFs), unhe upload karo — system unka text **OCR / text-extraction**
se nikaalega, phir tum jo sawaal puchhoge uska jawab **page number ke
saath** dega.

```
PDF upload ──► Text layer extraction ──► kam text / screenshot page par OCR
                    │                              (Tesseract / EasyOCR / RapidOCR)
                    └──────────────┬───────────────┘
                                   ▼
                        Chunks + TF-IDF search index
                                   ▼
              Sawaal ──► relevant pages dhundho ──► jawab + citations
                                   │
                    AI key ho to LLM se behtar jawab,
                    na ho to offline mode (relevant hisse + page no.)
```

## Chalana kaise hai

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

Browser mein **http://localhost:8000** kholo → PDF upload karo → sawaal puchho.

Bina browser ke (command line):

```bash
python cli.py add "GTM_Command_Center_Setup_Guide (1).pdf" --ocr auto
python cli.py ask "GTM Command Center mein kitne steps hain?"
python cli.py ask "WhatsApp agent banane ke liye kya kya chahiye?"
```

> Note: repo ki purani `VoterLens_v5.x` files alag project hain, ye naya
> system unse alag hai — unhe chheda nahi gaya.

## Ye kaam kaise karta hai

| Step | Kya hota hai |
|---|---|
| **1. Extraction** | Har page se pehle PDF ki embedded text layer nikali jati hai. Canva-style duplicate lines aur `S H U R U` jaise spaced letters saaf kiye jate hain. |
| **2. OCR (auto)** | Jis page par text bahut kam hai (scanned) **ya** bada screenshot/image hai, us page ko render karke OCR chalaya jata hai — taaki screenshot ke andar ka text (code, steps, table) bhi mil jaye. UI mein *"Har page par OCR"* tick karke force bhi kar sakte ho. |
| **3. Indexing** | Text ~900 character ke chunks mein katkar TF-IDF index banta hai (`data/store.json` mein save). Bina internet/model-download ke chalta hai, Hindi + English dono tokenize hote hain. |
| **4. Q&A** | Sawaal se sabse relevant chunks/pages dhundhe jate hain. AI key ho to LLM unhi passages se jawab likhta hai; na ho to offline extractive jawab — dono mein **(file, page)** citation milta hai. |

## AI jawab chahiye? (optional, lekin behtar jawab ke liye)

Bina key ke app **offline mode** mein chalegi — jawab mein PDF ke sabse
relevant hisse milenge. Sahi, natural-language jawab ke liye `.env.example`
ko `.env` naam se copy karke koi **ek** key bhar do:

- **Claude** — `ANTHROPIC_API_KEY=...`
- **OpenAI / Groq / koi bhi compatible API** — `OPENAI_API_KEY=...`
- **Ollama** (apne PC par bilkul free, local) — `OLLAMA_HOST=http://localhost:11434`

App restart karo, header mein `AI mode: ...` dikh jayega.

## OCR engine kaunsa lagega?

Priority: **Tesseract → EasyOCR → RapidOCR** (jo pehle mil jaye).

- **Hindi/Hinglish PDFs ke liye Tesseract best hai** — Ubuntu:
  `sudo apt install tesseract-ocr tesseract-ocr-hin` · Windows:
  UB-Mannheim Tesseract installer mein *Hindi (hin)* tick karo, phir
  `pip install pytesseract Pillow`
- **Sirf pip se chahiye** to `rapidocr-onnxruntime` (requirements mein
  default hai) — English strong hai, printed Hindi kamzor padh sakta hai.
- Repo ka VoterLens project EasyOCR use karta hai; wo install ho to ye
  system use bhi auto-detect kar lega.

## Files

| File | Kaam |
|---|---|
| `app.py` | Web app (FastAPI) — upload + chat UI |
| `cli.py` | Command-line version |
| `pdf_ocr_qa/extract.py` | PDF → saaf text (text layer + OCR merge) |
| `pdf_ocr_qa/ocr.py` | OCR engine auto-detection |
| `pdf_ocr_qa/store.py` | Chunking + TF-IDF index + storage |
| `pdf_ocr_qa/answer.py` | Jawab engine (LLM ya offline) |
| `static/index.html` | Browser UI |
| `data/` | Processed PDFs ka data (auto-banta hai, git mein nahi jata) |

## Limitations (sach baat)

- Scanned handwriting OCR se achhe se nahi padhegi; printed text best rahega.
- Offline mode "jawab likhta" nahi hai — relevant hisse deta hai. Natural
  jawab ke liye upar wali koi ek AI key/Ollama lagao.
- Table ka structure text mein flatten ho jata hai (rows line-wise bante hain).
