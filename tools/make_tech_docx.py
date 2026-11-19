"""Build the presentable Word document: technology, libraries, models and AI.

    python tools/make_tech_docx.py

Output: docs/Prototype_Technology_Stack.docx  (real screenshots embedded)
"""
from __future__ import annotations

import os
import sys

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def P(*a): return os.path.join(ROOT, *a)

SHOTS = P("brag-output", "work", "shots_app")
OUT = P("docs", "Prototype_Technology_Stack.docx")
ARCH = P("brag-output", "work", "architecture.png")

ACCENT = RGBColor(0x2F, 0x5B, 0xD6)
DARK = RGBColor(0x14, 0x20, 0x3C)
GREY = RGBColor(0x55, 0x60, 0x74)


def shade(cell, hexcolor):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hexcolor)
    tcPr.append(shd)


def set_cell(cell, text, bold=False, size=9.5, color=None):
    cell.text = ""
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(text)
    r.bold = bold
    r.font.size = Pt(size)
    if color:
        r.font.color.rgb = color


def table(doc, headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        set_cell(t.rows[0].cells[i], h, bold=True, size=9.5, color=RGBColor(0xFF, 0xFF, 0xFF))
        shade(t.rows[0].cells[i], "2F5BD6")
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            set_cell(cells[i], v)
    if widths:
        for r in t.rows:
            for i, w in enumerate(widths):
                r.cells[i].width = Inches(w)
    doc.add_paragraph()
    return t


def h1(doc, text):
    p = doc.add_heading(text, level=1)
    for r in p.runs:
        r.font.color.rgb = DARK
        r.font.size = Pt(16)
    return p


def h2(doc, text):
    p = doc.add_heading(text, level=2)
    for r in p.runs:
        r.font.color.rgb = ACCENT
        r.font.size = Pt(12.5)
    return p


def para(doc, text, size=10.5, bold=False, italic=False, color=None, space=6):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space)
    r = p.add_run(text)
    r.font.size = Pt(size)
    r.bold = bold
    r.italic = italic
    if color:
        r.font.color.rgb = color
    return p


def bullet(doc, text, size=10.5):
    p = doc.add_paragraph(style="List Bullet")
    r = p.add_run(text)
    r.font.size = Pt(size)
    return p


def shot(doc, filename, caption, width=6.3):
    path = os.path.join(SHOTS, filename)
    if not os.path.exists(path):
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(path, width=Inches(width))
    c = doc.add_paragraph()
    c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = c.add_run(caption)
    r.font.size = Pt(9)
    r.italic = True
    r.font.color.rgb = GREY
    c.paragraph_format.space_after = Pt(10)


def make_architecture_png():
    """A clean architecture figure for the document (boxes + arrows)."""
    from PIL import Image, ImageDraw, ImageFont
    W, H = 1500, 900
    FD = "/usr/share/fonts/truetype/dejavu/"
    f = lambda s, b=False: ImageFont.truetype(FD + ("DejaVuSans-Bold.ttf" if b else "DejaVuSans.ttf"), s)
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((40, 26), "PDF Q&A — ingest path and query path", font=f(30, True), fill=(20, 32, 60))
    box = lambda x, y, w, h, title, sub, col: (
        d.rounded_rectangle((x, y, x + w, y + h), 12, fill=(244, 247, 255), outline=col, width=2),
        d.rectangle((x, y, x + w, y + 8), fill=col),
        d.text((x + 16, y + 18), title, font=f(19, True), fill=(20, 32, 60)),
        d.text((x + 16, y + 48), sub, font=f(14), fill=(85, 96, 116)))
    lw, rw = 660, 620
    lx, rx = 60, 820
    items_l = [("Browser · static UI", "drag & drop upload, live progress, chat"),
               ("Express server · Node 20", "routes, upload, /api/progress, /api/ask"),
               ("Python worker", "PyMuPDF text extraction · RapidOCR on scanned pages"),
               ("Prisma 7 · libSQL driver", "documents → pages → chunks")]
    items_r = [("Question", "English / Hindi, optional document filter"),
               ("BM25 search", "FTS5 index over every chunk"),
               ("AI chain", "Ollama → GLM → NVIDIA → OpenRouter → Gemini"),
               ("Answer + page", "cited passage, file name, match score")]
    bh, gap = 120, 34
    for col, x, items in ((0, lx, items_l), (1, rx, items_r)):
        y = 100
        for i, (t, s) in enumerate(items):
            box(x, y, lw if col == 0 else rw, bh, t, s, (47, 91, 214) if col == 0 else (126, 91, 214))
            if i < 3:
                d.line((x + 60, y + bh, x + 60, y + bh + gap), fill=(47, 91, 214), width=3)
                d.polygon([(x + 60, y + bh + gap), (x + 54, y + bh + gap - 9), (x + 66, y + bh + gap - 9)])
            y += bh + gap
    d.line((lx + lw - 30, 100 + 3 * (bh + gap) + bh / 2, rx + 40, 100 + 2 * (bh + gap) + bh / 2), fill=(47, 91, 214), width=4)
    d.polygon([(rx + 40, 100 + 2 * (bh + gap) + bh / 2), (rx + 31, 100 + 2 * (bh + gap) + bh / 2 - 6), (rx + 31, 100 + 2 * (bh + gap) + bh / 2 + 6)])
    d.text((lx, 800), "ingest", font=f(16, True), fill=(47, 91, 214))
    d.text((rx, 800), "query", font=f(16, True), fill=(126, 91, 214))
    d.text((60, 850), "Everything runs on the user's machine: the PDF, the SQLite file and the OCR models.", font=f(14), fill=(85, 96, 116))
    img.save(ARCH, quality=92)
    return ARCH


def main():
    if not os.path.exists(ARCH):
        make_architecture_png()

    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(10.5)
    for s in doc.sections:
        s.top_margin = Inches(0.8)
        s.bottom_margin = Inches(0.8)
        s.left_margin = Inches(0.9)
        s.right_margin = Inches(0.9)

    # ---------------- cover
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(90)
    r = p.add_run("PDF Q&A")
    r.font.size = Pt(40)
    r.bold = True
    r.font.color.rgb = DARK
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Prototype Demo & Technology Stack")
    r.font.size = Pt(20)
    r.font.color.rgb = ACCENT
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Technology · Libraries · Models · AI")
    r.font.size = Pt(12)
    r.font.color.rgb = GREY
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(40)
    r = p.add_run("Prepared 19 November 2026 · PDF OCR + Prisma Q&A project")
    r.font.size = Pt(10)
    r.italic = True
    r.font.color.rgb = GREY
    doc.add_page_break()

    # ---------------- 1 overview
    h1(doc, "1. What this project is")
    para(doc, "Drop in any PDF and its data is extracted and saved into a SQLite database through Prisma ORM. "
              "Questions are answered first by the AI fallback chain (Ollama local → GLM → NVIDIA → OpenRouter → Gemini); "
              "if no AI works, you still get the database-search answer — the app never stops. The whole system works even without any key.")
    para(doc, "It is built for scanned documents: a 1,000-page image-only manual gets OCR on every page, and every page becomes "
              "searchable with its page number attached. The interface is a single dark, responsive web page.")
    h2(doc, "The problem it solves")
    bullet(doc, "Scanned PDFs are pictures, not text — Ctrl+F finds nothing.")
    bullet(doc, "In the real test, two Hitachi Zosen engine instruction manuals totalled 1,623 scanned pages with zero searchable characters.")
    bullet(doc, "After OCR the same material produced over 15 lakh (1.5 million) searchable characters in SQLite.")
    bullet(doc, "Answers carry their source — file name, page number and match score — so a human can verify them.")

    # ---------------- 2 live demo
    h1(doc, "2. The prototype, running")
    para(doc, "Every screenshot below was captured from the live application during this build (headless Chromium via "
              "microsoft/playwright-mcp). The database holds two real documents: a 7-page Claude × WhatsApp agent guide "
              "(image-heavy, so all 7 pages went through OCR) and an 8-page GTM Command Center setup guide.")
    shot(doc, "20_home_hidpi.png", "The whole application on one screen: upload, database panel, AI chain, document list and chat.")
    shot(doc, "26_ocr_progress_full.png", "Live OCR progress on a 48-page image-only PDF — page number, percentage and time remaining.")
    shot(doc, "40_answer_full.png", "A real question and its answer, with the cited page at the end of the reply.")
    shot(doc, "41_sources_full.png", "Sources opened: the exact passage, the file name, the page number and the match score.")
    shot(doc, "42_view_data.png", "Viewing the extracted text of any page, with TXT / CSV / JSON export.")
    shot(doc, "43_delete_confirm.png", "Delete always asks for confirmation first.")
    shot(doc, "44_mobile.png", "The same application at a 390-pixel phone width.", width=3.2)

    # ---------------- video chapters
    chap_path = P("brag-output", "work", "chapters.json")
    if os.path.exists(chap_path):
        import json
        ch = json.load(open(chap_path, encoding="utf-8"))
        h1(doc, "3. Video chapters")
        para(doc, "The film is 1920x1080 at 30 fps with a selectable English subtitle track and a "
                  "second Hinglish subtitle track.", size=10)
        def mmss(x):
            return f"{int(x // 60)}:{int(x % 60):02d}"
        rows = [[mmss(c["t"]), c["title"]] for c in ch["chapters"]]
        rows.append(["", f"end - {mmss(ch['total'])}"])
        table(doc, ["Time", "Chapter"], rows, widths=[1.0, 5.2])

    # ---------------- 3 architecture
    h1(doc, "4. Architecture")
    para(doc, "A Node/Express server owns the API and the database. Heavy document work is delegated to a Python worker "
              "process, which writes a JSON result back. Questions run a database search first and only then the AI chain.")
    doc.add_picture(ARCH, width=Inches(6.4))
    c = doc.add_paragraph(); c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = c.add_run("Ingest path (left) and query path (right)."); r.font.size = Pt(9); r.italic = True; r.font.color.rgb = GREY
    h2(doc, "Ingest path")
    bullet(doc, "Browser → Express: multipart upload (Multer), up to 20 files, 1 GB each.")
    bullet(doc, "server/worker.ts spawns worker.py and streams per-page progress to /api/progress.")
    bullet(doc, "pdf_ocr_qa/extract.py: PyMuPDF extracts text; pages with little or no text are sent to OCR.")
    bullet(doc, "pdf_ocr_qa/ocr.py: RapidOCR on ONNX Runtime (Tesseract or EasyOCR optional).")
    bullet(doc, "server/store.ts: Prisma transaction writes Document, Page and Chunk rows.")
    h2(doc, "Query path")
    bullet(doc, "server/search.ts: FTS5 full-text index with BM25 ranking, plus a TF-IDF scorer.")
    bullet(doc, "server/answer.ts: builds the answer from the top passages, always with (file, page) citations.")
    bullet(doc, "server/ai.ts: the five-provider fallback chain; on total failure the database answer is returned.")

    # ---------------- 4 tech & libraries
    h1(doc, "5. Technology and libraries")
    table(doc,
          ["Layer", "Technology", "Version / detail"],
          [["Server", "Node.js + Express", "Node 20.19+ · Express 4 · TypeScript via tsx"],
           ["Uploads", "Multer", "up to 20 files per request · 1 GB per file"],
           ["ORM", "Prisma", "7.10.1 · prisma-client generator · libSQL driver"],
           ["Database", "SQLite", "documents, pages, chunks · FTS5 virtual table"],
           ["Search", "FTS5 + BM25 + TF-IDF", "server/search.ts"],
           ["PDF text", "PyMuPDF (fitz)", ">= 1.24"],
           ["OCR", "RapidOCR-onnxruntime", "1.4.x · ONNX Runtime · headless OpenCV"],
           ["OCR alternatives", "Tesseract / EasyOCR", "optional; Tesseract with Hindi best for Devanagari"],
           ["Python API (standalone)", "FastAPI + Uvicorn", "pdf_ocr_qa/serve.py"],
           ["Container", "Docker + Compose", "node:22-bookworm · healthcheck on /api/health"],
           ["Cloud", "AWS EC2 + GitHub Actions", "Ubuntu 24.04 · Docker Compose · auto-deploy workflow"],
           ["Frontend", "Static HTML/CSS/JS", "responsive dark UI · no framework"]],
          widths=[1.5, 2.1, 3.2])

    # ---------------- 5 AI models
    h1(doc, "6. AI models and the fallback chain")
    para(doc, "Keys are optional and come only from .env. Ollama needs no key and no internet. Each provider is tried in "
              "order; a failure (down, bad key, rate limit, timeout) falls through to the next one.")
    table(doc,
          ["#", "Provider", "Model", "Key", "Free note"],
          [["1", "Ollama (local PC)", "qwen2.5:7b", "none", "Completely free, offline"],
           ["2", "GLM (z.ai)", "glm-4.7-flash", "GLM_API_KEY", "Free model"],
           ["3", "NVIDIA NIM", "nvidia/nemotron-3.5-lightning-30b-a3b", "NVIDIA_API_KEY", "Free tier (nvapi-…)"],
           ["4", "OpenRouter", "nvidia/nemotron-3.5-lightning:free", "OPENROUTER_API_KEY", "':free' models"],
           ["5", "Google Gemini", "gemini-flash-lite-latest", "GEMINI_API_KEY", "Free tier"]],
          widths=[0.4, 1.5, 2.9, 1.3, 1.6])
    para(doc, "Fallback: if every provider fails, the extractive database answer is returned with its citations, so the "
              "app always answers. AI_MODE=off disables the chain entirely.", italic=True, size=10)

    # ---------------- 6 data model
    h1(doc, "7. Data model (Prisma)")
    table(doc,
          ["Model", "Fields", "Notes"],
          [["Document", "id, name, sha256, file_size, page_count, total_chars, ocr_engine, ocr_pages, tables_found, metadata, stored_file, created_at",
            "id = first 12 chars of sha256; sha256 is unique, so re-uploads are ignored"],
           ["Page", "id, docId, pageNo, method, text, char_count", "method = text | ocr:<engine> | text+ocr:<engine>"],
           ["Chunk", "id, docId, pageNo, method, text", "search pieces for FTS5 / BM25"],
           ["chunks_fts", "text, doc_id, page_no, chunk_id", "FTS5 virtual table, created with raw SQL on boot"]],
          widths=[1.1, 3.9, 2.4])

    # ---------------- 8 video pipeline
    h1(doc, "8. How the video was made")
    table(doc,
          ["Stage", "Tool", "Detail"],
          [["Capture", "Playwright MCP + headless Chromium", "1440×900 CSS at 2× device scale, live app"],
           ["Narration", "Neural female voice (English)", "one clip per scene, natural pacing"],
           ["Music", "Ende.app — Happy Beats / Business Moves Vol. 1", "CC BY 4.0 · looped with a crossfade"],
           ["Sound effects", "Kenney (via brag)", "soft impacts on scene cuts"],
           ["Mix", "FFmpeg + NumPy", "voice-over ducked against the music bed, loudness-normalised"],
           ["Captions", "punctuation-aware chunks", "burned in, plus English and Hinglish SRT tracks"],
           ["Render", "FFmpeg + libx264", "1920×1080 · 30 fps · CRF 19 · faststart"]],
          widths=[1.3, 2.4, 3.5])

    # ---------------- 9 run
    h1(doc, "9. Running it")
    para(doc, "One-time setup, then one command to run:")
    for c in ["bash setup.sh          # Windows: setup.bat",
              "npm start              # http://localhost:8000",
              "docker compose up -d --build   # the AWS EC2 path"]:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Inches(0.3)
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(c)
        r.font.name = "Consolas"
        r.font.size = Pt(10)
    para(doc, "Guides in the repository: HOW_TO_RUN.md, AWS_DEPLOY.md and the Word guides in docs/ (English and Hinglish).", space=10)

    # ---------------- 10 test results
    h1(doc, "10. Verified in this build")
    table(doc,
          ["Check", "Result"],
          [["Two real PDFs uploaded", "7 + 8 pages, 15 pages saved, 25 search chunks"],
           ["OCR on an image-heavy PDF", "7 of 7 pages read by RapidOCR"],
           ["Live OCR on a 48-page image-only PDF", "48 pages · 46,212 characters extracted"],
           ["Question answered", "'What are the 5 steps to set up the GTM Command Center?' → cited answer from page 3"],
           ["AI chain test", "Ollama not running, no cloud keys → clean fallthrough, database answer returned"],
           ["Delete flow", "confirmation dialog shown, 'No, keep it' keeps the document"],
           ["Mobile layout", "390 × 844 render, no horizontal overflow"]],
          widths=[2.6, 4.6])

    doc.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    sys.exit(main())
