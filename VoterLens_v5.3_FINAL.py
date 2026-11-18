import os
import re
import glob
import json
import difflib
import collections
import threading
import queue as _queue
import traceback
import importlib.util
from datetime import datetime
from typing import Any

import cv2
import fitz  # PyMuPDF
import numpy as np
import pandas as pd
try:
    import easyocr
except ImportError:
    easyocr = None
import argparse
import csv
import io
import subprocess
import tempfile
import shutil
import customtkinter as ctk
from tkinter import filedialog, messagebox


# ---------------------------- CONFIG ---------------------------------
OCR_DPI = 300

# Working pixel width per rendered page. Replaces a fixed DPI, which produced
# wildly different sizes across rolls because their page boxes differ.
RENDER_TARGET_PX = 2600

# A page image at least this wide is read at its own resolution. Below it, the
# page is upscaled, because the detail is too coarse for the recogniser as-is.
NATIVE_PX_SUFFICIENT = 1800
OCR_LANGS = ["mr", "en"]

# Debug artefacts (segmentation previews + per-card OCR text) contain voter PII
# and are written next to the source PDF. Set False to disable entirely.
DEBUG_DUMP = False

# Output shape.
#   SINGLE_FILE_OUTPUT   one Excel file with a fixed name, overwritten each run,
#                        instead of a timestamped CSV + JSON + two more CSVs.
#   INCLUDE_AUDIT_SHEETS add All_OCR_Cards and Needs_Review tabs. Every observed
#                        card stays in Voters; no OCR result claims verification.
#   CLEAN_OLD_OUTPUTS    delete previous exports for the same PDF before writing.
SINGLE_FILE_OUTPUT = True
INCLUDE_AUDIT_SHEETS = True
CLEAN_OLD_OUTPUTS = False


def _gpu_available():
    """True only if torch was built with CUDA and a device is present."""
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False


USE_GPU = _gpu_available()

# Separates the left-hand block's Latin text from the whole-card Latin text.
BLOCK_EN_MARKER = "<<BLOCK_EN>>"
BLOCK_MR_MARKER = "<<BLOCK_MR>>"
EPIC_MARKER = "<<EPIC>>"

# Prefixes the house number read from its own row, so the parser can trust it
# ahead of anything scraped from the rest of the card.
HOUSE_MARKER = "<<HOUSE>>"

# Prefixes the age read off its own row with the Latin model, which reads the
# printed ASCII digits correctly where the Devanagari model transliterates them.
AGE_MARKER = "<<AGE>>"

# Prefixes the serial read from its own boxed cell, which the whole-card pass
# merges into the EPIC detection.
SERIAL_MARKER = "<<SERIAL>>"
MIN_AGE, MAX_AGE = 18, 120
MAX_LOG_LINES = 700


# ---------------------------- HELPERS --------------------------------

def _safe_mkdir(path):
    os.makedirs(path, exist_ok=True)
    return path


_debug_warned = [False]


def _safe_write(path, payload, log=None, image=False):
    """Write a debug artefact. Never let it abort an extraction run.

    The debug folder sits next to the source PDF, so anything that touches it
    mid-run (a user clearing it, sync software, antivirus) previously raised
    FileNotFoundError from inside the per-card loop and destroyed an hour of
    OCR work. Debug output is disposable; extraction is not.
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if image:
            cv2.imwrite(path, payload)
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write(payload)
        return True
    except Exception as e:
        if log and not _debug_warned[0]:
            _debug_warned[0] = True
            log(f"Debug output disabled for this run ({type(e).__name__}: {e}). "
                f"Extraction continues normally.")
        return False


_DEV_DIGITS = str.maketrans("०१२३४५६७८९",
                            "0123456789")


def _ascii_digits(text):
    """Rewrite Devanagari digits as ASCII.

    The cards print numbers in ASCII, but the Devanagari recogniser
    transliterates them, so the same house number came out as 623a from one
    pass and ६२३a from another. Normalising makes the column
    consistent and comparable.
    """
    return text.translate(_DEV_DIGITS) if text else text


def _col_letter(n):
    out = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def _cluster_positions(indices, max_gap=4):
    if len(indices) == 0:
        return []
    groups = [[int(indices[0])]]
    for x in indices[1:]:
        x = int(x)
        if x - groups[-1][-1] <= max_gap:
            groups[-1].append(x)
        else:
            groups.append([x])
    return [int(sum(g) / len(g)) for g in groups]


def _iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    if inter == 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0


def _normalize_epic_candidate(token):
    """Validate a printed ID. Never guess its letters or digits."""
    raw = _ascii_digits(str(token or '')).strip().upper()
    return raw if re.fullmatch(r'[A-Z]{3}[0-9]{7}', raw) else None


# ------------------------- IMAGE PREPROCESSOR -------------------------

class ImagePreprocessor:

    @staticmethod
    def for_lines(gray):
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        return cv2.adaptiveThreshold(
            blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 31, 13
        )


# --------------------------- SEGMENTATION -----------------------------

class CardSegmenter:
    """
    Detect voter-card rectangles from page borders/grid lines.
    Falls back to a 3-column grid only when line/contour detection is not usable.
    """

    @classmethod
    def segment(cls, page_gray, layout=None):
        """Keep observed card borders, including one-card and partial pages.

        The supplied roll has 993 actual rectangles. Expanding its partial
        pages into a 30-cell lattice fabricated 245 extra regions and missed
        the sole card on page 34. A serial sub-box distinguishes real cards
        from cover/summary tables. No fixed page count or serial is assumed.
        """
        boxes = [b for b in cls._detect_card_rectangles(page_gray)
                 if cls._has_serial_cell(page_gray, b)]
        # Use grid detection only when no outer rectangles were recovered.
        # Mixing detectors can duplicate a shifted part of a real card.
        if not boxes:
            boxes = [b for b in cls._detect_grid_cells(page_gray)
                     if cls._has_serial_cell(page_gray,b)]
        boxes = cls._sort_boxes(boxes)
        return ([cls._crop_with_margin(page_gray, b) for b in boxes],
                boxes, f'observed:{len(boxes)}')

    @staticmethod
    def _has_serial_cell(gray, box):
        x, y, w, h = box
        roi = gray[y:y + int(h * .24), x:x + int(w * .40)]
        if roi.size == 0:
            return False
        _, bw = cv2.threshold(roi, 180, 255, cv2.THRESH_BINARY_INV)
        contours, _ = cv2.findContours(bw, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        return any(.24*w <= cw <= .38*w and .08*h <= ch <= .22*h
                   for _, _, cw, ch in (cv2.boundingRect(c) for c in contours))

    @classmethod
    def _detect_card_rectangles(cls, gray):
        h, w = gray.shape[:2]
        bw = ImagePreprocessor.for_lines(gray)

        hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(25, w // 35), 1))
        vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, h // 55)))
        horizontal = cv2.morphologyEx(bw, cv2.MORPH_OPEN, hk)
        vertical = cv2.morphologyEx(bw, cv2.MORPH_OPEN, vk)
        grid = cv2.bitwise_or(horizontal, vertical)
        grid = cv2.dilate(grid, np.ones((3, 3), np.uint8), iterations=1)

        contours, _ = cv2.findContours(grid, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []

        min_w, max_w = int(w * 0.20), int(w * 0.39)
        min_h, max_h = int(h * 0.045), int(h * 0.20)
        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)
            if min_w <= cw <= max_w and min_h <= ch <= max_h:
                if y < int(h * 0.02):
                    continue
                candidates.append((x, y, cw, ch))

        # Remove near-duplicates/nested rectangles.
        candidates.sort(key=lambda b: b[2] * b[3], reverse=True)
        kept = []
        for b in candidates:
            if all(_iou(b, k) < 0.65 for k in kept):
                kept.append(b)

        # Keep only sizes around median card dimensions to discard legends/headers.
        if len(kept) >= 6:
            mw = np.median([b[2] for b in kept])
            mh = np.median([b[3] for b in kept])
            kept = [
                b for b in kept
                if 0.65 * mw <= b[2] <= 1.35 * mw and 0.55 * mh <= b[3] <= 1.45 * mh
            ]
        return kept

    @classmethod
    def _detect_grid_cells(cls, gray):
        h, w = gray.shape[:2]
        bw = ImagePreprocessor.for_lines(gray)
        hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(30, w // 25), 1))
        vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(30, h // 35)))
        hz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, hk)
        vt = cv2.morphologyEx(bw, cv2.MORPH_OPEN, vk)

        x_strength = (vt > 0).sum(axis=0)
        y_strength = (hz > 0).sum(axis=1)

        xs = np.where(x_strength > h * 0.12)[0]
        ys = np.where(y_strength > w * 0.18)[0]
        x_lines = _cluster_positions(xs, max_gap=max(3, w // 800))
        y_lines = _cluster_positions(ys, max_gap=max(3, h // 1200))

        # Reduce many noisy lines by requiring useful spacing.
        def spaced(vals, min_gap):
            out = []
            for v in vals:
                if not out or v - out[-1] >= min_gap:
                    out.append(v)
            return out

        x_lines = spaced(x_lines, int(w * 0.12))
        y_lines = spaced(y_lines, int(h * 0.035))

        if len(x_lines) < 4 or len(y_lines) < 3:
            return []

        cells = []
        for yi in range(len(y_lines) - 1):
            y1, y2 = y_lines[yi], y_lines[yi + 1]
            ch = y2 - y1
            if not (h * 0.045 <= ch <= h * 0.20):
                continue
            for xi in range(len(x_lines) - 1):
                x1, x2 = x_lines[xi], x_lines[xi + 1]
                cw = x2 - x1
                if w * 0.20 <= cw <= w * 0.40:
                    cells.append((x1, y1, cw, ch))
        return cells

    @staticmethod
    def _crop_with_margin(gray, box):
        x, y, w, h = box
        H, W = gray.shape[:2]
        mx = max(2, int(w * 0.01))
        my = max(2, int(h * 0.02))
        x1 = max(0, x + mx)
        y1 = max(0, y + my)
        x2 = min(W, x + w - mx)
        y2 = min(H, y + h - my)
        return gray[y1:y2, x1:x2]

    @staticmethod
    def _sort_boxes(boxes):
        if not boxes:
            return []
        rows = []
        tolerance = float(np.median([b[3] for b in boxes])) * .30
        for box in sorted(boxes, key=lambda b: (b[1], b[0])):
            if rows and abs(box[1] - rows[-1][0][1]) <= tolerance:
                rows[-1].append(box)
            else:
                rows.append([box])
        return [b for row in rows for b in sorted(row, key=lambda b: b[0])]

    @staticmethod
    def debug_image(gray, boxes, label=""):
        img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        for i, (x, y, w, h) in enumerate(boxes, 1):
            cv2.rectangle(img, (x, y), (x + w, y + h), (0, 0, 255), 2)
            cv2.putText(img, str(i), (x + 4, y + 22), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (0, 0, 255), 2, cv2.LINE_AA)
        if label:
            cv2.putText(img, label, (20, 35), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (0, 0, 255), 2, cv2.LINE_AA)
        return img


# ----------------------------- PARSER --------------------------------

class VoterParser:
    # The same roll is published in Marathi and in English. English cards
    # read far more reliably, so labelled English rows are extracted
    # directly by _label_fields; Devanagari rows go through the fuzzy
    # matchers below. Old exact-literal regexes were removed: scanned
    # labels almost never match them.

    # ---- OCR-tolerant label matching -------------------------------------
    # Scanned rolls rarely reproduce Devanagari labels exactly. Observed real
    # output for "वय" includes यय / चय / बय / वग / बग / तग, and "क्रमांक"
    # appears as ऋमांन / फमांफ / कमाक. Exact-literal regexes miss nearly all of
    # them, so labels are matched fuzzily and values are taken positionally.

    _DEV_TOKEN = re.compile(r"[ऀ-ॿ]+")
    # ः is the Devanagari visarga. OCR routinely renders the colon of
    # "नाव:" as one, producing नायः, so without it the label stayed glued to its
    # value and names came out as "नायः पांडूरंग घार्गे".
    _SPLIT = re.compile("[:：;।\\-–—!\"'·ः]+")

    @staticmethod
    def _ratio(a, b):
        return difflib.SequenceMatcher(None, a, b).ratio()

    @classmethod
    def _has_label(cls, line, targets, cutoff=0.6):
        for tok in cls._DEV_TOKEN.findall(line):
            for tgt in targets:
                if cls._ratio(tok, tgt) >= cutoff:
                    return True
        return False

    @classmethod
    def _has_leading_label(cls, line, targets, cutoff=0.6, ntokens=2):
        """Match a label only where a label can occur: at the start of the row.

        Searching the whole line let a word inside the value match a label of
        the wrong kind. "नाव : तेजश्री विलास गोरे" scored as both a name row and
        a relation row, so the elector name was filed as the father's name and
        the name column came out empty.

        ntokens matters. Two are needed to match a label such as
        "मतदाराचे नाव", but the second token is often the first word of the
        value, and Marathi given names collide with label words: सरिता scores
        0.67 against पिता, which discarded that elector's name entirely. Checks
        that exclude a row therefore pass ntokens=1.
        """
        toks = cls._DEV_TOKEN.findall(line or "")
        if not toks:
            return False
        for tok in toks[:max(1, ntokens)]:
            for tgt in targets:
                if cls._ratio(tok, tgt) >= cutoff:
                    return True
        return False

    @classmethod
    def _is_house_row(cls, line):
        """True only for a real house-number row.

        The label word alone is not a safe signal. मालन, a common Marathi given
        name, scores 0.75 against मकान, so electors with that name had their
        name row classed as the house row and lost their name. A genuine house
        row pairs its label with क्रमांक or carries the number itself.
        """
        toks = cls._DEV_TOKEN.findall(line or "")
        if not toks:
            return False
        head = max((cls._ratio(toks[0], t) for t in ("घर", "घट", "मकान")), default=0.0)
        if head < 0.66:
            return False
        if cls._NUM.search(line):
            return True
        return any(cls._ratio(t, "क्रमांक") >= 0.55 or cls._ratio(t, "नंबर") >= 0.6
                   for t in toks[1:3])

    _HOUSE_LABEL_WORDS = ("क्रमांक", "कमांक", "ऋमांक", "किमांक", "फमांक",
                          "मकान", "घर", "घट", "नंबर", "नं", "मांच", "मांक")

    @classmethod
    def _house_value(cls, line):
        """The house field's value, which is not always a number.

        Many cards give a locality instead: बजारपेट मारुती मंदिर, प्रीत वाडा,
        ढानें आळी, ऍट पोस्ट पाल. Requiring a digit dropped every one of those,
        which is most of why this column sat at 80%. Two things still have to be
        filtered out: the label itself, which survives when OCR omits the colon
        and leaves "क्रमांक" as the apparent value, and photo-box noise.
        """
        val = cls._value_after_label(line).strip(" :.-–—;!\"'=")
        toks = val.split()
        while toks and any(cls._ratio(toks[0], t) >= 0.62
                           for t in cls._HOUSE_LABEL_WORDS):
            toks.pop(0)
        val = " ".join(toks).strip(" :.-–—;!\"'=")
        if not val:
            return None

        # A number, where there is one: that is the house number proper.
        m = re.search(r"[0-9०-९]{1,4}\s?[-/]?\s?[A-Za-zऀ-ॿ]?", val)
        if m and m.group(0).strip():
            return m.group(0).strip()[:80]

        # Otherwise a locality, but only if it reads as real words.
        if (len(val) >= 4 and cls._DEV_CHAR.search(val)
                and not cls._has_label(val, cls.FURNITURE_LABELS, 0.6)
                and not cls._is_gender_word(val)
                and not cls._has_leading_label(val, cls.NAME_LABELS_ALL, 0.75, ntokens=1)
                and not cls._is_relation_row(val)):
            return val[:80]
        return None

    @classmethod
    def _is_relation_row(cls, line):
        """True only for a real "<relation>चे नाव" row.

        Matching the relation word alone is not safe. Marathi given names
        ending in -िता score above any workable cutoff against पिता: ललिता
        0.67, प्रणिता 0.73, and सरिता, अनिता, सुनिता and संगिता are all in the
        same family. Those rows were read as the father's name, so the elector
        lost their own. On these cards the label always carries नाव after the
        relation word, which separates the two cleanly. A very strong match on
        the relation word by itself is still accepted, for rows where OCR drops
        the नाव entirely.
        """
        toks = cls._DEV_TOKEN.findall(line or "")
        if not toks:
            return False
        best = max((cls._ratio(toks[0], t) for t in cls.REL_LABELS_ALL), default=0.0)
        if best >= 0.85:
            return True
        if best < 0.62:
            return False
        return any(cls._ratio(t, "नाव") >= 0.6 or cls._ratio(t, "नावः") >= 0.6
                   for t in toks[1:3])

    @classmethod
    def _value_after_label(cls, line):
        """Text to the right of the first separator, else text after label token."""
        parts = cls._SPLIT.split(line, maxsplit=1)
        if len(parts) == 2 and parts[1].strip():
            return parts[1].strip()
        toks = line.split()
        return " ".join(toks[1:]).strip() if len(toks) > 1 else ""

    @staticmethod
    def _to_int(s):
        try:
            return int(s)
        except (TypeError, ValueError):
            return None

    _NUM = re.compile(r"[0-9०-९]{1,4}")

    # Label vocabularies, including the OCR variants actually observed on
    # scanned Maharashtra rolls (नाव read as नाय / नान / नाच, and so on).
    NAME_LABELS_ALL = ("नाव", "नाय", "नान", "नाच", "नाम")
    REL_LABELS_ALL = ("वडिलांचे", "वडिल", "वडील", "पतीचे", "पती",
                      "आईचे", "पिता", "पति", "माता", "पर्तीचे")
    FURNITURE_LABELS = ("छायाचित्र", "उपलब्ध", "छायाचिन्न", "उपलच्ध", "छायाचिज्र",
                        "छायाचेन्न", "छागाचित्र", "छायाांयेत्न", "उगलच्ध",
                        "रपनन्ध", "रणनन्ध", "उपनन्व", "सपनस", "उपनस", "उपनः")
    HOUSE_LABELS_ALL = ("घर", "घट", "क्रमांक", "मकान", "ऋमांक", "किमांक")

    # Roll-administration vocabulary found on cover/summary pages only. These
    # words never occur inside a real voter card.
    _META = re.compile(
        "|".join((
            "मतदारसंघ", "मत्तदारसंघ", "विधानसभा", "लोकसभा",
            "पुनरिक्षण", "पुनरीक्षण", "आरक्षण", "अंतिम", "प्रारूप",
            "एकत्रीकरण", "विलीनीकरण", "तपशील", "सर्वसाधारण", "सर्चसाधारण",
            "मतदान\\s*केंद्र", "मतदान\\s*क्षेत्र", "विभागांचा", "भागाचा",
            "एकूण", "प्रसिद्ध", "यादी\\s*क्रमांक", "याद्यांचे",
            # "यादी ओळख" is the summary table's own row label. It survived on a
            # summary page that also held one real elector, so the page-level
            # filter kept the page and this row rode along as voter 994.
            "यादी\\s*ओळख", "ओळख", "सारांश", "मूळ\\s*यादी", "प्रकार",
            "जिल्हा", "तालुका", "राज्य",
            # "मतदार यादी" is the document's own title. OCR renders the last
            # word loosely (यादा, यादि), so only the stem is matched.
            "मतदार\\s*याद", "मतदान", "तयार\\s*करण्यात", "संख्या",
        ))
    )

    # Vowel signs, nukta, anusvara and virama. OCR corrupts these far more often
    # than it corrupts base consonants, so comparing consonant skeletons matches
    # real variants that a raw string ratio misses: गांहेला against महिला scores
    # only 0.50 intact, but 0.67 as गहल against महल.
    _MATRA = re.compile(r"[ऀ-ःऺ-्॑-ॗॢॣ]")

    @classmethod
    def _skeleton(cls, token):
        return cls._MATRA.sub("", token)

    # The leading consonant of लिंग is routinely misread, giving निंग, सिंग,
    # तिग and similar. Matching the shape rather than the exact word keeps the
    # age/gender row identifiable, which every other field depends on.
    @classmethod
    def _is_gender_word(cls, text):
        """True when the text is essentially just पुरुष or महिला.

        On cards where the लिंग label is unreadable the bare gender word
        survives as its own line and was being stored as the elector name
        (महला, पृरूप). A real name is longer and scores far lower here.
        """
        toks = cls._DEV_TOKEN.findall(text or "")
        # A bare gender word stands alone. Allowing several tokens let the
        # skeleton test fire on ordinary two-word values: प्रीत reduces to परत
        # against पुरुष's परष, so the locality "प्रीत वाडा" was scored a gender
        # and that card's house field was thrown away.
        if len(toks) != 1 or len(toks[0]) > 12:
            return False
        for tok in toks:
            for tgt in ("पुरुष", "महिला", "स्त्री"):
                r = cls._ratio(tok, tgt)
                # Skeletons are compared only for the two long forms, as in
                # _classify_gender. स्त्री reduces to सतर, which scores 0.67
                # against ordinary names such as संचिता and सुनीता and made
                # those rows look like a bare gender word, so the elector's own
                # name was discarded.
                if tgt != "स्त्री":
                    r = max(r, cls._ratio(cls._skeleton(tok), cls._skeleton(tgt)))
                if r >= 0.62:
                    return True
        return False

    _GEN_SPLIT = re.compile(r"[लनसतचमब][िीे]ं?ग|लिंग|लींग|िंग")

    @classmethod
    def _gender_label_pos(cls, toks):
        """Index of the लिंग label among a row's tokens, or None.

        Matching must be per token, not by substring. "सिंग" is both a plausible
        OCR reading of लिंग and a piece of very common Marathi names, so a
        substring search fired inside मानसिंगराव, धनसिंग and जयसिंग. Those name
        rows were then treated as the gender row: their names were dropped and
        the trailing word was scored as a gender, which is why surnames ending
        in -ील were counted Female. A real label token is short and scores at
        least 0.7; the longest name element here reached only 0.60.
        """
        for i, t in enumerate(toks):
            if cls._ratio(t, "लिंग") >= 0.7:
                return i
            if len(t) <= 5 and re.fullmatch(r"[लनसतचमब][िीे]ं?ग", t):
                return i
        return None

    @classmethod
    def _classify_gender(cls, line):
        # Confine the decision to the text after the लिंग label. Scanning the
        # whole line let ordinary Marathi names trip the weaker heuristics and
        # flipped real Male cards to Female.
        toks_all = cls._DEV_TOKEN.findall(line or "")
        pos = cls._gender_label_pos(toks_all)
        labelled = pos is not None
        seg = " ".join(toks_all[pos + 1:]) if labelled else line

        # Without a लिंग label there is nothing marking this text as a gender,
        # so only a near-exact word counts. At the labelled threshold the
        # skeleton test matched ordinary names: महादेव scored 0.57 against
        # महिला and made that elector Female.
        cutoff = 0.55 if labelled else 0.80

        best, score = None, 0.0
        for tok in cls._DEV_TOKEN.findall(seg):
            # ष plus a प onset is पुरुष and survives heavy corruption. The प
            # requirement matters: ordinary names carry ष too (नर्षा, देशमुष,
            # कृष्णत्त), and without it they were all scored Male.
            if labelled and "ष" in tok and len(tok) >= 3 and tok.startswith("प"):
                return "Male"
            for tgt, label in (("पुरुष", "Male"), ("महिला", "Female"), ("स्त्री", "Female")):
                r = cls._ratio(tok, tgt)
                # Skeletons are compared only for the two long forms. स्त्री
                # reduces to सतर, which scored 0.57 against ordinary names such
                # as सूनर्णा and marked real electors Female.
                # Only behind a लिंग label, too: without one the skeleton of the
                # surname पोरे (पर) scores 0.80 against पुरुष's परष, which made
                # three women on the source roll read as both Male and Female
                # and dropped their gender as a conflict.
                if tgt != "स्त्री" and labelled:
                    r = max(r, cls._ratio(cls._skeleton(tok), cls._skeleton(tgt)))
                if r > score and r >= cutoff:
                    best, score = label, r
        if best:
            return best

        # Only with an explicit लिंग label do we fall back to shape: the female
        # forms keep a ...ि/े + ल/स/न + ा tail even when the first consonant is
        # misread (मदिला, मडिसा, ्पहिसा, गाहेला).
        if labelled:
            for tok in cls._DEV_TOKEN.findall(seg):
                if len(tok) >= 4 and re.search(r"[िीेै][लसन]ा?$|ह[िे][लसन]", tok):
                    return "Female"
        if re.search(r"\b(male|m)\b", seg, re.I):
            return "Male"
        if re.search(r"\b(female|f)\b", seg, re.I):
            return "Female"
        return None

    _DEV_CHAR = re.compile(r"[ऀ-ॿ]")

    @classmethod
    def parse_auto(cls, text_mr, page, card, confidence=None, text_en=''):
        if cls.looks_english(text_mr, text_en):
            return cls.parse_english(text_en, text_en, page, card, confidence)
        return cls.parse(text_mr, page, card, confidence, text_en)

    @classmethod
    def looks_english(cls, text_mr, block_en):
        # Marathi OCR of English can hallucinate many Devanagari characters.
        # Explicit English field labels are stronger evidence than that count.
        return sum(bool(re.search(p, block_en or '', re.I|re.M)) for p in
                   (r'^\s*Name\s*:', r'^\s*House\s*(?:Number|No)',
                    r'\bAge\s*:', r'\bGender\s*:')) >= 2

    @classmethod
    def parse_english(cls, block_en, whole_en, page, card, confidence=None):
        return cls._parse_structured('', whole_en or block_en, page, card, confidence, 'en')

    @classmethod
    def parse(cls, text, page, card, confidence=None, text_en=''):
        return cls._parse_structured(text, text_en, page, card, confidence, 'mr')

    @classmethod
    def _label_fields(cls, text, language):
        if language == 'en':
            patterns = (
                ('relation', r"^(?:Father|Husband|Mother|Guardian|Other)\s*'?\s*s?\s*(?:Name)?\s*[:.;-]\s*(.*)$"),
                ('name', r"^(?:Elector'?s?\s+)?Name\s*[:.;-]?\s*(.*)$"),
                ('house', r'^House\s*(?:Number|No\.?)\s*[:.;-]?\s*(.*)$'),
            )
            stop = r'^(?:Age|Gender|Photo|Available)\b'
        else:
            patterns = (
                ('relation', r'^(?:वडिलांचे|वडीलांचे|वडील|वडिल|वडिलाचे|वडिलांंचे|पतीचे|पतीचें|पती|पर्तीचे|आईचे|आरईईचे|आरईचे|आई|पिता|पति|माता|इतर)(?:\s*का)?\s*(?:नाव|नावः|नावं|नाम)?\s*[:ः.;-]?\s*(.*)$'),
                ('name', r'^(?:(?:मतदाराचे|मतदाराचे नाव|मतदाता का)\s*)?(?:नाव|नाय|नाद|नव|नाम)(?=[\s:ः.;-]|$)\s*[:ः.;-]?\s*(.*)$'),
                ('house', r'^(?:घर|घट|मकान)\s*(?:क्रमांक|क्रमाांक|क्रमाक|क्रमांकं|क्रनांक|कमांक|क्रं?\.?|नंबर|नं\.?)\s*[:ः.;-]?\s*(.*)$'),
            )
            stop = r'^(?:वय|वयः|दय|वग|बय|आयु|उम्र|लिंग|छायाचित्र|उपलब्ध|पुरुष|महिला|स्त्री)(?=[\s:ः]|$)'
        values = collections.defaultdict(list)
        current, parts = None, []
        def flush():
            nonlocal current, parts
            if current:
                value = ' '.join(parts).strip(' :ः;')
                # "वडिलांचे नवः बाळासो सोनावले": the label's own नाव, corrupted
                # past the alternation above, survives at the head of the value.
                # Both tests are required — the visarga marks it as a label
                # remnant, so real first names that merely resemble नाव
                # (नवाब) are left alone.
                head = value.split()
                if (current in ('name', 'relation') and head
                        and head[0].endswith('ः')
                        and max(cls._ratio(head[0].rstrip('ः'), t)
                                for t in ('नाव', 'नाम', 'नव')) >= .6):
                    value = ' '.join(head[1:])
                values[current].append(value)
            current, parts = None, []
        for raw in (text or '').splitlines():
            line = re.sub(r'\s+', ' ', raw).replace('’', "'").replace('‘', "'").strip().lstrip("|!'\" ")
            if not line:
                continue
            if line.startswith('<<') or re.search(stop, line, re.I):
                flush()
                continue
            matched = False
            for key, pattern in patterns:
                match = re.match(pattern, line, re.I)
                if match:
                    flush()
                    current, parts = key, [match.group(1).strip()] if match.group(1).strip() else []
                    matched = True
                    break
            if matched:
                continue
            # A relation label the literal alternation missed. OCR wrote पतीचे
            # as प्तीचे on 39 cards of the source roll; the row then counted as a
            # continuation of the name above it, so the elector's name came out
            # as "चंदना राजेंद्र थोरात प्तीचे नावः राजेंद्र थोरात". _is_relation_row
            # scores the label instead of matching it literally, and requires
            # नाव after it so that given names ending in -िता cannot trip it.
            if language == 'mr' and cls._is_relation_row(line):
                flush()
                value = cls._value_after_label(line).strip()
                current, parts = 'relation', [value] if value else []
                continue
            # A house row whose label OCR corrupted past the literal
            # alternation (घर ऋमांक, मकान किमांक, घट क्रनांक). _is_house_row
            # scores the leading word and requires a number or a क्रमांक-like
            # token, so ordinary name rows cannot reach here.
            if language == 'mr' and cls._is_house_row(line):
                flush()
                value = cls._house_value(line)
                current, parts = 'house', [value] if value else []
                continue
            # Continuations must occur AFTER the label and BEFORE the next
            # labelled field. Never steal the preceding person's/relative's row.
            if current:
                if re.search(r'\b[A-Z]{3}[0-9]{7}\b', line) or re.fullmatch(r'[0-9०-९]{1,5}', line):
                    if current != 'house':
                        flush()
                        continue
                if current in ('name','relation') and re.search(r'[0-9०-९]|<<', line):
                    flush()
                    continue
                if language == 'mr' and not cls._DEV_CHAR.search(line) and current != 'house':
                    continue
                parts.append(line)
        flush()
        return values

    @classmethod
    def _parse_structured(cls, text_mr, text_en, page, card, confidence, language):
        v = dict(page=page, card=card, serial_no=None, serial_status='missing',
                 epic_no=None, epic_status='missing', name=None, name_marathi=None,
                 father_husband_name=None, father_husband_name_marathi=None,
                 house_no=None, age=None, gender=None, language=language,
                 ocr_confidence=round(float(confidence),3) if confidence is not None else None,
                 raw_text=text_mr or '', raw_text_en=text_en or '', review_reason='')
        source = text_en if language == 'en' else text_mr
        fields = cls._label_fields(source, language)
        notes = []
        lines = (text_en or '').splitlines()
        # ROI reads arrive as their own marker lines. A marker comes from a
        # single boxed row read with a restricted allowlist, so it outranks
        # anything scraped from the whole-card pass.
        age_marks = set()
        house_marks = []
        for line in lines:
            if line.startswith(AGE_MARKER):
                tok = line[len(AGE_MARKER):].strip()
                if re.fullmatch(r'\d{1,3}', tok) and MIN_AGE <= int(tok) <= MAX_AGE:
                    age_marks.add(int(tok))
            elif line.startswith(HOUSE_MARKER):
                tok = _ascii_digits(line[len(HOUSE_MARKER):].strip())
                if tok:
                    house_marks.append(tok)
        house_marks = list(dict.fromkeys(house_marks))
        for key, dest in [('name', 'name' if language=='en' else 'name_marathi'),
                          ('relation', 'father_husband_name' if language=='en' else 'father_husband_name_marathi'),
                          ('house', 'house_no')]:
            candidates = list(dict.fromkeys(fields.get(key, [])))
            if key == 'house':
                # House values are numbers or locality words and are never
                # script-sensitive, so normalise Devanagari digits before
                # comparing candidates, then put the trusted ROI read first.
                candidates = [_ascii_digits(c).strip() for c in candidates]
                if house_marks:
                    candidates = house_marks + candidates
                candidates = list(dict.fromkeys(candidates))
            filled = [c for c in candidates if c]
            if filled:
                # Within one spatially ordered pass, the first name label
                # belongs to the elector. A dropped relationship label must
                # not replace that name with a longer relative's name.
                v[dest] = filled[0]
                if len(filled)>1 and any(c not in v[dest] for c in filled):
                    notes.append(key+'_ocr_conflict')
            if key == 'house':
                v['house_status'] = 'read' if filled else ('blank_in_source' if candidates else 'not_read')
        if v['house_no'] is not None:
            v['house_no'] = _ascii_digits(v['house_no'])
        joined = _ascii_digits(source or '')
        age_pattern = r'\bAge\s*[:.;-]?\s*(\d{2,3})(?!\d)' if language=='en' else r'(?:वय|वयः|दय|बय|वग|आयु|उम्र)\s*[:ः.;-]?\s*(\d{2,3})(?!\d)'
        ages = {int(m) for m in re.findall(age_pattern, joined, re.I) if MIN_AGE<=int(m)<=MAX_AGE}
        if len(age_marks)==1:
            # The Latin-model row read is the authority on printed digits;
            # the Devanagari whole-card pass transliterates them wrongly.
            v['age'] = next(iter(age_marks))
            if len(ages)==1 and next(iter(ages)) != v['age']:
                notes.append('age_ocr_conflict')
        elif len(ages)==1:
            v['age'] = ages.pop()
        elif ages:
            notes.append('age_ocr_conflict')
        genders = set()
        for line in joined.splitlines():
            if language=='en':
                match = re.search(r'Gender\s*[:.;-]?\s*(Female|Male|Other|Third Gender)\b',line,re.I)
                if match:
                    genders.add(match.group(1).title())
            else:
                match = re.search(r'(?:लिंग|लींग|निंग|सिंग)\s*[:ः.;-]?\s*(महिला|पुरुष|स्त्री|तृतीयपंथी)(?=[\s.,;]|$)',line)
                if match:
                    genders.add({'महिला':'Female','पुरुष':'Male','स्त्री':'Female','तृतीयपंथी':'Other'}[match.group(1)])
        if not genders and language != 'en':
            # The printed value itself is often corrupted (महिला read as मडिला,
            # महिल, नहिला), which the literal alternation above cannot match and
            # which left 71 of 993 cards on the source roll with no gender at
            # all, every one of them female. _classify_gender scores the word
            # against the real forms and only fires behind a लिंग label.
            for line in joined.splitlines():
                guess = cls._classify_gender(line)
                if guess:
                    genders.add(guess)
        if len(genders)==1:
            v['gender'] = genders.pop()
        elif genders:
            notes.append('gender_ocr_conflict')
        serials = [line[len(SERIAL_MARKER):].strip() for line in lines if line.startswith(SERIAL_MARKER)]
        if not serials:
            serials = [l.strip() for l in (source or '').splitlines()[:2]
                       if re.fullmatch(r'[0-9०-९]{1,5}', l.strip())]
        serials = list(dict.fromkeys(_ascii_digits(x) for x in serials if re.fullmatch(r'[0-9०-९]{1,5}',x) and int(x)>0))
        if len(serials)==1:
            v['serial_no'], v['serial_status'] = serials[0], 'read'
        elif serials:
            notes.append('serial_ocr_conflict')
        ids = []
        for line in lines:
            if line.startswith(EPIC_MARKER):
                payload = line[len(EPIC_MARKER):].upper()
                ids.extend(re.findall(r'(?<![A-Za-z0-9])[A-Z]{3}[0-9]{7}(?![A-Za-z0-9])', payload))
                # The ROI reader joins its tokens with spaces, so a real EPIC
                # can arrive as "NYS 6606669", which the boundary regex above
                # cannot see. Compact the boxed-cell read and scan again; no
                # letters or digits are invented by this.
                compact = re.sub(r'[^A-Z0-9]', '', payload)
                if compact != payload:
                    ids.extend(re.findall(r'(?<![A-Z0-9])[A-Z]{3}[0-9]{7}(?![0-9])', compact))
        if not ids:
            for line in lines[:3] + (text_mr or '').splitlines()[:3]:
                ids.extend(re.findall(r'(?<![A-Za-z0-9])[A-Z]{3}[0-9]{7}(?![A-Za-z0-9])',line.upper()))
        ids = list(dict.fromkeys(ids))
        if len(ids)==1:
            v['epic_no'], v['epic_status'] = ids[0], 'format_ok'
        elif ids:
            v['epic_status'] = 'conflict'
            notes.append('epic_ocr_conflict')
        v['review_reason'] = '; '.join(notes)
        return cls.assess(v)

    @staticmethod
    def assess(v):
        generated={'missing_serial_no','missing_epic_no','missing_age','missing_gender',
                   'missing_name','missing_relation','short_name_review_source',
                   'short_relation_review_source','low_ocr_confidence','house_row_not_read'}
        notes = [x for x in str(v.get('review_reason') or '').split('; ') if x and x not in generated]
        for key in ('serial_no','epic_no','age','gender'):
            if v.get(key) is None or v.get(key)=='':
                notes.append('missing_'+key)
        for key, val in [('name', v.get('name') or v.get('name_marathi')),
                         ('relation',v.get('father_husband_name') or v.get('father_husband_name_marathi'))]:
            if not val:
                notes.append('missing_'+key)
            elif len(str(val).split())<2:
                notes.append('short_'+key+'_review_source')
        if v.get('ocr_confidence') is not None and v['ocr_confidence'] < .60:
            notes.append('low_ocr_confidence')
        if v.get('house_status') == 'not_read':
            notes.append('house_row_not_read')
        v['review_reason'] = '; '.join(dict.fromkeys(notes))
        v['parse_status'] = 'needs_review' if v['review_reason'] else 'parsed'
        return v

    @staticmethod
    def is_valid(v):
        """Complete parsed fields do not imply independently verified spelling."""
        return VoterParser.assess(v)['parse_status'] == 'parsed'


# ---------------------------- OCR ENGINE ------------------------------

class TesseractReader:
    """Optional local OCR backend for CLI verification. No cloud API is used."""
    def __init__(self, language, tessdata_dir=None):
        self.language, self.tessdata_dir = language, tessdata_dir
        if shutil.which('tesseract') is None:
            raise RuntimeError('Tesseract is not on PATH. Use EasyOCR or install Tesseract with mar and eng language data.')

    def _read(self, image, psm, allowlist=None):
        ok, buf = cv2.imencode('.png',image)
        if not ok:
            raise RuntimeError('Cannot encode OCR image')
        cmd=['tesseract','stdin','stdout','-l',self.language,'--psm',str(psm)]
        if self.tessdata_dir:
            cmd += ['--tessdata-dir',self.tessdata_dir]
        if allowlist:
            cmd += ['-c','tessedit_char_whitelist='+allowlist]
        # Set the output variable directly. A custom tessdata directory may
        # contain language files but no configs/tsv file; Tesseract otherwise
        # silently prints plain text with exit code zero.
        cmd += ['-c','tessedit_create_tsv=1']
        env=os.environ.copy()
        env.setdefault('OMP_THREAD_LIMIT','1')
        proc=subprocess.run(cmd,input=buf.tobytes(),capture_output=True,timeout=90,env=env)
        if proc.returncode:
            raise RuntimeError(proc.stderr.decode('utf-8',errors='replace')[-1500:])
        output=proc.stdout.decode('utf-8')
        if not output.startswith('level\t'):
            raise RuntimeError('Tesseract did not return TSV output: '+proc.stderr.decode('utf-8',errors='replace')[-500:])
        words=[]
        for row in csv.DictReader(io.StringIO(output),delimiter='\t',quoting=csv.QUOTE_NONE):
            if row.get('level')!='5' or not row.get('text','').strip():
                continue
            x,y,w,h=[int(row[k]) for k in ('left','top','width','height')]
            words.append(([[x,y],[x+w,y],[x+w,y+h],[x,y+h]],row['text'],max(0,float(row['conf']))/100))
        return words

    def readtext(self,image,**kwargs):
        return self._read(image,6,kwargs.get('allowlist'))

    def recognize(self,image,**kwargs):
        allowlist=kwargs.get('allowlist')
        if allowlist=='0123456789':
            # Short isolated numbers are sometimes treated as punctuation in
            # line mode. Compare line and word modes using their OCR scores.
            reads=[self._read(image,mode,allowlist) for mode in (7,8)]
            return max(reads,key=lambda r: sum(float(x[2]) for x in r)/len(r) if r else -1)
        first=self._read(image,7,allowlist)
        if allowlist and not any(_normalize_epic_candidate(t) and float(c)>=.10 for _,t,c in first):
            second=self._read(image,8,allowlist)
            if any(_normalize_epic_candidate(t) and float(c)>=.10 for _,t,c in second):
                return second
        return first


class VoterLensEngine:
    def __init__(self, status_cb=None, log_cb=None, backend='easyocr', tessdata_dir=None):
        if backend not in ('easyocr','tesseract'):
            raise ValueError('Unsupported OCR backend')
        self.backend, self.tessdata_dir = backend, tessdata_dir
        self._status = status_cb or (lambda _s: None)
        self._log = log_cb or (lambda _s: None)
        self._reader = None
        self._reader_en = None
        # True when the source page carries enough native detail that the
        # Devanagari recogniser reads printed digits correctly. Set by
        # _render_matrix once the document is opened.
        self._hi_res = False
        # Card geometry for this document, learned from the first page that
        # detects cleanly and reused on pages that do not.
        self._layout = None
        self._reader_lock = threading.Lock()
        self._reader_en_lock = threading.Lock()
        self.last_all_records = []
        self.last_rejected_records = []
        self.last_stats = {}

    def _get_reader(self):
        with self._reader_lock:
            if self._reader is None:
                if self.backend == 'tesseract':
                    self._reader = TesseractReader('mar',self.tessdata_dir)
                    return self._reader
                if easyocr is None:
                    raise RuntimeError('Install EasyOCR: python -m pip install easyocr')
                self._status("Loading Marathi OCR model...")
                self._log(f"EasyOCR languages: {OCR_LANGS}; {'GPU (CUDA)' if USE_GPU else 'CPU'} mode")
                self._reader = easyocr.Reader(OCR_LANGS, gpu=USE_GPU)
                self._log("Devanagari model ready.")
        return self._reader

    def _get_reader_en(self):
        # EasyOCR binds ONE recognition network per Reader. A ["mr","en"] reader
        # uses the Devanagari network, which shreds Latin text: a real EPIC of
        # NYS6606669 came back as "|r 3680!556+" at 0.01 confidence. A separate
        # Latin-only reader is the only way to recover EPIC and ASCII digits.
        with self._reader_en_lock:
            if self._reader_en is None:
                if self.backend == 'tesseract':
                    self._reader_en = TesseractReader('eng',self.tessdata_dir)
                    return self._reader_en
                if easyocr is None:
                    raise RuntimeError('Install EasyOCR: python -m pip install easyocr')
                self._status("Loading English OCR model (EPIC recovery)...")
                self._reader_en = easyocr.Reader(["en"], gpu=USE_GPU)
                self._log("Latin model ready.")
        return self._reader_en

    @staticmethod
    def _readtext_marathi(reader: Any, image: Any) -> Any:
        """Call EasyOCR with explicit typed arguments so Pylance can validate them."""
        return reader.readtext(
            image,
            detail=1,
            paragraph=False,
            decoder="greedy",
            text_threshold=0.55,
            low_text=0.30,
            link_threshold=0.35,
            canvas_size=3000,
            mag_ratio=1.25,
            add_margin=0.12,
        )

    @staticmethod
    def _order(results: Any, thresh: float):
        """Join detections on the same printed line before parsing labels.

        Sorting by top-left Y alone placed a surname above its name label
        when the boxes differed by a few pixels. Preserve X order within rows.
        """
        tokens = []
        for item in results:
            if len(item) < 3:
                continue
            try:
                box, txt, confidence = item[0], str(item[1]).strip(), float(item[2])
                xs, ys = [float(p[0]) for p in box], [float(p[1]) for p in box]
            except (TypeError, ValueError):
                continue
            if txt and confidence >= thresh:
                tokens.append((min(xs), min(ys), max(ys), txt, confidence))
        rows = []
        for token in sorted(tokens, key=lambda t: ((t[1]+t[2])/2, t[0])):
            for row in reversed(rows):
                mid = float(np.median([(t[1]+t[2])/2 for t in row]))
                height = float(np.median([t[2]-t[1] for t in row]))
                if abs((token[1]+token[2])/2-mid) <= .45*max(height, token[2]-token[1]):
                    row.append(token)
                    break
            else:
                rows.append([token])
        rows.sort(key=lambda row: np.median([(t[1]+t[2])/2 for t in row]))
        text = '\n'.join(' '.join(t[3] for t in sorted(row, key=lambda t:t[0])) for row in rows)
        return text, sum(t[4] for t in tokens)/len(tokens) if tokens else 0.0

    def _ocr_card_two_pass(self, card):
        language = getattr(self, '_source_language', None)
        h, w = card.shape[:2]
        # Photo starts near 75% of card width in the observed template. The old
        # 58% crop removed surnames and long house addresses.
        body = card[int(h*.19):int(h*.96), int(w*.010):int(w*.745)]
        native_body=body
        body = cv2.resize(body, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        if language == 'en':
            text_en, conf = self._order(self._read_printed_lines(self._get_reader_en(), body), .10)
            text_mr = ''
        else:
            text_mr, conf = self._order(self._read_printed_lines(self._get_reader(), body), .10)
            text_en = ''
            if language is None:
                text_en, en_conf = self._order(self._read_printed_lines(self._get_reader_en(), body), .10)
                if VoterParser.looks_english(text_mr, text_en):
                    text_mr, conf = '', en_conf
        active_lang='en' if language=='en' or VoterParser.looks_english(text_mr,text_en) else 'mr'
        active_text=text_en if active_lang=='en' else text_mr
        if not any(VoterParser._label_fields(active_text,active_lang).get('relation',[])):
            # Retry only a failed labelled field with a different resampling.
            # Keep both attempts in raw text and surface conflicting readings.
            alternate=cv2.resize(native_body,None,fx=2,fy=2,interpolation=cv2.INTER_LINEAR)
            reader=self._get_reader_en() if active_lang=='en' else self._get_reader()
            retry,_=self._order(self._read_printed_lines(reader,alternate),.10)
            if any(VoterParser._label_fields(retry,active_lang).get('relation',[])):
                if active_lang=='en':
                    text_en += '\n'+BLOCK_EN_MARKER+'\n'+retry
                else:
                    text_mr += '\n'+BLOCK_MR_MARKER+'\n'+retry
        epic = self._ocr_epic_roi(card)
        serial = self._ocr_serial_roi(card)
        # The age and house rows get their own Latin-model reads: printed
        # ASCII digits and house numbers survive there but die in the
        # Devanagari whole-card pass. _parse_structured consumes the markers.
        age = self._ocr_age_roi(card)
        house = self._ocr_house_roi(card, exclude_age=age)
        markers = []
        if epic:
            markers.append(EPIC_MARKER + epic)
        if serial:
            markers.append(SERIAL_MARKER + serial)
        if age is not None:
            markers.append(AGE_MARKER + str(age))
        if house:
            markers.append(HOUSE_MARKER + house)
        return text_mr, '\n'.join(markers) + '\n' + text_en, conf

    @staticmethod
    def _split_merged_bands(groups_ink, groups):
        """Separate two printed rows that the projection merged into one band.

        Devanagari descenders and the next row's shirorekha can leave a gap
        that never reaches zero ink, so the name row and the relation row below
        it arrived at the recogniser as a single line: it returned one smeared
        string ("नाबिलां्ेसनानः शकील मुल्ला") carrying the first row's label and
        the second row's value, and both electors' names were lost. A band much
        taller than the card's own median band is cut at its deepest interior
        ink valley, which is the true inter-row gap.
        """
        ink = groups_ink
        if len(groups) < 2:
            return groups
        med = float(np.median([int(g[-1]) - int(g[0]) + 1 for g in groups]))
        if med <= 0:
            return groups

        def split(g):
            a, b = int(g[0]), int(g[-1])
            span = b - a + 1
            if span < med * 1.6:
                return [g]
            lo, hi = a + int(span * .25), a + int(span * .75)
            if hi - lo < 3:
                return [g]
            cut = lo + int(np.argmin(ink[lo:hi]))
            # A real row gap is near-empty. Anything busier is one tall line.
            if ink[cut] > .25 * float(np.mean(ink[a:b + 1])):
                return [g]
            left, right = g[g <= cut], g[g > cut]
            if len(left) < 6 or len(right) < 6:
                return [g]
            return split(left) + split(right)

        return [part for g in groups for part in split(g)]

    @staticmethod
    def _read_printed_lines(reader, gray):
        """Recognize complete printed lines instead of reordering word boxes.

        Projection uses the actual ink bands, so wrapped field values are kept
        and no assumption of four equally spaced field rows is necessary.
        """
        if isinstance(reader,TesseractReader):
            return reader.readtext(gray)
        h, w = gray.shape[:2]
        ink = (gray < 190).sum(axis=1)
        ys = np.flatnonzero(ink >= max(3, int(w*.008)))
        groups = np.split(ys, np.where(np.diff(ys) > 2)[0] + 1) if len(ys) else []
        groups = VoterLensEngine._split_merged_bands(ink, [g for g in groups if len(g) >= 6])
        bands=[]
        for g in groups:
            if len(g)<6:
                continue
            top,bottom=max(0,int(g[0])-3),min(h,int(g[-1])+4)
            xs=np.flatnonzero((gray[top:bottom]<190).sum(axis=0)>1)
            if len(xs):
                bands.append([max(0,int(xs[0])-4),min(w,int(xs[-1])+5),top,bottom])
        if not bands or len(bands)>8:
            return reader.readtext(gray,detail=1,paragraph=False)
        return reader.recognize(gray,horizontal_list=bands,free_list=[],
                                detail=1,paragraph=False,batch_size=1)

    @staticmethod
    def _clean_identifier_roi(roi):
        """Remove the printed box rules before single-line recognition."""
        _, ink = cv2.threshold(roi, 190, 255, cv2.THRESH_BINARY_INV)
        h,w = ink.shape
        hz = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1,max(15,int(w*.65))),np.uint8))
        vt = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((max(25,int(h*.85)),1),np.uint8))
        rules = cv2.dilate(cv2.bitwise_or(hz,vt), np.ones((3,3),np.uint8))
        clean = roi.copy()
        clean[rules>0] = 255
        # Faint pieces of the box can survive line removal. Bound the crop by
        # character-sized components, not isolated border pixels.
        _,labels,stats,_=cv2.connectedComponentsWithStats((clean<180).astype(np.uint8),connectivity=8)
        chars=[(x,y,cw,ch) for x,y,cw,ch,area in stats[1:]
               if max(5,h*.20)<=ch<=h*.85 and max(2,ch*.10)<=cw<=ch*2.5 and area>=max(8,ch*1.2)]
        if chars:
            x=min(b[0] for b in chars); y=min(b[1] for b in chars)
            right=max(b[0]+b[2] for b in chars); bottom=max(b[1]+b[3] for b in chars)
            clean=clean[y:bottom,x:right]
        return cv2.copyMakeBorder(clean,10,10,10,10,cv2.BORDER_CONSTANT,value=255)

    _HOUSE_TOKEN = re.compile(r"\d{1,4}\s?[-/]?\s?[A-Za-zऀ-ॿ]?")

    def _render_matrix(self, doc):
        """Choose a render scale from the page's own geometry.

        A fixed DPI is wrong for these files. Page boxes differ wildly: one roll
        uses a 595x842 box holding a 949x1343 image, another uses a 1983x2806
        box holding a 1983x2806 image. Rendering the second at 300 DPI would
        produce an 8262px-wide page, many times its real detail, costing minutes
        per page for nothing. Targeting a pixel width instead keeps every file
        at a sensible, comparable working size.
        """
        try:
            page = doc[0]
            width_pt = float(page.rect.width) or 595.0
            native = 0
            # Cover pages often carry only a small logo image; sampling the
            # first pages avoids mistaking that for the roll's real detail.
            for pno in range(min(3, doc.page_count)):
                for img in doc[pno].get_images(full=True):
                    try:
                        native = max(native, int(doc.extract_image(img[0])["width"]))
                    except Exception:
                        continue
            # Render at the page's own resolution when it carries enough
            # detail, and only fall back to upscaling when it does not.
            # Measured both ways: a roll whose image is 1983px wide loses
            # accuracy when pushed to 2600 (names truncate, ages flip), while a
            # roll whose image is only 949px needs the upscale. Interpolating
            # past the detail that exists makes the recogniser worse, not better.
            dpi_px = width_pt * OCR_DPI / 72.0
            if native >= NATIVE_PX_SUFFICIENT:
                target = native
                self._hi_res = True
            else:
                target = min(dpi_px, RENDER_TARGET_PX)
                self._hi_res = False
            scale = target / width_pt
            self._log(f"Render: page {width_pt:.0f}pt, native {native or '?'}px "
                      f"-> {target}px (scale {scale:.2f})")
            return fitz.Matrix(scale, scale)
        except Exception:
            return fitz.Matrix(OCR_DPI / 72.0, OCR_DPI / 72.0)

    def _ocr_serial_roi(self, card):
        h,w = card.shape[:2]
        # The serial cell widens for longer numbers. Find its printed outline
        # instead of clipping its rightmost digit at a fixed X percentage.
        header = card[:int(h*.23),:int(w*.42)]
        _,bw = cv2.threshold(header,180,255,cv2.THRESH_BINARY_INV)
        contours,_ = cv2.findContours(bw,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        cells = [(x,y,cw,ch) for x,y,cw,ch in (cv2.boundingRect(c) for c in contours)
                 if .23*w<=cw<=.40*w and .07*h<=ch<=.22*h and x<.08*w]
        if cells:
            x,y,cw,ch = max(cells,key=lambda b:b[2]*b[3])
            inset=max(2,int(h*.008))
            roi=header[y+inset:y+ch-inset,x+inset:x+cw-inset]
        else:
            roi=card[:int(h*.20),:int(w*.38)]
        if roi.size == 0:
            return None
        roi = cv2.copyMakeBorder(cv2.resize(roi,None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC),8,8,8,8,cv2.BORDER_CONSTANT,value=255)
        roi = self._clean_identifier_roi(roi)
        results = self._get_reader_en().recognize(roi,detail=1,paragraph=False,allowlist='0123456789')
        tokens = [str(t).strip() for _,t,c in results if float(c)>=.15 and re.fullmatch(r'[0-9]{1,5}',str(t).strip())]
        return tokens[0] if len(tokens)==1 else None

    def _ocr_age_roi(self, card):
        """Read the age off the वय row with the Latin model.

        Ages are printed in ASCII. The Devanagari model transliterates them and
        gets them wrong, turning 33 into २३ and 28 into २३. Restricting the
        read to the row, with a digits-only allowlist, recovers the printed
        value. The वय label itself comes back as "7:" or "44", so the digits
        are taken from after the separator.
        """
        try:
            h, w = card.shape[:2]
            if h < 20 or w < 20:
                return None
            roi = card[int(h * 0.55):int(h * 0.78), 0:int(w * 0.55)]
            if roi.size == 0:
                return None
            roi = cv2.resize(roi, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
            best, best_conf = None, 0.0
            for _b, txt, cf in self._get_reader_en().readtext(
                    roi, detail=1, paragraph=False, allowlist="0123456789: "):
                conf = float(cf)
                s = str(txt)
                if ":" not in s or conf < 0.25:
                    continue
                tail = s.split(":")[-1].strip()
                # fullmatch, not match: the age row must not borrow the
                # first two digits of a 3-digit house number that OCR
                # merged into the same line.
                m = re.fullmatch(r"(\d{2,3})", tail)
                if not m:
                    continue
                age = int(m.group(1))
                if MIN_AGE <= age <= MAX_AGE and conf > best_conf:
                    best, best_conf = age, conf
            return best
        except Exception:
            return None

    def _ocr_house_roi(self, card, exclude_age=None):
        """Read the घर क्रमांक row alone with the Latin model.

        House numbers are printed in ASCII (623a, 623b) and the Devanagari
        model turns them into letters such as GSH. Scanning the whole card's
        Latin text instead pulled numeric-looking noise out of the photo box
        on the right and invented house numbers for cards that have none, so
        the read is confined to the row itself.
        """
        try:
            h, w = card.shape[:2]
            if h < 20 or w < 20:
                return ""
            roi = card[int(h * 0.42):int(h * 0.66), 0:int(w * 0.58)]
            if roi.size == 0:
                return ""
            roi = cv2.resize(roi, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
            best, best_conf = "", 0.0
            for _b, txt, cf in self._get_reader_en().readtext(
                    roi, detail=1, paragraph=False):
                conf = float(cf)
                if conf < 0.10:
                    continue
                tail = re.split(r"[:;]", str(txt))[-1].strip()
                m = self._HOUSE_TOKEN.search(tail)
                if not m:
                    continue
                tok = m.group(0).strip()
                digits = re.sub(r"\D", "", tok)
                # The age row overlaps this ROI on some templates; never
                # let the printed age become a house number.
                if exclude_age is not None and digits == str(exclude_age):
                    continue
                # One-digit houses exist; they need a higher confidence
                # than multi-digit reads to be trusted.
                if digits and (2 <= len(digits) <= 4
                               or (len(digits) == 1 and conf >= 0.30)) and conf > best_conf:
                    best, best_conf = tok, conf
            return best
        except Exception:
            return ""

    _EPIC_ALLOWLIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

    def _ocr_epic_roi(self, card):
        h,w = card.shape[:2]
        roi = card[:int(h*.19), int(w*.50):]
        if roi.size == 0:
            return ''
        roi = cv2.copyMakeBorder(cv2.resize(roi,None,fx=2,fy=2,interpolation=cv2.INTER_CUBIC),8,8,8,8,cv2.BORDER_CONSTANT,value=255)
        roi = self._clean_identifier_roi(roi)
        results = self._get_reader_en().recognize(roi,detail=1,paragraph=False,allowlist=self._EPIC_ALLOWLIST)
        return ' '.join(str(t).strip() for _,t,c in results if float(c)>=.10)

    def process_pdf(self, pdf_path, progress_cb=None, cancel_ev=None):
        cancel_ev = cancel_ev or threading.Event()
        self._layout = None  # A GUI engine is reused between different files.
        filename = os.path.basename(pdf_path).upper()
        # Separators vary between files: -ENG-, _ENG., " ENG ". Match with
        # boundaries so ordinary words never trigger a language lock.
        self._source_language = (
            'en' if re.search(r'(?:^|[-_.\s])(?:ENG|EN)(?:[-_.\s]|$)', filename) else
            'mr' if re.search(r'(?:^|[-_.\s])(?:MAR|MR)(?:[-_.\s]|$)', filename) else None)
        records, page_counts = [], []
        debug_dir = _safe_mkdir(os.path.join(os.path.dirname(os.path.abspath(pdf_path)), 'VoterLens_Debug')) if DEBUG_DUMP else None
        with fitz.open(pdf_path) as doc:
            matrix = self._render_matrix(doc)
            for pidx in range(len(doc)):
                page = doc[pidx]
                if cancel_ev.is_set():
                    raise RuntimeError('Cancelled. Previous output was not replaced.')
                self._status(f'Reading page {pidx+1}/{len(doc)}...')
                pix = page.get_pixmap(matrix=matrix, colorspace=fitz.csGRAY, alpha=False)
                gray = np.frombuffer(pix.samples,dtype=np.uint8).copy().reshape(pix.height,pix.width)
                cards, boxes, method = CardSegmenter.segment(gray)
                if debug_dir:
                    _safe_write(os.path.join(debug_dir,'segmentation',f'page_{pidx+1:04d}.jpg'),
                                CardSegmenter.debug_image(gray,boxes,method),self._log,image=True)
                page_counts.append(len(cards))
                self._log(f'Page {pidx+1}: {len(cards)} observed card(s)')
                for cidx, card in enumerate(cards,1):
                    if cancel_ev.is_set():
                        raise RuntimeError('Cancelled. Previous output was not replaced.')
                    text, text_en, conf = self._ocr_card_two_pass(card)
                    voter = VoterParser.parse_auto(text,pidx+1,cidx,conf,text_en)
                    if debug_dir:
                        _safe_write(os.path.join(debug_dir,'raw_ocr',f'p{pidx+1:04d}_c{cidx:02d}.txt'),
                                    text+'\n--- EN PASS ---\n'+text_en,self._log)
                    voter.update(segmentation_method=method,has_ocr_text=bool((text+text_en).strip()))
                    # Retain every real card even if one field fails OCR.
                    records.append(voter)
                if progress_cb:
                    progress_cb(int((pidx+1)/len(doc)*100))
            self._finish_records(records, len(doc), page_counts)
        return records, debug_dir

    def _finish_records(self, records, pages, page_counts):
        self._repair_serials(records)
        by_epic = collections.defaultdict(list)
        for row in records:
            if row.get('epic_no'):
                by_epic[row['epic_no']].append(row)
        for group in by_epic.values():
            if len(group)>1:
                for row in group:
                    row['epic_status']='duplicate'
                    row['review_reason']+='; duplicate_epic_review_source'
                    VoterParser.assess(row)
        serials = [int(r['serial_no']) for r in records if str(r.get('serial_no') or '').isdigit()]
        gaps = sorted(set(range(min(serials),max(serials)+1))-set(serials)) if serials and max(serials)-min(serials)<100000 else []
        self.last_all_records = [dict(r) for r in records]
        self.last_rejected_records = [dict(r) for r in records if r['parse_status']=='needs_review']
        self.last_stats = dict(pages=pages,segmented_cards=len(records),valid_voters=len(records),
                               parsed_without_flags=len(records)-len(self.last_rejected_records),
                               needs_review=len(self.last_rejected_records),
                               partial_or_rejected=0,duplicate_epics=sum(len(g)-1 for g in by_epic.values() if len(g)>1),
                               page_card_counts=', '.join(f'{i+1}:{n}' for i,n in enumerate(page_counts)),
                               missing_serials=', '.join(map(str,gaps[:500])) + (f' ... ({len(gaps)} gaps)' if len(gaps)>500 else ''),
                               serial_gap_count=len(gaps),
                               zero_card_pages=', '.join(str(i+1) for i,n in enumerate(page_counts) if not n),
                               verification='OCR output; review flags and reconcile against source summary')
        self._log(f'{len(records)} extracted; {len(self.last_rejected_records)} need review; {len(gaps)} serial gap(s)')

    def _normalize_epic_prefixes(self, records):
        # Frequency cannot prove an individual's EPIC. Preserve source reads.
        return records

    def _repair_serials(self, records):
        """Flag sequence problems. Never fill or overwrite a printed identifier."""
        counts = collections.Counter(str(r.get('serial_no')) for r in records if r.get('serial_no'))
        previous = None
        for row in records:
            row['review_reason']='; '.join(x for x in (row.get('review_reason') or '').split('; ')
                                           if x and x!='serial_sequence_review_source')
            value = row.get('serial_no')
            if not value or not str(value).isdigit():
                row['serial_status']='missing'
            else:
                number=int(value)
                issue=counts[str(value)]>1 or (previous is not None and number!=previous+1)
                row['serial_status']='check' if issue else 'read'
                if issue:
                    row['review_reason']=(row.get('review_reason') or '')+'; serial_sequence_review_source'
                previous=number
            VoterParser.assess(row)
        return records

    def _drop_non_voter_pages(self, records):
        # Page classification is geometric; low OCR recovery is not a reason
        # to erase an observed voter card or a one-card page.
        return records

    def process_image(self, path, progress_cb=None, cancel_ev=None):
        cancel_ev=cancel_ev or threading.Event()
        self._layout=None
        self._source_language=None
        gray=cv2.imread(path,cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise ValueError(f'Cannot read image: {path}')
        cards,boxes,method=CardSegmenter.segment(gray)
        records=[]
        for i,card in enumerate(cards,1):
            if cancel_ev.is_set():
                raise RuntimeError('Cancelled. Previous output was not replaced.')
            text,text_en,conf=self._ocr_card_two_pass(card)
            row=VoterParser.parse_auto(text,1,i,conf,text_en)
            row.update(segmentation_method=method,has_ocr_text=bool(text or text_en))
            records.append(row)
            if progress_cb:
                progress_cb(int(i/max(1,len(cards))*100))
        self._finish_records(records,1,[len(cards)])
        return records,None

    def process_file(self, path, progress_cb=None, cancel_ev=None):
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        ext = os.path.splitext(path)[1].lower()
        if ext == ".pdf":
            return self.process_pdf(path, progress_cb, cancel_ev)
        if ext in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}:
            return self.process_image(path, progress_cb, cancel_ev)
        raise ValueError("Select a PDF or supported image file.")


# ----------------------------- OUTPUT --------------------------------

class OutputManager:
    COLS = [
        "page", "card", "serial_no", "serial_status", "epic_no", "epic_status", "name", "name_marathi",
        "father_husband_name", "father_husband_name_marathi", "house_no",
        "age", "gender", "language", "ocr_confidence", "parse_status", "has_ocr_text",
        "segmentation_method", "raw_text", "raw_text_en", "house_status", "review_reason"
    ]

    @staticmethod
    def _epic_status(epic):
        """Flag EPICs that do not match the ECI format of 3 letters + 7 digits.

        Filter this column to "check" in Excel to review only the doubtful
        numbers instead of scanning the whole sheet.
        """
        if not epic:
            return "missing"
        return "format_ok" if re.fullmatch(r"[A-Z]{3}\d{7}", str(epic)) else "check"

    @classmethod
    def _frame(cls, rows):
        if rows:
            df = pd.DataFrame(rows)
        else:
            df = pd.DataFrame(columns=cls.COLS)
        ordered = [c for c in cls.COLS if c in df.columns]
        extras = [c for c in df.columns if c not in ordered]
        return df.reindex(columns=ordered + extras)

    @staticmethod
    def _format_openpyxl(ws, df):
        try:
            for i, col in enumerate(df.columns, 1):
                longest = df[col].fillna("").astype(str).str.len().max()
                longest = 0 if longest is None or pd.isna(longest) else int(longest)
                ws.column_dimensions[_col_letter(i)].width = min(60, max(len(str(col)), longest) + 2)
            ws.freeze_panes = "A2"
            if ws.max_row >= 1 and ws.max_column >= 1:
                ws.auto_filter.ref = ws.dimensions
        except Exception:
            # Formatting must never destroy an otherwise valid Excel export.
            pass

    @classmethod
    def save(cls, records, source_path, all_records=None, rejected_records=None, stats=None):
        all_records = all_records if all_records is not None else records
        rejected_records = rejected_records or []
        stats = stats or {}
        if not records or not any(r.get('name') or r.get('name_marathi') or r.get('epic_no') for r in records):
            raise RuntimeError('No voter cards extracted. Existing output was not replaced. Check the scan/layout.')

        out_dir = _safe_mkdir(os.path.join(os.path.dirname(os.path.abspath(source_path)), "VoterLens_Output"))
        stem = os.path.splitext(os.path.basename(source_path))[0]

        if SINGLE_FILE_OUTPUT:
            # Fixed name, overwritten each run. A timestamped base left four new
            # files behind on every run, so the folder filled with near-identical
            # exports and it was unclear which one was current.
            base = os.path.join(out_dir, f"{stem}_VoterLens")
            if CLEAN_OLD_OUTPUTS:
                for old in glob.glob(os.path.join(out_dir, f"{stem}_VoterLens_*")):
                    try:
                        os.remove(old)
                    except OSError:
                        pass
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            base = os.path.join(out_dir, f"{stem}_VoterLens_{ts}")

        for r in records:
            r.setdefault("epic_status", cls._epic_status(r.get("epic_no")))

        df = cls._frame(records)
        all_df = cls._frame(all_records)
        rejected_df = cls._frame(rejected_records)

        csv_path = base + ".csv"
        all_csv_path = base + "_ALL_OCR_CARDS.csv"
        xlsx_path = base + ".xlsx"
        json_path = base + ".json"

        # Side files are audit artifacts. In single-file mode the Excel workbook
        # is the deliverable and these are skipped.
        if not SINGLE_FILE_OUTPUT:
            df.to_csv(csv_path, index=False, encoding="utf-8-sig")
            all_df.to_csv(all_csv_path, index=False, encoding="utf-8-sig")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
        else:
            csv_path = all_csv_path = json_path = None

        summary_rows = [
            {"metric": "Source file", "value": os.path.abspath(source_path)},
            {"metric": "Extracted voters", "value": len(df)},
            {"metric": "All segmented/OCR cards", "value": len(all_df)},
            {"metric": "Rows requiring review (retained in Voters)", "value": len(rejected_df)},
        ]
        for k, v in stats.items():
            summary_rows.append({"metric": str(k), "value": v})
        summary_df = pd.DataFrame(summary_rows)

        # openpyxl is the single Excel backend for this app. Avoid an optional
        # xlsxwriter import so VS Code/Pylance does not report a missing module.
        if importlib.util.find_spec("openpyxl") is None:
            raise RuntimeError(
                "Excel writer is not installed. Run: py -m pip install openpyxl"
            )
        engine = "openpyxl"

        tmp_xlsx = xlsx_path + ".tmp.xlsx"
        if os.path.exists(tmp_xlsx):
            os.remove(tmp_xlsx)

        with pd.ExcelWriter(tmp_xlsx, engine=engine) as writer:
            df.to_excel(writer, index=False, sheet_name="Voters")
            if INCLUDE_AUDIT_SHEETS:
                all_df.to_excel(writer, index=False, sheet_name="All_OCR_Cards")
                rejected_df.to_excel(writer, index=False, sheet_name="Needs_Review")
            summary_df.to_excel(writer, index=False, sheet_name="Summary")

            cls._format_openpyxl(writer.sheets["Voters"], df)
            if INCLUDE_AUDIT_SHEETS:
                cls._format_openpyxl(writer.sheets["All_OCR_Cards"], all_df)
                cls._format_openpyxl(writer.sheets["Needs_Review"], rejected_df)
            cls._format_openpyxl(writer.sheets["Summary"], summary_df)

        os.replace(tmp_xlsx, xlsx_path)
        if not os.path.exists(xlsx_path) or os.path.getsize(xlsx_path) <= 0:
            raise RuntimeError(f"Excel export verification failed: {xlsx_path}")

        return {
            "count": len(df), "all_count": len(all_df), "rejected_count": len(rejected_df),
            "csv": csv_path, "all_csv": all_csv_path, "xlsx": xlsx_path,
            "json": json_path, "output_dir": out_dir,
        }


# ------------------------------- GUI ---------------------------------

class VoterLensApp:
    def __init__(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.root = ctk.CTk()
        self.root.title("VoterLens v5.3 — Maharashtra Electoral Roll OCR")
        self.root.geometry("980x760")

        self.engine = None
        self.engine_lock = threading.Lock()
        self.queue = _queue.Queue()
        self.cancel_ev = threading.Event()
        self.busy = False

        self._build()
        self.root.after(100, self._poll)

    def _build(self):
        ctk.CTkLabel(self.root, text="VOTERLENS v5.3",
                     font=ctk.CTkFont(size=34, weight="bold")).pack(pady=(18, 2))
        ctk.CTkLabel(self.root,
                     text="Maharashtra Voter List OCR • Marathi + English • Debuggable Extraction",
                     font=ctk.CTkFont(size=14)).pack(pady=(0, 15))

        pf = ctk.CTkFrame(self.root)
        pf.pack(fill="x", padx=40, pady=5)
        self.progress = ctk.CTkProgressBar(pf)
        self.progress.pack(fill="x", padx=20, pady=(15, 8))
        self.progress.set(0)
        self.status = ctk.CTkLabel(pf, text="Ready — select PDF / image")
        self.status.pack(pady=(0, 12))

        bf = ctk.CTkFrame(self.root, fg_color="transparent")
        bf.pack(pady=10)
        self.open_btn = ctk.CTkButton(bf, text="Select Voter List PDF / Image",
                                      width=310, height=50, command=self._start)
        self.open_btn.pack(side="left", padx=8)
        self.cancel_btn = ctk.CTkButton(bf, text="Cancel", width=140, height=50,
                                        command=self._cancel, state="disabled", fg_color="gray40")
        self.cancel_btn.pack(side="left", padx=8)

        info = (
            "Reads observed voter cards. Partial fields stay visible in Voters and Needs_Review. "
            "OCR spelling must be checked against the source; identifiers are never guessed."
        )
        ctk.CTkLabel(self.root, text=info, wraplength=880, text_color="gray75").pack(pady=(0, 8))

        lf = ctk.CTkFrame(self.root)
        lf.pack(fill="both", expand=True, padx=40, pady=10)
        self.log = ctk.CTkTextbox(lf, font=ctk.CTkFont(size=11))
        self.log.pack(fill="both", expand=True, padx=10, pady=10)

    def _set_busy(self, value):
        self.busy = value
        self.open_btn.configure(state="disabled" if value else "normal")
        self.cancel_btn.configure(state="normal" if value else "disabled")

    def _cancel(self):
        self.cancel_ev.set()
        self.queue.put(("status", "Cancelling..."))

    def _start(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(
            title="Select electoral roll PDF / image",
            filetypes=[
                ("PDF", "*.pdf"),
                ("Images", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                ("All files", "*.*"),
            ]
        )
        if not path:
            return

        self.cancel_ev.clear()
        self._set_busy(True)
        self.progress.set(0)
        self.log.delete("1.0", "end")
        self.queue.put(("log", f"Selected: {path}"))

        def work():
            try:
                with self.engine_lock:
                    if self.engine is None:
                        self.engine = VoterLensEngine(
                            status_cb=lambda s: self.queue.put(("status", s)),
                            log_cb=lambda s: self.queue.put(("log", s)),
                        )
                records, debug_dir = self.engine.process_file(
                    path,
                    progress_cb=lambda v: self.queue.put(("progress", v)),
                    cancel_ev=self.cancel_ev,
                )
                self.queue.put(("log", f"Extracted voter rows: {len(records)}"))
                self.queue.put(("log", f"All segmented/OCR cards: {len(self.engine.last_all_records)}"))
                self.queue.put(("status", "Writing Excel / CSV / JSON..."))
                result = OutputManager.save(
                    records, path,
                    all_records=self.engine.last_all_records,
                    rejected_records=self.engine.last_rejected_records,
                    stats=self.engine.last_stats,
                )
                self.queue.put(("log", f"Excel saved: {result['xlsx']}"))
                self.queue.put(("done", result, debug_dir))
            except Exception as e:
                self.queue.put(("log", traceback.format_exc()))
                self.queue.put(("error", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                typ = msg[0]
                if typ == "status":
                    self.status.configure(text=msg[1])
                elif typ == "progress":
                    self.progress.set(msg[1] / 100)
                elif typ == "log":
                    self.log.insert("end", msg[1] + "\n")
                    line_count = int(self.log.index("end-1c").split(".")[0])
                    if line_count > MAX_LOG_LINES:
                        self.log.delete("1.0", "150.0")
                    self.log.see("end")
                elif typ == "done":
                    self._set_busy(False)
                    self.progress.set(1)
                    result, debug_dir = msg[1], msg[2]
                    self.status.configure(text=f"Done — {result['count']} voters")
                    messagebox.showinfo(
                        "Complete",
                        f"Extracted voters: {result['count']}\n"
                        f"All OCR cards: {result['all_count']}\n"
                        f"Retained rows needing review: {result['rejected_count']}\n\n"
                        f"Excel: {result['xlsx']}\n"
                        + (f"All-cards CSV: {result['all_csv']}\n"
                           if result.get('all_csv') else "")
                        + f"Output folder: {result['output_dir']}\n\n"
                        + (f"Debug: {debug_dir}" if debug_dir
                           else "Debug output: off (DEBUG_DUMP = False)")
                    )
                elif typ == "error":
                    self._set_busy(False)
                    self.status.configure(text="Error")
                    self.log.insert("end", "ERROR: " + msg[1] + "\n")
                    messagebox.showerror("Error", msg[1])
        except _queue.Empty:
            pass
        self.root.after(100, self._poll)

    def run(self):
        self.root.mainloop()


def merge_companion_rows(primary, companion):
    """Match supplied language editions by unique EPIC, with serial checks.

    Never join by row number or similar names. Keep source disagreements for
    review. English columns remain empty for a Marathi-only input by design.
    """
    lookup=collections.defaultdict(list)
    primary_counts=collections.Counter(row.get('epic_no') for row in primary if row.get('epic_no'))
    for row in companion:
        if row.get('epic_no'):
            lookup[row['epic_no']].append(row)
    for row in primary:
        candidates=lookup.get(row.get('epic_no'),[])
        row['companion_status']='unmatched'
        if len(candidates)!=1 or primary_counts.get(row.get('epic_no'),0)!=1:
            row['review_reason']=(row.get('review_reason') or '')+'; companion_identity_unmatched'
            VoterParser.assess(row)
            continue
        other=candidates[0]
        if row.get('serial_no') and other.get('serial_no') and row['serial_no']!=other['serial_no']:
            row['companion_status']='serial_conflict'
            row['review_reason']=(row.get('review_reason') or '')+'; companion_serial_conflict'
            VoterParser.assess(row)
            continue
        row['companion_status']='matched_epic'
        notes=[]
        for field in ('serial_no','age','gender'):
            if row.get(field) in (None,'') and other.get(field) not in (None,''):
                row[field]=other[field]
                notes.append(field+' from companion PDF')
            elif row.get(field) not in (None,'') and other.get(field) not in (None,'') and row[field]!=other[field]:
                row['review_reason']=(row.get('review_reason') or '')+'; companion_'+field+'_conflict'
        for field in ('name','name_marathi','father_husband_name','father_husband_name_marathi'):
            if not row.get(field) and other.get(field):
                row[field]=other[field]
        if row.get('language')=='mr' and other.get('language')=='en':
            row['house_no_english']=other.get('house_no')
            row['raw_header']=row.get('raw_text_en','')
            row['raw_text_en']=other.get('raw_text_en','')
        row['source_note']='; '.join(notes)
        VoterParser.assess(row)
    return primary


def main():
    parser=argparse.ArgumentParser(description='VoterLens v5.3: local Marathi/English roll extraction')
    parser.add_argument('source',nargs='?',help='PDF/image; omit to open the existing desktop UI')
    parser.add_argument('--backend',choices=['easyocr','tesseract'],default='easyocr')
    parser.add_argument('--tessdata-dir',help='Folder containing mar.traineddata and eng.traineddata')
    parser.add_argument('--json',dest='json_path',help='Write extraction JSON instead of Excel')
    parser.add_argument('--expected-total',type=int,help='Printed source total; a mismatch exits with an error')
    parser.add_argument('--companion',help='Matching language-edition PDF; join only by unique EPIC with serial checks')
    args=parser.parse_args()
    if not args.source:
        VoterLensApp().run()
        return
    engine=VoterLensEngine(log_cb=print,backend=args.backend,tessdata_dir=args.tessdata_dir)
    rows,_=engine.process_file(args.source)
    if args.companion:
        companion=VoterLensEngine(log_cb=print,backend=args.backend,tessdata_dir=args.tessdata_dir)
        other,_=companion.process_file(args.companion)
        rows=merge_companion_rows(rows,other)
        pages=int(engine.last_stats['pages'])
        engine._finish_records(rows,pages,[sum(r['page']==i for r in rows) for i in range(1,pages+1)])
        engine.last_stats['companion_file']=os.path.basename(args.companion)
    if args.expected_total is not None and len(rows)!=args.expected_total:
        raise RuntimeError(f'Source total mismatch: expected {args.expected_total}, extracted {len(rows)}. Output not replaced.')
    if args.json_path:
        destination=os.path.abspath(args.json_path)
        os.makedirs(os.path.dirname(destination),exist_ok=True)
        with open(destination+'.tmp','w',encoding='utf-8') as stream:
            json.dump({'records':rows,'stats':engine.last_stats},stream,ensure_ascii=False,indent=2)
        os.replace(destination+'.tmp',destination)
    else:
        result=OutputManager.save(rows,args.source,engine.last_all_records,
                                  engine.last_rejected_records,engine.last_stats)
        print('Saved:',result['xlsx'])


if __name__ == '__main__':
    main()
