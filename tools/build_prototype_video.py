"""Build the PDF Q&A prototype / technology video from real screenshots.

    python tools/build_prototype_video.py

Inputs (all real, captured from the running app):
  brag-output/work/shots_app/*.png     Playwright MCP screenshots of the live app
  brag-output/work/audio/sceneNN.wav   narration (female voice, English)
  brag-output/work/repos/brag/...      brag music (CC BY 4.0) + Kenney SFX

Output:
  brag-output/prototype-tech-video.mp4 (+ .jpg poster, .srt)

Creative rules follow latent-spaces/brag (storyboard, cuts on the beat grid,
show the real product) and Moh4696/cinematic-skill (one hero per line, readable
type, captions). Subtitle chunking is punctuation-aware in the OmniVoice style.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import imageio_ffmpeg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def P(*a): return os.path.join(ROOT, *a)

SHOTS = P("brag-output", "work", "shots_app")
WORK = P("brag-output", "work", "video")
AUDIO = P("brag-output", "work", "audio")
NARR = P("tools", "prototype-narration.json")
BRAG = P("brag-output", "work", "repos", "brag", "skills", "brag", "assets")
MUSIC = os.path.join(BRAG, "music", "happy-beats-business-moves-vol-1-by-ende-dot-app.mp3")
OUT = P("brag-output", "prototype-tech-video.mp4")
POSTER = P("brag-output", "prototype-tech-video.jpg")
SRT = P("brag-output", "prototype-tech-video.srt")

W, H, FPS, SR = 1920, 1080, 30, 44100
FF = imageio_ffmpeg.get_ffmpeg_exe()
os.makedirs(WORK, exist_ok=True)

# ---------------------------------------------------------------- palette
BG1, BG2 = (9, 13, 26), (16, 24, 48)
ACC, ACC2, TXT, MUT, LINE = (125, 162, 255), (165, 139, 255), (238, 241, 248), (169, 182, 206), (43, 60, 102)
OK, WARN, RUST = (61, 217, 160), (255, 180, 84), (255, 107, 107)

FD = "/usr/share/fonts/truetype/dejavu/"
def font(size, bold=False, mono=False):
    if mono:
        name = "DejaVuSansMono-Bold.ttf" if bold else "DejaVuSansMono.ttf"
    else:
        name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(FD + name, size)

F_KICK = font(27, True)
F_TITLE = font(52, True)
F_SUB = font(33)
F_BODY = font(30)
F_SMALL = font(24)
F_BIG = font(88, True)
F_CHIP = font(23, True)
F_MONO = font(30, True)
F_MONO_S = font(24, True)
F_REPO = font(30, True)
F_REPO_B = font(22)
F_REPO_S = font(19)

LEAD, TAIL = 0.55, 0.85          # pause before / after every narration line
BEAT = 0.5                        # 120 BPM music grid


# ---------------------------------------------------------------- helpers
def gradient_bg():
    y = np.linspace(0, 1, H)[:, None, None]
    arr = (np.array(BG1) * (1 - y) + np.array(BG2) * y).repeat(W, axis=1)
    img = Image.fromarray(arr.astype(np.uint8), "RGB")
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse((W - 1000, -600, W + 500, 520), fill=60)
    glow = glow.filter(ImageFilter.GaussianBlur(200))
    img = Image.composite(Image.new("RGB", (W, H), (58, 70, 158)), img, glow)
    d = ImageDraw.Draw(img)
    for x in range(0, W, 96):
        d.line((x, 0, x, H), fill=(255, 255, 255, 8), width=1)
    for yy in range(0, H, 96):
        d.line((0, yy, W, yy), fill=(255, 255, 255, 8), width=1)
    d.text((W - 60, 44), "PDF Q&A", font=F_SMALL, fill=(90, 108, 150), anchor="ra")
    return img


BG = gradient_bg()


def header(img, kicker, title):
    d = ImageDraw.Draw(img)
    d.text((96, 50), kicker.upper(), font=F_KICK, fill=ACC)
    d.text((96, 88), title, font=F_TITLE, fill=TXT)


def wrap(text, fnt, width, draw):
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if draw.textlength(t, font=fnt) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = w_
    if cur:
        lines.append(cur)
    return lines


def card_rgba(path, max_w, max_h, scale=1.0):
    im = Image.open(path).convert("RGB")
    r = min(max_w / im.width, max_h / im.height) * scale
    im = im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))), Image.LANCZOS)
    pad = 34
    out = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("L", out.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle((pad, pad + 16, pad + im.width, pad + im.height + 16), 26, fill=170)
    out.putalpha(sh.filter(ImageFilter.GaussianBlur(22)))
    out = Image.composite(Image.new("RGBA", out.size, (0, 0, 0, 255)),
                          Image.new("RGBA", out.size, (0, 0, 0, 0)), out.getchannel("A"))
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, im.width - 1, im.height - 1), 20, fill=255)
    out.paste(im, (pad, pad), mask)
    ImageDraw.Draw(out).rounded_rectangle((pad, pad, pad + im.width - 1, pad + im.height - 1), 20, outline=LINE, width=2)
    return out


def paste_center(img, card, cx, cy, alpha=1.0):
    c = card
    if alpha < 1.0:
        c = card.copy()
        c.putalpha(c.getchannel("A").point(lambda v: int(v * alpha)))
    img.paste(c, (int(cx - c.width / 2), int(cy - c.height / 2)), c)


def zoom_crop(img, z, cx=0.5, cy=0.5):
    cw, ch = int(W / z), int(H / z)
    x = int((W - cw) * cx)
    y = int((H - ch) * cy)
    return img.crop((x, y, x + cw, y + ch)).resize((W, H), Image.BILINEAR)


def arrow(d, x0, y0, x1, y1, col=ACC, w=5):
    d.line((x0, y0, x1, y1), fill=col, width=w)
    ang = math.atan2(y1 - y0, x1 - x0)
    for s in (-1, 1):
        a = ang + math.pi + s * 0.42
        d.line((x1, y1, x1 + 20 * math.cos(a), y1 + 20 * math.sin(a)), fill=col, width=w)


def box(d, xy, wh, fill, outline=LINE, r=18, width=2):
    d.rounded_rectangle((xy[0], xy[1], xy[0] + wh[0], xy[1] + wh[1]), r, fill=fill, outline=outline, width=width)


def chip(d, x, y, text, fnt=F_CHIP, fg=TXT, bg=(22, 33, 60), pad=(18, 9)):
    tw = d.textlength(text, font=fnt)
    w, h = tw + 2 * pad[0], fnt.size + 2 * pad[1]
    d.rounded_rectangle((x, y, x + w, y + h), h // 2, fill=bg)
    d.text((x + pad[0], y + pad[1] - 2), text, font=fnt, fill=fg)
    return w


# ---------------------------------------------------------------- scenes
def sc_title():
    img = BG.copy()
    d = ImageDraw.Draw(img)
    d.text((150, 210), "PDF Q&A", font=font(140, True), fill=TXT)
    d.text((156, 380), "Scanned PDFs are pictures, not text.", font=F_SUB, fill=ACC)
    d.text((156, 432), "This is the problem PDF Q&A was built to kill.", font=F_BODY, fill=MUT)
    stats = [("1,623", "scanned pages in the two Hitachi Zosen\nengine manuals used for the real test"),
             ("0", "searchable characters before OCR —\nCtrl+F found nothing"),
             ("15 lakh+", "characters extracted and made\nsearchable in SQLite")]
    x0, cw, gap = 150, 540, 36
    for i, (big, body) in enumerate(stats):
        x = x0 + i * (cw + gap)
        box(d, (x, 560), (cw, 300), (19, 28, 52), LINE, 24)
        d.text((x + 34, 596), big, font=F_BIG, fill=OK if i == 2 else TXT)
        yy = 700
        for ln in body.split("\n"):
            d.text((x + 34, yy), ln, font=F_SMALL, fill=MUT)
            yy += 36
    return img


def sc_shot(img_file, kicker, title, bullets=(), focus=(0.5, 0.5), extra=None):
    """Real app screenshot on the left, a 'what to notice' panel on the right.

    `extra` adds a second (usually portrait) screenshot beside the main one —
    used by the data scene to show the phone layout next to the desktop app.
    """
    img = BG.copy()
    header(img, kicker, title)
    d = ImageDraw.Draw(img)
    if extra:
        main_w, main_h = 880, 556
        card = card_rgba(os.path.join(SHOTS, img_file), main_w, main_h, 1.0)
        paste_center(img, card, 96 + main_w / 2, 576)
        ex = card_rgba(os.path.join(SHOTS, extra), 300, 660, 1.0)
        paste_center(img, ex, 1046 + ex.width / 2, 576)
    else:
        max_w, max_h = 1204, 742
        card = card_rgba(os.path.join(SHOTS, img_file), max_w, max_h, 1.0)
        paste_center(img, card, 96 + max_w / 2, 205 + max_h / 2)
    x = 1340
    d.text((x, 268), "WHAT TO NOTICE", font=F_CHIP, fill=ACC)
    d.line((x, 308, 1824, 308), fill=LINE, width=1)
    yy = 340
    for head, body in bullets:
        d.text((x, yy), head, font=F_BODY, fill=TXT)
        yy += 40
        for ln in wrap(body, F_SMALL, 484, d):
            d.text((x, yy), ln, font=F_SMALL, fill=MUT)
            yy += 32
        yy += 30
    return img, focus


def sc_arch():
    img = BG.copy()
    header(img, "UNDER THE HOOD", "One request, two paths: ingest and query")
    d = ImageDraw.Draw(img)
    lw, rw = 760, 900
    lx, rx = 96, 1080
    ly, ry = 230, 230
    left = [("Browser · static UI", "drag & drop, live progress, chat", ACC),
            ("Express server · Node 20", "routes, upload, progress, ask", ACC2),
            ("Python worker", "PyMuPDF text · RapidOCR on scanned pages", OK),
            ("Prisma 7 · libSQL driver", "documents → pages → chunks", ACC)]
    right = [("Question", "English or Hindi, with a document filter", ACC),
             ("BM25 search", "FTS5 index over every chunk", ACC2),
             ("AI chain", "Ollama → GLM → NVIDIA → OpenRouter → Gemini", OK),
             ("Answer + page", "cited passage, file name, match score", RUST)]
    bh, gap = 108, 34
    for col, x, items in ((0, lx, left), (1, rx, right)):
        yy = ly
        for i, (t, s, c) in enumerate(items):
            box(d, (x, yy), (lw if col == 0 else rw, bh), (19, 28, 52), LINE, 18)
            d.rectangle((x, yy, x + 8, yy + bh), fill=c)
            d.text((x + 30, yy + 22), t, font=F_BODY, fill=TXT)
            d.text((x + 30, yy + 62), s, font=F_SMALL, fill=MUT)
            if i < len(items) - 1:
                arrow(d, x + (lw if col == 0 else rw) / 2, yy + bh + 4,
                      x + (lw if col == 0 else rw) / 2, yy + bh + gap - 4, LINE, 4)
            yy += bh + gap
    arrow(d, lx + lw - 40, ly + 3 * (bh + gap) + bh / 2, rx + 60, ry + 2 * (bh + gap) + bh / 2, ACC, 6)
    d.text((880, 640), "ingest", font=F_SMALL, fill=MUT, anchor="ma")
    d.text((1540, 470), "query", font=F_SMALL, fill=MUT, anchor="ma")
    d.text((96, 990), "Everything stays on the machine: the PDF, the SQLite file and the OCR models.",
           font=F_SMALL, fill=MUT)
    return img


def sc_ai(img_file=None):
    """The five-provider chain on the left, the real in-app key test on the right."""
    img = BG.copy()
    header(img, "THE AI FALLBACK CHAIN", "Five providers. If one fails, the next answers.")
    d = ImageDraw.Draw(img)
    provs = [("1 · Ollama", "local · free · no key", "qwen2.5:7b", OK),
             ("2 · GLM", "z.ai", "glm-4.7-flash", ACC),
             ("3 · NVIDIA NIM", "build.nvidia.com", "nemotron-3.5-lightning-30b-a3b", ACC),
             ("4 · OpenRouter", "openrouter.ai", "nemotron-3.5-lightning:free", ACC),
             ("5 · Gemini", "aistudio.google.com", "gemini-flash-lite-latest", ACC)]
    bw, bh, gap = 1050, 88, 20
    x, yy = 96, 250
    for i, (t, s, m, c) in enumerate(provs):
        box(d, (x, yy), (bw, bh), (19, 28, 52), LINE, 16)
        d.rectangle((x, yy, x + 8, yy + bh), fill=c)
        d.text((x + 28, yy + 16), t, font=F_BODY, fill=TXT)
        d.text((x + 28, yy + 54), s, font=F_SMALL, fill=MUT)
        d.text((x + 420, yy + 54), m, font=F_MONO_S, fill=ACC)
        if i < len(provs) - 1:
            arrow(d, x + bw - 60, yy + bh + 2, x + bw - 60, yy + bh + gap - 2, LINE, 3)
        yy += bh + gap
    box(d, (x, yy), (bw, bh), (16, 46, 40), OK, 16)
    d.rectangle((x, yy, x + 8, yy + bh), fill=OK)
    d.text((x + 28, yy + 16), "Sab fail?", font=F_BODY, fill=OK)
    d.text((x + 28, yy + 54), "Database answer wapas aata hai — passage, page number aur score.", font=F_SMALL, fill=TXT)

    if img_file and os.path.exists(os.path.join(SHOTS, img_file)):
        d.text((1180, 200), "LIVE KEY TEST — THIS RUN", font=F_CHIP, fill=ACC)
        card = card_rgba(os.path.join(SHOTS, img_file), 360, 742, 1.0)
        paste_center(img, card, 1180 + (1824 - 1180) / 2, 236 + 742 / 2)
        d.text((1180, 990), "No keys in this run — the chain falls through to the database answer.",
               font=F_REPO_S, fill=MUT)
    return img


def sc_stack():
    img = BG.copy()
    header(img, "TECHNOLOGY, LIBRARIES, MODELS", "Exactly what ships in this repository")
    d = ImageDraw.Draw(img)
    groups = [
        ("SERVER", ["Node.js 20", "Express 4", "TypeScript · tsx", "Multer uploads"], ACC),
        ("DATABASE", ["Prisma 7", "libSQL driver", "SQLite", "FTS5 index", "BM25 ranking"], ACC2),
        ("DOCUMENT AI", ["PyMuPDF", "RapidOCR", "ONNX Runtime", "Tesseract (option)"], OK),
        ("AI MODELS", ["Qwen 2.5 7B · Ollama", "GLM 4.7 Flash", "Nemotron 3.5 Lightning", "OpenRouter :free", "Gemini Flash Lite"], WARN),
        ("DEPLOY", ["Docker", "Docker Compose", "AWS EC2", "GitHub Actions"], RUST),
    ]
    cw, ch, gap = 336, 470, 24
    x0 = (W - (5 * cw + 4 * gap)) / 2
    for i, (name, items, c) in enumerate(groups):
        x = x0 + i * (cw + gap)
        box(d, (x, 250), (cw, ch), (17, 26, 48), LINE, 20)
        d.rectangle((x, 250, x + cw, 258), fill=c)
        d.text((x + 24, 286), name, font=F_CHIP, fill=c)
        yy = 340
        for it in items:
            d.ellipse((x + 26, yy + 9, x + 38, yy + 21), fill=MUT)
            for ln in wrap(it, F_SMALL, cw - 80, d):
                d.text((x + 52, yy), ln, font=F_SMALL, fill=TXT)
                yy += 32
            yy += 14
    d.text((96, 800), "Plus the video stack: brag · cinematic-skill · VoiceStudio · OmniVoice · playwright-mcp",
           font=F_BODY, fill=ACC)
    d.text((96, 850), "Voice: a natural female neural voice. Captions: punctuation-aware chunks. Render: FFmpeg + libx264.",
           font=F_SMALL, fill=MUT)
    return img


def sc_repos():
    img = BG.copy()
    header(img, "BUILT WITH THESE OPEN-SOURCE PROJECTS", "The five repositories behind this film")
    d = ImageDraw.Draw(img)
    repos = [
        ("brag", "latent-spaces/brag", "Storyboard, music & SFX", "Launch-video skill. Supplied the CC BY 4.0 Ende.app track and the Kenney sound effects.", ACC),
        ("cinematic-skill", "Moh4696/cinematic-skill", "Cinematic board & captions", "One-camera board rules, beat table and caption styles used for every scene.", ACC2),
        ("VoiceStudio", "debpalash/VoiceStudio", "Voice & audio mix", "Open-source local ElevenLabs alternative; its quality analysis and mixing shaped the voice-over.", OK),
        ("OmniVoice", "k2-fsa/OmniVoice", "Speech design", "600+ language zero-shot TTS; punctuation-aware chunking guided the subtitle timing.", WARN),
        ("playwright-mcp", "microsoft/playwright-mcp", "Real screenshots", "Headless browser automation that captured every app screenshot in this film.", RUST),
    ]
    cw, ch, gap = 336, 560, 24
    x0 = (W - (5 * cw + 4 * gap)) / 2
    for i, (name, repo, role, desc, c) in enumerate(repos):
        x = x0 + i * (cw + gap)
        box(d, (x, 240), (cw, ch), (17, 26, 48), LINE, 20)
        d.rectangle((x, 240, x + cw, 250), fill=c)
        d.text((x + 24, 286), name, font=F_REPO, fill=TXT)
        d.text((x + 24, 330), repo, font=F_MONO_S, fill=c)
        d.text((x + 24, 378), role, font=F_REPO_B, fill=ACC)
        yy = 424
        for ln in wrap(desc, F_REPO_S, cw - 48, d):
            d.text((x + 24, yy), ln, font=F_REPO_S, fill=MUT)
            yy += 28
        d.line((x + 24, 620, x + cw - 24, 620), fill=LINE, width=1)
        d.text((x + 24, 646), "github.com", font=F_MONO_S, fill=MUT)
    return img


def sc_outro():
    img = BG.copy()
    d = ImageDraw.Draw(img)
    d.text((150, 220), "Setup · Start · Drop a PDF · Ask", font=font(60, True), fill=TXT)
    cmds = [("setup.sh  /  setup.bat", "one time: Python, OCR, npm, Prisma, database"),
            ("npm start", "http://localhost:8000"),
            ("docker compose up -d --build", "the AWS EC2 path, in the repository")]
    y = 400
    for c, s in cmds:
        box(d, (150, y), (1500, 96), (8, 12, 22), LINE, 16)
        d.text((186, y + 16), c, font=F_MONO, fill=TXT)
        d.text((186, y + 58), s, font=F_SMALL, fill=MUT)
        y += 126
    d.text((150, 830), "Guides: HOW_TO_RUN.md · AWS_DEPLOY.md · docs/ (Word, English + Hinglish)", font=F_SMALL, fill=MUT)
    d.text((150, 884), "github.com/akashshinde700/ocr_pdf", font=F_BODY, fill=ACC)
    return img


# ---------------------------------------------------------------- audio
def decode(path, sr=SR):
    raw = subprocess.run([FF, "-v", "error", "-i", path, "-f", "f32le", "-ac", "1", "-ar", str(sr), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def ensure_brag_assets():
    """The music and SFX are brag's bundled assets (CC BY 4.0 / Kenney)."""
    if os.path.exists(MUSIC):
        return
    dest = os.path.dirname(os.path.dirname(BRAG))          # .../work/repos
    os.makedirs(dest, exist_ok=True)
    print("fetching brag assets (music + SFX)…")
    subprocess.run(["git", "clone", "--depth", "1", "-q",
                    "https://github.com/latent-spaces/brag.git",
                    os.path.join(dest, "brag")], check=True)


def music_bed(n):
    """brag's CC BY 4.0 track, looped with a short crossfade to fill n samples."""
    ensure_brag_assets()
    track = decode(MUSIC)
    if len(track) >= n:
        return track[:n]
    out = track.copy()
    fade = int(1.5 * SR)
    while len(out) < n:
        need = n - len(out)
        piece = track[:min(len(track), need + fade)]
        # crossfade the overlap
        ov = min(fade, len(out), len(piece))
        if ov > 0:
            ramp = np.linspace(0, 1, ov)
            out[-ov:] = out[-ov:] * (1 - ramp) + piece[:ov] * ramp
            out = np.concatenate([out, piece[ov:]])
        else:
            out = np.concatenate([out, piece])
    return out[:n]


def sfx_bed(n, cuts):
    bed = np.zeros(n, dtype=np.float32)
    whoosh = decode(os.path.join(BRAG, "sfx", "impact", "impactSoft_medium_001.ogg"))
    whoosh = whoosh[:int(0.6 * SR)]
    click = decode(os.path.join(BRAG, "sfx", "interface", "click_003.ogg"))
    click = click[:int(0.12 * SR)]
    for i, t in enumerate(cuts):
        s = int(t * SR)
        w = whoosh if i % 2 == 0 else click
        if s + len(w) <= n:
            bed[s:s + len(w)] += w * (0.5 if i % 2 == 0 else 0.25)
    return bed


# ---------------------------------------------------------------- main
def main():
    nar = json.load(open(NARR, encoding="utf-8"))
    scenes = nar["scenes"]
    vos = []
    for sc in scenes:
        wav = os.path.join(AUDIO, f"scene{sc['id']:02d}.wav")
        if not os.path.exists(wav):
            print("missing", wav, "-> silent scene")
            vos.append(np.zeros(int(6.0 * SR), dtype=np.float32))
        else:
            vos.append(decode(wav))
    durs = [LEAD + len(v) / SR + TAIL for v in vos]
    # snap every cut to the 0.5 s beat grid
    starts, acc = [], 0.0
    for d in durs:
        starts.append(acc)
        acc += math.ceil(d / BEAT) * BEAT
    durs = [starts[i + 1] - starts[i] if i + 1 < len(starts) else d for i, d in enumerate(durs)]
    total = starts[-1] + durs[-1]
    print(f"scenes={len(scenes)} total={total:.1f}s")
    # chapter list for the Word document / video guide
    chap_titles = ["Hook — the problem", "The application", "Upload + live OCR", "Ask + sources",
                   "Architecture", "AI fallback chain", "Libraries and models",
                   "The five repositories", "Your data + mobile", "Outro"]
    with open(P("brag-output", "work", "chapters.json"), "w", encoding="utf-8") as f:
        json.dump({"total": round(total, 2),
                   "chapters": [{"t": round(s, 2), "title": chap_titles[i]}
                                for i, s in enumerate(starts)]}, f, indent=1)

    nS = int(math.ceil(total * SR)) + SR
    voice = np.zeros(nS, dtype=np.float32)
    for v, st in zip(vos, starts):
        o = int((st + LEAD) * SR)
        voice[o:o + len(v)] += v
    voice /= (np.abs(voice).max() + 1e-9)

    music = music_bed(nS)
    # ducking: music dips wherever the narrator is speaking
    env = np.abs(voice)
    k = int(0.25 * SR)
    env = np.convolve(env, np.ones(k) / k, mode="same")
    env = np.clip(env / (env.max() + 1e-9), 0, 1)
    gain = 0.16 * (1 - 0.72 * env)
    fade = np.minimum(1, np.arange(nS) / (2 * SR)) * np.minimum(1, (nS - np.arange(nS)) / (3 * SR))
    bed = music * gain * fade
    bed += sfx_bed(nS, starts[1:]) * fade
    mix = 0.95 * voice + bed
    mix = (mix / (np.abs(mix).max() + 1e-9) * 0.95).astype(np.float32)
    wav = os.path.join(WORK, "mix.f32")
    mix.tofile(wav)

    # ---------------- subtitles (punctuation-aware chunks, OmniVoice style)
    def chunk_text(text):
        parts = [p.strip() for p in re.split(r"(?<=[.!?;:])\s+", text) if p.strip()]
        chunks = []
        for p in parts:
            words = p.split()
            if len(words) <= 9:
                chunks.append(p)
            else:
                for j in range(0, len(words), 8):
                    chunks.append(" ".join(words[j:j + 8]))
        return chunks

    def build_cues(key):
        out = []
        for i, sc in enumerate(scenes):
            vd = len(vos[i]) / SR
            chunks = chunk_text(sc[key])
            tot = sum(len(p) for p in chunks)
            t0 = starts[i] + LEAD
            for p in chunks:
                t1 = t0 + vd * len(p) / tot
                out.append((t0, t1, p))
                t0 = t1
        return out

    def ts(s):
        ms = int(round(s * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    def write_srt(cues, path):
        with open(path, "w", encoding="utf-8") as f:
            for i, (a, b, p) in enumerate(cues, 1):
                f.write(f"{i}\n{ts(a)} --> {ts(min(b, total))}\n{p}\n\n")
        print("srt:", os.path.basename(path), len(cues), "cues")

    cues = build_cues("text")
    write_srt(cues, SRT)
    SRT_HI = P("brag-output", "prototype-tech-video.hi.srt")
    if any(sc.get("hi") for sc in scenes):
        write_srt(build_cues("hi"), SRT_HI)

    dd = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    cap_imgs = []
    for _, _, text in cues:
        lines = wrap(text, F_SUB, 1500, dd)[:2]
        lh = 46
        bw = int(max(dd.textlength(l, font=F_SUB) for l in lines)) + 56
        bh = lh * len(lines) + 26
        im = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        di = ImageDraw.Draw(im)
        di.rounded_rectangle((0, 0, bw - 1, bh - 1), 16, fill=(6, 9, 18, 200))
        for j, l in enumerate(lines):
            di.text((bw // 2, 12 + j * lh), l, font=F_SUB, fill=TXT, anchor="ma")
        cap_imgs.append(im)

    # ---------------- static layers
    layers, focuses = [], []
    for sc in scenes:
        k = sc["kind"]
        if k == "title":
            img, f = sc_title(), (0.5, 0.5)
        elif k == "shot":
            img, f = sc_shot(sc["img"], sc.get("kicker", "THE APP"), sc.get("title", ""),
                             bullets=sc.get("bullets", ()), extra=sc.get("extra"))
        elif k == "diagram":
            f = (0.5, 0.5)
            if sc["diagram"] == "aichain":
                img = sc_ai(sc.get("img"))
            else:
                img = {"architecture": sc_arch, "stack": sc_stack}[sc["diagram"]]()
        elif k == "repos":
            img, f = sc_repos(), (0.5, 0.5)
        else:
            img, f = sc_outro(), (0.5, 0.5)
        layers.append(img)
        focuses.append(f)
    layers[0].convert("RGB").save(POSTER, quality=92)

    # ---------------- render
    cmd = [FF, "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", wav,
           "-i", SRT]
    if os.path.exists(SRT_HI):
        cmd += ["-i", SRT_HI]
    cmd += ["-map", "0:v", "-map", "1:a", "-map", "2:s"]
    if os.path.exists(SRT_HI):
        cmd += ["-map", "3:s"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-ac", "2",
            "-c:s", "mov_text", "-metadata:s:s:0", "language=eng", "-metadata:s:s:0", "title=English"]
    if os.path.exists(SRT_HI):
        cmd += ["-metadata:s:s:1", "language=hin", "-metadata:s:s:1", "title=Hinglish"]
    cmd += ["-metadata", "title=PDF Q&A — Prototype Demo & Technology Deep Dive",
            "-movflags", "+faststart", "-shortest", OUT]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    nframes = int(total * FPS)
    for f in range(nframes):
        t = f / FPS
        i = max(k for k in range(len(scenes)) if starts[k] <= t)
        st, d = starts[i], durs[i]
        p = min(1.0, max(0.0, (t - st) / d))
        z = 1.0 + 0.055 * (0.5 - 0.5 * math.cos(math.pi * p))
        fx, fy = focuses[i]
        cx = 0.5 + (fx - 0.5) * 0.55
        cy = 0.5 + (fy - 0.5) * 0.45
        frame = zoom_crop(layers[i], z, cx, cy)
        # caption
        for j, (a, b, _) in enumerate(cues):
            if a <= t < b:
                s = cap_imgs[j]
                frame.paste(s, ((W - s.width) // 2, H - s.height - 46), s)
                break
        dr = ImageDraw.Draw(frame)
        dr.rectangle((0, H - 6, int(W * t / total), H), fill=ACC)
        # dip through the background at every cut
        e = min(t - st, st + d - t)
        if e < 0.28:
            kk = max(0.0, e / 0.28)
            frame = Image.blend(Image.new("RGB", (W, H), BG1), frame, kk)
        proc.stdin.write(frame.tobytes())
        if f % 300 == 0:
            print(f"frame {f}/{nframes}", flush=True)
    proc.stdin.close()
    proc.wait()
    print("done:", OUT, f"{total:.1f}s")


if __name__ == "__main__":
    sys.exit(main())
