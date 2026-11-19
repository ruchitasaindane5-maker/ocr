"""PDF -> clean, proper text (page by page) - for any kind of PDF.

Every PDF is different, so extraction happens in several layers:
  1. Embedded text layer, with block-based reading order
     (on multi-column pages the left column first, then the right).
  2. Tables as separate structured lines (cell | cell | cell), so
     table data is not lost when flattened.
  3. Form field (AcroForm) values are added to the text as well.
  4. Cleaning: duplicate lines, "S T A R T" spaced letters, hyphen-broken
     words, and headers/footers repeated on every page
     (same line on 60%+ of pages) are removed.
  5. OCR (auto): scanned pages (text < 80 chars), pages with large
     screenshots, or a bad/garbage text layer are rendered and OCR'd.
     OCR text is deduplicated against the embedded text and merged.
"""
from __future__ import annotations

import re
from collections import Counter

import pymupdf

from . import ocr as ocr_mod

MIN_TEXT_CHARS = 80          # fewer than this = treat as a scanned page
BIG_IMAGE_AREA_RATIO = 0.25  # 25%+ of the page is an image = probably a screenshot
OCR_ZOOM_SCANNED = 3.0       # ~216 DPI for scanned pages
OCR_ZOOM_MERGE = 2.2


def _fix_spaced_letters(line: str) -> str:
    """'G E T  S T A R T E D' -> 'GET STARTED'."""
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
    """'WHATSAPPWHATSAPP AGENTAGENT' -> 'WHATSAPP AGENT' (doubled words
    caused by a duplicate text layer glued together)."""
    out = []
    for tok in line.split(" "):
        if len(tok) >= 8 and len(tok) % 2 == 0 and tok[: len(tok) // 2] == tok[len(tok) // 2:]:
            tok = tok[: len(tok) // 2]
        out.append(tok)
    return " ".join(out)


def _keep_ocr_line(line: str) -> bool:
    """Drop garbage OCR lines (upside-down/cut-off text, symbol junk)."""
    s = line.strip()
    if len(s) < 3:
        return False
    if sum(1 for ch in s if ch.isalnum()) < 2:
        return False
    return _text_quality(s) >= 0.5


def clean_text(raw: str) -> str:
    raw = re.sub(r"([A-Za-z])-\n([a-z])", r"\1\2", raw or "")  # rejoin hyphen-broken words
    lines, prev, seen_long = [], None, set()
    for line in raw.splitlines():
        line = _halve_doubled_tokens(
            _fix_spaced_letters(re.sub(r"[ \t]+", " ", line).strip()))
        if not line or line == prev:
            continue
        # a long line repeated across the page (duplicate text layer) only once
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
    """Add only the new lines from extra (no duplicate OCR/text)."""
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
    """0..1 - how clean the text is (to detect a garbage layer)."""
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
    """Block-based reading order. On multi-column pages the whole left
    column comes first, then the right column - otherwise lines at the same
    height get mixed. Full-width headers/footers are handled separately."""
    try:
        blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
    except Exception:
        return page.get_text("text", sort=True)
    if len(blocks) < 3:
        # with few blocks keep each block whole (no line mixing):
        # top block first, then the left block in full
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
    # Keep full-width blocks in their real position: a header above where the
    # columns start comes first, the rest (footer) goes last. Previously all
    # wide blocks moved to the top — even the footer showed up at the top.
    col_top = min([b[1] for b in left + right], default=0)
    header = sorted([b for b in wide if b[1] <= col_top + 2], key=lambda b: b[1])
    footer = sorted([b for b in wide if b[1] > col_top + 2], key=lambda b: b[1])
    ordered = header + left + right + sorted(rest, key=lambda b: b[1]) + footer
    return "\n".join(b[4].strip() for b in ordered)


def _tables_text(page) -> tuple[str, int]:
    """Convert the page's tables into 'cell | cell' lines."""
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
    """Remove headers/footers repeated on every page (they don't identify a page)."""
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


def extract_pdf(path: str, ocr_mode: str = "auto", progress=None) -> dict:
    """ocr_mode: 'auto' | 'always' | 'never'.
    progress: optional callback(done_pages, total_pages), called after every page."""
    if ocr_mode not in ("auto", "always", "never"):
        ocr_mode = "auto"
    engine = ocr_mod.detect_engine() if ocr_mode != "never" else None
    doc = pymupdf.open(path)
    if doc.needs_pass:
        doc.close()
        raise ValueError("This PDF is password-protected - remove the password first.")
    metadata = {k: v for k, v in (doc.metadata or {}).items() if v}
    pages, tables_total, warnings = [], 0, []
    total_pages = len(doc)
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
            # Scanned page but no OCR engine — don't hide the reason,
            # tell the UI/user so they can install an engine
            warnings.append(
                f"Page {page_no}: is scanned but no OCR engine was found"
                + (f" ({ocr_mod.last_error()})" if ocr_mod.last_error() else "")
                + " — try: pip install opencv-python-headless rapidocr-onnxruntime --no-deps"
            )
        want_ocr = bool(engine) and (
            ocr_mode == "always"
            or (ocr_mode == "auto" and (
                len(embedded) < MIN_TEXT_CHARS or garbage
                or _image_area_ratio(page) > BIG_IMAGE_AREA_RATIO)))
        if want_ocr:
            scanned = len(embedded) < MIN_TEXT_CHARS
            zoom = OCR_ZOOM_SCANNED if scanned else OCR_ZOOM_MERGE
            # On very large pages (poster/A3) the pixmap ate memory —
            # cap at roughly 30MP; quality barely changes
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
        if progress:
            progress(page_no, total_pages)
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
