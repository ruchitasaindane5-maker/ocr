"""OCR engine detection aur page-image OCR.

Priority order (jo pehle available ho wahi use hota hai):
  1. Tesseract  (pytesseract)  - Hindi (hin) + English ke liye sabse best,
                                 lekin system par tesseract binary chahiye.
  2. EasyOCR                   - Devanagari support, heavy (torch).
  3. RapidOCR (onnxruntime)    - pip se install ho jata hai, English strong,
                                 Hindi weak. Sirf `pip install` se chalta hai.

Koi engine na ho to OCR skip ho jata hai aur sirf PDF ki embedded text
layer use hoti hai - app crash nahi hota.
"""
from __future__ import annotations

import io
import shutil
import threading

_engine = None
_engine_name: str | None = None
_lock = threading.Lock()


def _try_tesseract():
    if shutil.which("tesseract") is None:
        return None
    try:
        import pytesseract  # noqa: F401

        return "tesseract"
    except ImportError:
        return None


def _try_easyocr():
    try:
        import easyocr  # noqa: F401

        return "easyocr"
    except ImportError:
        return None


def _try_rapidocr():
    try:
        import rapidocr_onnxruntime  # noqa: F401

        return "rapidocr"
    except ImportError:
        return None


def detect_engine() -> str | None:
    """Available OCR engine ka naam, ya None."""
    global _engine_name
    if _engine_name is not None:
        return _engine_name or None
    for probe in (_try_tesseract, _try_easyocr, _try_rapidocr):
        name = probe()
        if name:
            _engine_name = name
            return name
    _engine_name = ""
    return None


def _get_engine():
    global _engine
    with _lock:
        if _engine is not None:
            return _engine
        name = detect_engine()
        if name == "easyocr":
            import easyocr

            # mr = Marathi/Devanagari script family, en = English
            _engine = easyocr.Reader(["en", "mr"], gpu=False, verbose=False)
        elif name == "rapidocr":
            from rapidocr_onnxruntime import RapidOCR

            _engine = RapidOCR()
        else:
            _engine = name  # "tesseract" (stateless) ya None
        return _engine


def ocr_image(png_bytes: bytes, lang: str = "hin+eng") -> str:
    """Ek page image (PNG bytes) par OCR chalao, text return karo."""
    name = detect_engine()
    if name is None:
        return ""
    try:
        if name == "tesseract":
            import pytesseract
            from PIL import Image

            img = Image.open(io.BytesIO(png_bytes))
            try:
                return pytesseract.image_to_string(img, lang=lang)
            except Exception:
                # hin traineddata na ho to sirf English se try karo
                return pytesseract.image_to_string(img, lang="eng")
        engine = _get_engine()
        if name == "easyocr":
            import numpy as np
            from PIL import Image

            arr = np.array(Image.open(io.BytesIO(png_bytes)).convert("RGB"))
            return "\n".join(engine.readtext(arr, detail=0, paragraph=True))
        if name == "rapidocr":
            import numpy as np
            from PIL import Image

            arr = np.array(Image.open(io.BytesIO(png_bytes)).convert("RGB"))
            result, _ = engine(arr)
            if not result:
                return ""
            result.sort(key=lambda r: (r[0][0][1], r[0][0][0]))
            return "\n".join(line[1] for line in result)
    except Exception:
        return ""
    return ""
