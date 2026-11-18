# 📄 PDF OCR + Database Q&A — bina AI ke (100% Offline)

**Tum jo bhi PDF daalo, uska data proper nikal kar SQLite database mein
save hota hai, aur sawaal ka jawab database search se milta hai.
Koi AI nahi, koi API key nahi, koi internet nahi.**

```
PDF upload ─► Text layer (reading-order) ─► Table extraction ─► Cleaning
                    │                                              │
                    └─► Scanned / screenshot / kharab page par OCR ┘
                                   ▼
              SQLite Database (data/pdf_qa.db)
              documents · pages · chunks · FTS5 search index
                                   ▼
         Sawaal ─► Database search (BM25) ─► Jawab + (file, page) source
```

## Chalana

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
# Browser: http://localhost:8000
```

Command line se:

```bash
python cli.py add "koi-bhi.pdf"              # process + DB mein save
python cli.py list                           # DB mein saved PDFs
python cli.py status                         # database ki details
python cli.py ask "UPI QR kaise banta hai?"  # database se jawab
python cli.py export <doc_id> --format csv   # data bahar nikalo (txt/csv/json)
```

## Database mein kya-kya save hota hai

File: **`data/pdf_qa.db`** (SQLite — app band karke kholne par data
wahi rahega, dobara process nahi karna padega)

| Table | Kya save hota hai |
|---|---|
| `documents` | PDF ka naam, hash, size, pages, kab add hui, OCR/tables stats |
| `pages` | Har page ka saaf kiya hua text + method (`text` / `ocr:...`) |
| `chunks` | Search ke liye ~900 char ke hisse (page number ke saath) |
| `chunks_fts` | SQLite FTS5 full-text index — BM25 ranking se tez search |

Original PDF ki copy `data/uploads/` mein bhi rehti hai. Ek hi PDF
dobara daalo to duplicate nahi banta — wahi record update ho jata hai.

## Koi bhi PDF — proper data kaise niklta hai

| PDF ki halat | Kya hota hai |
|---|---|
| Normal digital PDF | Text layer reading-order mein (multi-column par pehle left column, phir right column) |
| Table wali PDF | Tables `cell \| cell \| cell` lines mein — search me rate/price aaram se milta hai |
| Scanned PDF (sirf photo) | Page render karke OCR (300 DPI), OCR garbage lines filter hoti hain |
| Screenshot wali PDF (jaise Canva guides) | Bade image wale page par OCR + text merge, duplicate lines saaf |
| Kharab/garbled text layer | Quality check fail hone par OCR wala text use hota hai |
| Har page par same header/footer | 60%+ pages par dohraayi line apne aap hat jati hai |
| Form wali PDF | Form fields ke values bhi text mein aa jate hain |
| Password wali PDF | Saaf error: pehle password hatao |

## Sawaal-jawab bina AI ke (sach baat)

- Jawab **database search (FTS5/BM25 + TF-IDF fallback)** se banta hai —
  ye classic database search hai, AI/LLM/embedding nahi hai.
- Bina AI ke system jawab *"likhta"* nahi hai; ye PDF ke woh hisse
  deta hai jahan tumhare sawaal ke shabd mile, **page number ke saath**.
- Isliye sawaal mein PDF ke exact shabd use karo — jaise
  `"UPI QR kaise banta hai?"`, `"Step 3 Calendar"`, `"Laptop price"`.
  Dusri bhasha/paryaye shabd (jaise PDF mein "price" hai aur tum
  "keemat" puchho) bina AI ke nahi judega.

## OCR engine

Priority: **Tesseract → EasyOCR → RapidOCR** (jo mil jaye).
Hindi ke liye Tesseract best hai: Ubuntu `sudo apt install tesseract-ocr
tesseract-ocr-hin` · Windows installer mein Hindi tick karo, phir
`pip install pytesseract Pillow`. Sirf pip se `rapidocr-onnxruntime`
(default) — English strong, printed Hindi kamzor ho sakta hai.

## Files

| File | Kaam |
|---|---|
| `app.py` + `static/index.html` | Web app — upload, database panel, chat, export (TXT/CSV/JSON) |
| `cli.py` | Terminal version — add / list / status / ask / text / export / remove |
| `pdf_ocr_qa/extract.py` | PDF → saaf text (layout + tables + OCR merge + cleaning) |
| `pdf_ocr_qa/ocr.py` | OCR engine auto-detect |
| `pdf_ocr_qa/store.py` | **SQLite database** + FTS5/TF-IDF search |
| `pdf_ocr_qa/answer.py` | Database search se jawab (bina AI) |
| `data/pdf_qa.db` | Tumhara database (auto-banta hai) |

> Purani VoterLens files alag project hain — unhe chheda nahi gaya.
> v1 ki `store.json` ho to pehli baar mein uska data khud DB mein
> migrate ho jata hai.
