"""PDF -> saaf, proper text (page by page) - kisi bhi tarah ki PDF ke liye.

Har PDF alag hoti hai, isliye extraction kai layer mein hoti hai:
  1. Embedded text layer, block-based reading-order ke saath
     (multi-column par pehle left column, phir right).
  2. Tables alag se structured lines mein (cell | cell | cell), taaki
     table ka data flatten hokar bhi khoye nahi.
  3. Form fields (AcroForm) ke values bhi text mein jodte hain.
  4. Cleaning: duplicate lines, "S H U R U" spaced letters, hyphen se
     tute shabd, aur har page par dohraaye jaane wale header/footer
     (60%+ pages par same line) hata diye jate hain.
  5. OCR (auto): scanned page (text < 80 chars), bade screenshot wale
     page, ya kharab/garbage text-layer par page render karke OCR.
     OCR text embedded ke saath dedupe karke merge hota hai.
"""
from __future__ import annotations

import re
from collections import Counter

import pymupdf

from . import ocr as ocr_mod

MIN_TEXT_CHARS = 80          # isse kam = scanned page maano
BIG_IMAGE_AREA_RATIO = 0.25  # page ka 25%+ image = screenshot probable
OCR_ZOOM_SCANNED = 3.0       # scanned page ke liye ~216 DPI
OCR_ZOOM_MERGE = 2.2


def _fix_spaced_letters(line: str) -> str:
    """'S H U R U  K A R N E' -> 'SHURU KARNE'."""
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


def _halve_doubled_tokens(line: str) -> str:
    """'WHATSAPPWHATSAPP AGENTAGENT' -> 'WHATSAPP AGENT' (duplicate layer
    chipak jaane se bane dohre shabd)."""
    out = []
    for tok in line.split(" "):
        if len(tok) >= 8 and len(tok) % 2 == 0 and tok[: len(tok) // 2] == tok[len(tok) // 2:]:
            tok = tok[: len(tok) // 2]
        out.append(tok)
    return " ".join(out)


def _keep_ocr_line(line: str) -> bool:
    """OCR ki garbage lines (ulta/kaata text, symbol junk) roko."""
    s = line.strip()
    if len(s) < 3:
        return False
    if sum(1 for ch in s if ch.isalnum()) < 2:
        return False
    return _text_quality(s) >= 0.5


def clean_text(raw: str) -> str:
    raw = re.sub(r"([A-Za-z])-\n([a-z])", r"\1\2", raw or "")  # hyphen-tute shabd jodo
    lines, prev, seen_long = [], None, set()
    for line in raw.splitlines():
        line = _halve_doubled_tokens(
            _fix_spaced_letters(re.sub(r"[ \t]+", " ", line).strip()))
        if not line or line == prev:
            continue
        # poore page mein dohraayi lambi line (duplicate text-layer) ek hi baar
        if len(line) > 50:
            key = line.lower()
            if key in seen_long:
                continue
            seen_long.add(key)
        prev = line
        lines.append(line)
    return "\n".join(lines)


def _norm_key(line: str) -> str:
    return re.sub(r"[^0-9a-z\u0900-\u097F]+", "", line.lower())


def merge_texts(base: str, extra: str) -> str:
    """extra ki sirf nayi lines add karo (duplicate OCR/text na aaye)."""
    seen = {_norm_key(ln) for ln in base.splitlines() if _norm_key(ln)}
    merged = base.splitlines()
    for line in extra.splitlines():
        key = _norm_key(line)
        if len(key) < 3 or key in seen:
            continue
        if any((key in s or s in key) for s in list(seen)[:2000] if len(s) > 12):
            continue
        seen.add(key)
        merged.append(line)
    return "\n".join(merged)


def _text_quality(text: str) -> float:
    """0..1 - kitna saaf text hai (garbage layer pehchanne ke liye)."""
    if not text:
        return 0.0
    ok = sum(1 for ch in text if ch.isalnum() or ch.isspace() or ch in ".,;:!?()[]|/-–—'\"₹%")
    return ok / max(len(text), 1)


def _image_area_ratio(page) -> float:
    try:
        page_area = page.rect.width * page.rect.height
        if page_area <= 0:
            return 0.0
        area = sum(r.width * r.height
                   for img in page.get_images(full=True)
                   for r in page.get_image_rects(img[0]))
        return min(area / page_area, 1.0)
    except Exception:
        return 0.0


def _layout_text(page) -> str:
    """Block-based reading order. Multi-column page par pehle poora left
    column, phir right column - warna same height ki lines mix ho jati
    hain. Full-width header/footer alag se pehle aata hai."""
    try:
        blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
    except Exception:
        return page.get_text("text", sort=True)
    if len(blocks) < 3:
        # kam blocks ho to block ko poora rakho (line-mixing nahi hoga):
        # pehle upar-wala, phir left-wala block pura
        blocks.sort(key=lambda b: (round(b[1] / 4), b[0]))
        return "\n".join(b[4].strip() for b in blocks)
    width = page.rect.width
    best = None  # (crossing, imbalance, split)
    for b in blocks:
        for split in (b[0], b[2]):
            if not (0.2 * width < split < 0.8 * width):
                continue
            left = [x for x in blocks if x[2] <= split + 2]
            right = [x for x in blocks if x[0] >= split - 2]
            crossing = len(blocks) - len(left) - len(right) + \
                sum(1 for x in blocks if x[0] < split - 2 and x[2] > split + 2)
            wide = sum(1 for x in blocks if (x[2] - x[0]) > 0.6 * width)
            crossing = len([x for x in blocks
                            if x[0] < split - 2 and x[2] > split + 2]) - wide
            if len(left) >= 1 and len(right) >= 1:
                score = (max(crossing, 0), abs(len(left) - len(right)))
                if best is None or score < best[0]:
                    best = (score, split)
    if best is None or best[0][0] > max(1, len(blocks) // 5):
        blocks.sort(key=lambda b: (round(b[1] / 4), b[0]))
        return "\n".join(b[4].strip() for b in blocks)
    split = best[1]
    wide = [b for b in blocks if (b[2] - b[0]) > 0.6 * width]
    left = sorted([b for b in blocks if b[2] <= split + 2 and b not in wide],
                  key=lambda b: (b[1], b[0]))
    right = sorted([b for b in blocks if b[0] >= split - 2 and b not in wide],
                   key=lambda b: (b[1], b[0]))
    rest = [b for b in blocks if b not in wide + left + right]
    # Full-width block apni asal jagah par rakho: column shuru hone se
    # upar wala header pehle, baaki (footer) sabse aakhir mein. Pehle saare
    # wide blocks upar aa jate the — footer bhi page ke top par dikhta tha.
    col_top = min([b[1] for b in left + right], default=0)
    header = sorted([b for b in wide if b[1] <= col_top + 2], key=lambda b: b[1])
    footer = sorted([b for b in wide if b[1] > col_top + 2], key=lambda b: b[1])
    ordered = header + left + right + sorted(rest, key=lambda b: b[1]) + footer
    return "\n".join(b[4].strip() for b in ordered)


def _tables_text(page) -> tuple[str, int]:
    """Page ki tables ko 'cell | cell' lines mein badlo."""
    try:
        tables = page.find_tables().tables
    except Exception:
        return "", 0
    lines, count = [], 0
    for t in tables:
        try:
            rows = t.extract()
        except Exception:
            continue
        if not rows:
            continue
        count += 1
        for row in rows:
            cells = [re.sub(r"\s+", " ", c).strip() for c in row if c and c.strip()]
            if len(cells) >= 2:
                lines.append(" | ".join(cells))
    return "\n".join(lines), count


def _form_text(page) -> str:
    try:
        vals = [f"{w.field_name}: {w.field_value}"
                for w in page.widgets() if w.field_value]
        return "\n".join(vals)
    except Exception:
        return ""


def _strip_boilerplate(pages: list[dict]) -> int:
    """Har page par dohraaya header/footer (page ki pehchan nahi) hatao."""
    if len(pages) < 3:
        return 0
    freq = Counter()
    for p in pages:
        for line in set(p["text"].splitlines()):
            if 0 < len(line) <= 120:
                freq[line] += 1
    boiler = {ln for ln, c in freq.items() if c >= max(2, 0.6 * len(pages))}
    removed = 0
    for p in pages:
        lines = p["text"].splitlines()
        kept = [ln for ln in lines if ln not in boiler]
        removed += len(lines) - len(kept)
        p["text"] = "\n".join(kept)
    return removed


def extract_pdf(path: str, ocr_mode: str = "auto") -> dict:
    """ocr_mode: 'auto' | 'always' | 'never'."""
    if ocr_mode not in ("auto", "always", "never"):
        ocr_mode = "auto"
    engine = ocr_mod.detect_engine() if ocr_mode != "never" else None
    doc = pymupdf.open(path)
    if doc.needs_pass:
        doc.close()
        raise ValueError("Ye PDF password-protected hai - pehle password hatao.")
    metadata = {k: v for k, v in (doc.metadata or {}).items() if v}
    pages, tables_total, warnings = [], 0, []
    for page_no, page in enumerate(doc, start=1):
        embedded = clean_text(_layout_text(page))
        tables_txt, n_tables = _tables_text(page)
        tables_total += n_tables
        if tables_txt:
            embedded = merge_texts(embedded, clean_text(tables_txt))
        form_txt = _form_text(page)
        if form_txt:
            embedded = merge_texts(embedded, clean_text(form_txt))

        method, text = "text", embedded
        garbage = len(embedded) >= MIN_TEXT_CHARS and _text_quality(embedded) < 0.55
        if not engine and ocr_mode != "never" and len(embedded) < MIN_TEXT_CHARS:
            # Scanned page mila par OCR engine hi nahi — wajah chhupao mat,
            # UI/user ko batao taaki wo engine install kare
            warnings.append(
                f"Page {page_no}: scanned hai par OCR engine nahi mila"
                + (f" ({ocr_mod.last_error()})" if ocr_mod.last_error() else "")
                + " — pip install opencv-python-headless rapidocr-onnxruntime --no-deps try karo"
            )
        want_ocr = bool(engine) and (
            ocr_mode == "always"
            or (ocr_mode == "auto" and (
                len(embedded) < MIN_TEXT_CHARS or garbage
                or _image_area_ratio(page) > BIG_IMAGE_AREA_RATIO)))
        if want_ocr:
            scanned = len(embedded) < MIN_TEXT_CHARS
            zoom = OCR_ZOOM_SCANNED if scanned else OCR_ZOOM_MERGE
            # Bahut badi page (poster/A3) par pixmap memory kha jata tha —
            # takreeban 30MP par cap lagao, quality par khaas farak nahi padta
            max_px = 30_000_000
            area = page.rect.width * page.rect.height * zoom * zoom
            if area > max_px:
                zoom *= (max_px / area) ** 0.5
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
            ocr_raw = ocr_mod.ocr_image(pix.tobytes("png"))
            ocr_text = clean_text("\n".join(
                ln for ln in ocr_raw.splitlines() if _keep_ocr_line(ln)))
            if ocr_text:
                if scanned or (garbage and len(ocr_text) > len(embedded)):
                    text, method = ocr_text, f"ocr:{engine}"
                else:
                    text, method = merge_texts(embedded, ocr_text), f"text+ocr:{engine}"
        pages.append({"page": page_no, "text": text, "method": method})
    boiler_removed = _strip_boilerplate(pages)
    doc.close()
    return {
        "pages": pages,
        "page_count": len(pages),
        "total_chars": sum(len(p["text"]) for p in pages),
        "ocr_engine": engine,
        "ocr_pages": sum(1 for p in pages if "ocr" in p["method"]),
        "tables_found": tables_total,
        "metadata": {**metadata, "boilerplate_lines_removed": boiler_removed},
        "warnings": warnings,
    }
