"""PDF -> saaf text (page by page).

Strategy (hybrid):
  1. Pehle PDF ki apni embedded text layer nikalo (fast, accurate).
     Design-tool wali PDFs (Canva etc.) mein text aksar duplicate aur
     "S H U R U" jaise spaced letters mein hota hai -> cleaning lagti hai.
  2. OCR tab chalao jab:
       - ocr_mode == "always"  -> har page par, ya
       - ocr_mode == "auto"    -> page par text bahut kam hai (scanned page)
                                  YA page par bade screenshots/images hain
                                  (unke andar ka text text-layer mein nahi hota).
     OCR text ko embedded text ke saath line-level dedupe karke merge
     karte hain taaki duplicate content search ko kharab na kare.
"""
from __future__ import annotations

import re

import pymupdf

from . import ocr as ocr_mod

MIN_TEXT_CHARS = 80  # isse kam text wale page ko "scanned" maano
BIG_IMAGE_AREA_RATIO = 0.25  # page ka 25%+ hissa image = screenshot probable
OCR_ZOOM = 2.2  # ~160 DPI render OCR ke liye kaafi hai aur fast bhi


def _fix_spaced_letters(line: str) -> str:
    """'S H U R U  K A R N E' -> 'SHURU KARNE' (single letters join karo)."""
    tokens = line.split()
    if len(tokens) < 4:
        return line
    single = sum(1 for t in tokens if len(t) == 1 and t.isalpha())
    if single / len(tokens) < 0.6:
        return line
    out, buf = [], ""
    for t in tokens:
        if len(t) == 1 and t.isalpha():
            buf += t
        else:
            if buf:
                out.append(buf)
                buf = ""
            out.append(t)
    if buf:
        out.append(buf)
    return " ".join(out)


def clean_text(raw: str) -> str:
    lines, seen_consecutive = [], None
    for line in raw.splitlines():
        line = _fix_spaced_letters(re.sub(r"[ \t]+", " ", line).strip())
        if not line:
            continue
        # Canva-style PDFs har heading do baar embed karte hain
        if line == seen_consecutive:
            continue
        seen_consecutive = line
        lines.append(line)
    return "\n".join(lines)


def _norm_key(line: str) -> str:
    return re.sub(r"[^0-9a-z\u0900-\u097F]+", "", line.lower())


def merge_texts(base: str, extra: str) -> str:
    """extra ki sirf wahi lines add karo jo base mein pehle se nahi hain."""
    seen = {_norm_key(line) for line in base.splitlines() if _norm_key(line)}
    merged = base.splitlines()
    for line in extra.splitlines():
        key = _norm_key(line)
        if len(key) < 3 or key in seen:
            continue
        if any(key in s or s in key for s in list(seen)[:2000] if len(s) > 12):
            continue
        seen.add(key)
        merged.append(line)
    return "\n".join(merged)


def _image_area_ratio(page) -> float:
    try:
        page_area = page.rect.width * page.rect.height
        if page_area <= 0:
            return 0.0
        area = 0.0
        for img in page.get_images(full=True):
            for r in page.get_image_rects(img[0]):
                area += r.width * r.height
        return min(area / page_area, 1.0)
    except Exception:
        return 0.0


def extract_pdf(path: str, ocr_mode: str = "auto") -> dict:
    """ocr_mode: 'auto' | 'always' | 'never'. Page-wise text + stats deta hai."""
    if ocr_mode not in ("auto", "always", "never"):
        ocr_mode = "auto"
    engine = ocr_mod.detect_engine() if ocr_mode != "never" else None
    doc = pymupdf.open(path)
    pages = []
    for page_no, page in enumerate(doc, start=1):
        embedded = clean_text(page.get_text("text"))
        method, text = "text", embedded
        want_ocr = False
        if engine and ocr_mode == "always":
            want_ocr = True
        elif engine and ocr_mode == "auto":
            want_ocr = len(embedded) < MIN_TEXT_CHARS or _image_area_ratio(page) > BIG_IMAGE_AREA_RATIO
        if want_ocr:
            pix = page.get_pixmap(matrix=pymupdf.Matrix(OCR_ZOOM, OCR_ZOOM))
            ocr_text = clean_text(ocr_mod.ocr_image(pix.tobytes("png")))
            if ocr_text:
                if len(embedded) < MIN_TEXT_CHARS:
                    text, method = ocr_text, f"ocr:{engine}"
                else:
                    text, method = merge_texts(embedded, ocr_text), f"text+ocr:{engine}"
        pages.append({"page": page_no, "text": text, "method": method})
    doc.close()
    return {
        "pages": pages,
        "page_count": len(pages),
        "total_chars": sum(len(p["text"]) for p in pages),
        "ocr_engine": engine,
        "ocr_pages": sum(1 for p in pages if "ocr" in p["method"]),
    }
