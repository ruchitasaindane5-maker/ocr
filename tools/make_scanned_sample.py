"""Build an image-only ("scanned") sample PDF for the live-OCR screenshot.

    python tools/make_scanned_sample.py [src.pdf] [repeats] [out]

The output has no text layer at all, so the app must run OCR on every page —
which is exactly what the upload-progress shot in the video shows.
"""
import os
import sys

import pymupdf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "GTM_Command_Center_Setup_Guide (1).pdf")
repeats = int(sys.argv[2]) if len(sys.argv) > 2 else 6
out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(ROOT, "brag-output", "work", "scanned_sample.pdf")

doc = pymupdf.open(src)
new = pymupdf.open()
for _ in range(repeats):
    for page in doc:
        pix = page.get_pixmap(dpi=110)
        np_ = new.new_page(width=page.rect.width, height=page.rect.height)
        np_.insert_image(np_.rect, stream=pix.tobytes("png"))
new.set_metadata({"title": "Scanned sample (image only)", "author": "prototype demo"})
os.makedirs(os.path.dirname(out), exist_ok=True)
new.save(out, deflate=True, garbage=3)
print(f"{out}: {new.page_count} image-only pages")
