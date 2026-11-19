"""Build the PDF Q&A "start here" video from real screenshots.
build_video.py <shots_dir> <work_dir> <out_mp4> <out_poster_jpg>
Needs: Pillow, numpy, edge-tts, imageio-ffmpeg (tools venv)."""
import asyncio, math, os, re, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import edge_tts, imageio_ffmpeg

SHOTS, WORK, OUT, POSTER = sys.argv[1:5]
os.makedirs(WORK, exist_ok=True)
FF = imageio_ffmpeg.get_ffmpeg_exe()
W, H, FPS, SR = 1920, 1080, 25, 44100
VOICE = "hi-IN-SwaraNeural"

FONTS = "C:/Windows/Fonts/"
def font(name, size): return ImageFont.truetype(FONTS + name, size)
F_KICK = font("seguisb.ttf", 28)
F_TITLE = font("segoeuib.ttf", 58)
F_BIG = font("segoeuib.ttf", 96)
F_MID = font("seguisb.ttf", 40)
F_BODY = font("segoeui.ttf", 34)
F_SUB = font("seguisb.ttf", 36)
F_MONO = font("consola.ttf", 40)
F_SMALL = font("segoeui.ttf", 26)

BG1, BG2 = (11, 16, 29), (17, 26, 50)
ACC, ACC2, TXT, MUT, LINE = (125, 162, 255), (165, 139, 255), (238, 241, 248), (169, 182, 206), (42, 59, 99)
OK = (61, 217, 160)

# ---------------- scenes ----------------
# hi = what the voice says (Devanagari for natural pronunciation); sub = on-screen Hinglish subtitles
SCENES = [
 dict(kind="title",
  hi="नमस्ते! ये है पीडीएफ क्यू एंड ए। कोई भी पीडीएफ डालो, चाहे वो हज़ार पेज का स्कैन्ड मैनुअल हो, और सवाल पूछो। जवाब मिलेगा, पेज नंबर के साथ।",
  sub="Namaste! Ye hai PDF Q&A. Koi bhi PDF daalo, chahe wo hazaar page ka scanned manual ho, aur sawaal poochho. Jawab milega, page number ke saath."),
 dict(kind="problem",
  hi="असली टेस्ट हुआ हिताची ज़ोसेन इंजन की दो इंस्ट्रक्शन बुक्स पर। कुल सोलह सौ तेईस स्कैन्ड पेज, और उनमें सर्च करने लायक एक भी अक्षर नहीं था।",
  sub="Asli test hua Hitachi Zosen engine ki do instruction books par. Kul 1,623 scanned pages, aur unme search karne layak ek bhi akshar nahi tha."),
 dict(kind="terminal", kicker="STEP 1 · SETUP", title="Teen commands, bas",
  hi="सेटअप सिर्फ़ एक बार। सेटअप डॉट बैट चलाओ। लोकल एआई चाहिए तो ओलामा पुल क्वेन। और फिर, एनपीएम स्टार्ट।",
  sub="Setup sirf ek baar. setup.bat chalao. Local AI chahiye to ollama pull qwen. Aur phir, npm start."),
 dict(kind="shot", img="01_home.png", kicker="STEP 2 · OPEN THE APP", title="localhost:8000 — poora app ek screen par", focus=(0.5, 0.35),
  hi="ब्राउज़र में लोकलहोस्ट आठ हज़ार खोलो। लेफ़्ट में अपलोड, डेटाबेस और एआई पैनल है, और राइट में चैट। ऊपर दिखता है कि कितनी पीडीएफ और कितने पेज सेव हैं।",
  sub="Browser mein localhost:8000 kholo. Left mein upload, database aur AI panel hai, aur right mein chat. Upar dikhta hai kitni PDF aur kitne pages save hain."),
 dict(kind="shot", img="02_upload_progress.png", kicker="STEP 3 · UPLOAD", title="Badi scanned PDF? Live progress", focus=(0.5, 0.7),
  hi="पीडीएफ को बॉक्स में ड्रैग करो, एक साथ बीस फ़ाइलें तक, हर फ़ाइल एक जीबी तक। स्कैन्ड पेज पर ओसीआर अपने आप चलता है, और यहाँ लाइव दिखता है, कौन सा पेज, कितने परसेंट, और कितना टाइम बाकी।",
  sub="PDF ko box mein drag karo, ek saath 20 files tak, har file 1 GB tak. Scanned page par OCR apne aap chalta hai, aur yahan live dikhta hai: kaunsa page, kitne percent, aur kitna time baaki."),
 dict(kind="shot", img="04b_ai_test_results.png", kicker="STEP 4 · AI CHAIN", title="Paanch AI — ek fail, to agla", focus=(0.5, 0.4),
  hi="पाँच एआई एक चेन में हैं। पहले लोकल ओलामा, फिर जीएलएम, एनवीडिया, ओपनराउटर और जेमिनी। एक फ़ेल हुआ तो अगला अपने आप जवाब देता है। यहाँ जीएलएम बिज़ी था, फिर भी बाकी चार चल रहे थे।",
  sub="Paanch AI ek chain mein hain: pehle local Ollama, phir GLM, NVIDIA, OpenRouter aur Gemini. Ek fail hua to agla apne aap jawab deta hai. Yahan GLM busy tha, phir bhi baaki chaar chal rahe the."),
 dict(kind="shot", img="08_answer_chat.png", kicker="STEP 5 · ASK", title="Sawaal poochho — jawab page ke saath", focus=(0.45, 0.55),
  hi="अब सवाल पूछा, इंजन रूम की सफ़ाई के लिए सेफ़्टी प्रीकॉशन्स क्या हैं? जवाब आया चार पॉइंट्स में, और आख़िर में लिखा है, पेज ग्यारह।",
  sub="Ab sawaal poochha: engine room ki safai ke liye safety precautions kya hain? Jawab aaya chaar points mein, aur aakhir mein likha hai: page 11."),
 dict(kind="shot", img="09_sources.png", kicker="STEP 6 · VERIFY", title="Sources — khud check karo", focus=(0.4, 0.3),
  hi="सोर्सेज़ खोलो, तो वही पेज दिखता है, पंचानवे परसेंट मैच के साथ। ये टेक्स्ट ओसीआर से निकला था। यानी जवाब तुम ख़ुद वेरीफ़ाई कर सकते हो।",
  sub="Sources kholo, to wahi page dikhta hai, 95% match ke saath. Ye text OCR se nikla tha. Yaani jawab tum khud verify kar sakte ho."),
 dict(kind="shot", img="10_view_data.png", kicker="STEP 7 · YOUR DATA", title="View data · Export · Delete", focus=(0.5, 0.45), extra="05_pdf_list.png",
  hi="हर पीडीएफ का पूरा डेटा देख सकते हो, टीएक्सटी, सीएसवी या जेसन में डाउनलोड कर सकते हो, और ज़रूरत न हो तो डिलीट भी। डिलीट से पहले कन्फ़र्म ज़रूर पूछता है।",
  sub="Har PDF ka poora data dekh sakte ho, TXT, CSV ya JSON mein download kar sakte ho, aur zaroorat na ho to delete bhi. Delete se pehle confirm zaroor poochhta hai."),
 dict(kind="aws", kicker="STEP 8 · PHONE & AWS", title="Phone par bhi. AWS ke liye tayyar.",
  hi="फ़ोन पर भी चलता है। और एडब्ल्यूएस पर डिप्लॉय करना हो, तो डॉकर और ईसी टू का पूरा सेटअप तैयार है। गिटहब पर पुश करो, और सर्वर अपने आप अपडेट।",
  sub="Phone par bhi chalta hai. Aur AWS par deploy karna ho, to Docker aur EC2 ka poora setup tayyar hai. GitHub par push karo, aur server apne aap update."),
 dict(kind="outro",
  hi="तो बस। सेटअप, स्टार्ट, पीडीएफ डालो, और सवाल पूछो। पूरी गाइड रिपॉज़िटरी में है। धन्यवाद!",
  sub="To bas: setup, start, PDF daalo, aur sawaal poochho. Poori guide repository mein hai. Dhanyavaad!"),
]

# ---------------- helpers ----------------
def gradient_bg():
    y = np.linspace(0, 1, H)[:, None, None]
    arr = (np.array(BG1) * (1 - y) + np.array(BG2) * y).repeat(W, axis=1)
    img = Image.fromarray(arr.astype(np.uint8), "RGB")
    glow = Image.new("L", (W, H), 0)
    ImageDraw.Draw(glow).ellipse((W - 900, -500, W + 400, 500), fill=70)
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    img = Image.composite(Image.new("RGB", (W, H), (60, 70, 160)), img, glow)
    d = ImageDraw.Draw(img)
    d.text((W - 96, 60), "PDF Q&A", font=F_KICK, fill=MUT, anchor="ra")
    return img

BG = gradient_bg()

def header(img, kicker, title):
    d = ImageDraw.Draw(img)
    d.text((96, 56), kicker, font=F_KICK, fill=ACC)
    d.text((96, 94), title, font=F_TITLE, fill=TXT)

def card_rgba(path, max_w, max_h, scale=1.0):
    im = Image.open(path).convert("RGB")
    r = min(max_w / im.width, max_h / im.height) * scale
    im = im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))), Image.LANCZOS)
    pad = 40
    out = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("L", out.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle((pad, pad + 14, pad + im.width, pad + im.height + 14), 22, fill=150)
    out.putalpha(sh.filter(ImageFilter.GaussianBlur(18)))
    out = Image.composite(Image.new("RGBA", out.size, (0, 0, 0, 255)), Image.new("RGBA", out.size, (0, 0, 0, 0)), out.getchannel("A"))
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, im.width - 1, im.height - 1), 18, fill=255)
    out.paste(im, (pad, pad), mask)
    ImageDraw.Draw(out).rounded_rectangle((pad, pad, pad + im.width - 1, pad + im.height - 1), 18, outline=LINE, width=2)
    return out

def wrap(text, fnt, width, draw):
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if draw.textlength(t, font=fnt) <= width: cur = t
        else: lines.append(cur); cur = w_
    if cur: lines.append(cur)
    return lines

def pill(d, xy, text, fnt, fill, fg):
    x, y = xy
    tw = d.textlength(text, font=fnt)
    d.rounded_rectangle((x, y, x + tw + 44, y + fnt.size + 26), 16, fill=fill)
    d.text((x + 22, y + 10), text, font=fnt, fill=fg)
    return x + tw + 44

# ---------------- static layers per scene ----------------
def static_layer(sc):
    img = BG.copy()
    d = ImageDraw.Draw(img)
    k = sc["kind"]
    if k == "title":
        d.text((140, 250), "PDF Q&A", font=font("segoeuib.ttf", 150), fill=TXT)
        d.text((146, 450), "Koi bhi PDF. Jawab page number ke saath.", font=F_MID, fill=ACC)
        y = 560
        for line in ["Scanned 1,000-page manuals · OCR · Prisma database", "5 AI fallback chain: Ollama → GLM → NVIDIA → OpenRouter → Gemini"]:
            d.text((146, y), line, font=F_BODY, fill=MUT); y += 54
        x = 146
        for t in ["Node.js", "Python OCR", "SQLite + FTS5", "Docker · AWS EC2"]:
            x = pill(d, (x, 720), t, F_SMALL, (23, 34, 59), TXT) + 16
    elif k == "problem":
        header(img, "THE PROBLEM", "Jawab manual mein hai. Dhoondhne mein ghante.")
        cards = [("1,623", "scanned pages — do instruction books (960 + 663)"),
                 ("0", "searchable characters — Ctrl+F kuch nahi dhoondhta"),
                 ("15 lakh", "characters OCR ke baad — ab sab searchable")]
        x0, cw = 96, 552
        for i, (big, body) in enumerate(cards):
            x = x0 + i * (cw + 36)
            d.rounded_rectangle((x, 300, x + cw, 720), 26, fill=(23, 34, 59), outline=LINE, width=2)
            d.text((x + 40, 340), big, font=F_BIG, fill=OK if i == 2 else TXT)
            yy = 490
            for ln in wrap(body, F_BODY, cw - 80, d):
                d.text((x + 40, yy), ln, font=F_BODY, fill=MUT); yy += 48
    elif k == "terminal":
        header(img, sc["kicker"], sc["title"])
        d.rounded_rectangle((96, 230, W - 96, 820), 22, fill=(8, 12, 22), outline=LINE, width=2)
        for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
            d.ellipse((130 + i * 34, 258, 150 + i * 34, 278), fill=c)
        d.text((260, 254), "Command Prompt — C:\\Users\\LENOVO\\Desktop\\ocr_pdf", font=F_SMALL, fill=MUT)
        rows = [("> setup.bat", "one-time: Python venv, OCR, npm install, Prisma, database", TXT),
                ("   OCR engine: rapidocr", None, OK),
                ("> ollama pull qwen2.5:7b", "optional: free local AI (~4.7 GB)", TXT),
                ("> npm start", None, TXT),
                ("   PDF OCR + Prisma Q&A running at: http://localhost:8000", None, OK)]
        y = 330
        for cmd, cmt, col in rows:
            d.text((150, y), cmd, font=F_MONO, fill=col)
            if cmt: d.text((150, y + 50), "   :: " + cmt, font=F_SMALL, fill=MUT); y += 40
            y += 82
    elif k == "aws":
        header(img, sc["kicker"], sc["title"])
        mob = card_rgba(os.path.join(SHOTS, "12_mobile.png"), 380, 700)
        img.paste(mob, (96 - 40, 210 - 40), mob)
        x = 560
        steps = [("git push", "master par"), ("GitHub Actions", "SSH · pull · build"), ("AWS EC2", "Docker container")]
        bw = 380
        for i, (a, b) in enumerate(steps):
            bx = x + i * (bw + 70)
            d.rounded_rectangle((bx, 280, bx + bw, 450), 22, fill=(27, 42, 77) if i == 2 else (23, 34, 59), outline=ACC if i == 2 else LINE, width=2)
            d.text((bx + 30, 310), a, font=F_MID, fill=TXT)
            d.text((bx + 30, 370), b, font=F_BODY, fill=MUT)
            if i < 2:
                ax = bx + bw + 12
                d.polygon([(ax, 350), (ax + 30, 350), (ax + 30, 335), (ax + 50, 365), (ax + 30, 395), (ax + 30, 380), (ax, 380)], fill=ACC)
        bullets = ["./data volume: database + PDFs rebuild ke baad bhi safe",
                   "EC2 par GPU nahi → cloud AI jawab dete hain",
                   "Login nahi hai → port 8000 public mat karo, SSH tunnel use karo"]
        y = 520
        for bl in bullets:
            d.ellipse((x, y + 16, x + 12, y + 28), fill=ACC)
            d.text((x + 30, y), bl, font=F_BODY, fill=MUT); y += 64
    elif k == "outro":
        d.text((140, 220), "Setup · Start · PDF daalo · Sawaal poochho", font=F_TITLE, fill=TXT)
        y = 360
        for cmd in ["setup.bat", "npm start   →  http://localhost:8000"]:
            d.rounded_rectangle((140, y, 1100, y + 84), 16, fill=(8, 12, 22), outline=LINE, width=2)
            d.text((176, y + 18), cmd, font=F_MONO, fill=TXT); y += 110
        d.text((140, 620), "Guides: HOW_TO_RUN.md · docs/PDF_QA_Complete_Guide (English + Hinglish) · AWS_DEPLOY.md", font=F_SMALL, fill=MUT)
        d.text((140, 680), "github.com/akashshinde700/ocr_pdf", font=F_MID, fill=ACC)
    else:  # shot
        header(img, sc["kicker"], sc["title"])
    return img

# ---------------- audio ----------------
async def tts_all():
    for i, sc in enumerate(SCENES):
        p = os.path.join(WORK, f"vo_{i:02d}.mp3")
        if not os.path.exists(p):
            await edge_tts.Communicate(sc["hi"], VOICE, rate="+4%").save(p)

def decode(path):
    raw = subprocess.run([FF, "-v", "error", "-i", path, "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)

def music(n):
    """Soft synthesized pad: Am–F–C–G, 4 s per chord, gentle swell."""
    t = np.arange(n) / SR
    chords = [[220.0, 261.63, 329.63], [174.61, 220.0, 261.63], [196.0, 261.63, 329.63], [196.0, 246.94, 293.66]]
    out = np.zeros(n, dtype=np.float64)
    seg = 4 * SR
    for s in range(0, n, seg):
        e = min(n, s + seg + SR)  # 1 s overlap
        tt = t[s:e] - t[s]
        env = np.minimum(1, tt / 1.2) * np.minimum(1, (tt[-1] - tt + 1e-6) / 1.2)
        ch = chords[(s // seg) % 4]
        sig = sum(np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(2 * np.pi * 2 * f * tt + 0.5) for f in ch)
        sig += 0.5 * np.sin(2 * np.pi * ch[0] / 2 * tt)
        out[s:e] += sig * env
    lfo = 0.85 + 0.15 * np.sin(2 * np.pi * 0.1 * t)
    out *= lfo
    return (out / (np.abs(out).max() + 1e-9)).astype(np.float32)

# ---------------- main ----------------
def main():
    asyncio.run(tts_all())
    vos = [decode(os.path.join(WORK, f"vo_{i:02d}.mp3")) for i in range(len(SCENES))]
    LEAD, TAIL = 0.45, 0.75
    durs = [LEAD + len(v) / SR + TAIL for v in vos]
    total = sum(durs)
    nS = int(math.ceil(total * SR)) + SR
    voice = np.zeros(nS, dtype=np.float32)
    starts, acc = [], 0.0
    for v, d in zip(vos, durs):
        starts.append(acc)
        o = int((acc + LEAD) * SR)
        voice[o:o + len(v)] += v
        acc += d
    voice /= (np.abs(voice).max() + 1e-9)
    bg = music(nS)
    fade = np.minimum(1, np.arange(nS) / (2 * SR)) * np.minimum(1, (nS - np.arange(nS)) / (3 * SR))
    mix = 0.92 * voice + 0.07 * bg * fade
    mix = (mix / (np.abs(mix).max() + 1e-9) * 0.95).astype(np.float32)
    wav = os.path.join(WORK, "mix.f32")
    mix.tofile(wav)

    # subtitles: split into sentences, time by character share of the voice duration
    srt, cues, n = [], [], 1
    for i, sc in enumerate(SCENES):
        parts = [p.strip() for p in re.split(r"(?<=[.!?:])\s+", sc["sub"]) if p.strip()]
        vd = len(vos[i]) / SR
        tot = sum(len(p) for p in parts)
        t0 = starts[i] + LEAD
        for p in parts:
            t1 = t0 + vd * len(p) / tot
            cues.append((t0, t1, p))
            fmt = lambda s: f"{int(s//3600):02d}:{int(s%3600//60):02d}:{int(s%60):02d},{int(s*1000%1000):03d}"
            srt += [str(n), f"{fmt(t0)} --> {fmt(t1)}", p, ""]
            n += 1; t0 = t1
    srt_path = os.path.join(WORK, "subs.srt")
    open(srt_path, "w", encoding="utf-8").write("\n".join(srt))

    # pre-render subtitle overlays
    dd = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    sub_imgs = []
    for (_, _, text) in cues:
        lines = wrap(text, F_SUB, 1500, dd)[:2]
        lh = 50
        bw = int(max(dd.textlength(l, font=F_SUB) for l in lines)) + 64
        bh = lh * len(lines) + 30
        im = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        di = ImageDraw.Draw(im)
        di.rounded_rectangle((0, 0, bw - 1, bh - 1), 18, fill=(6, 9, 18, 205))
        for j, l in enumerate(lines):
            di.text((bw // 2, 15 + j * lh), l, font=F_SUB, fill=TXT, anchor="ma")
        sub_imgs.append(im)

    statics = [static_layer(sc) for sc in SCENES]
    statics[0].convert("RGB").save(POSTER, quality=92)
    cards = {}
    for i, sc in enumerate(SCENES):
        if sc["kind"] == "shot":
            cards[i] = card_rgba(os.path.join(SHOTS, sc["img"]), 1500 if sc.get("extra") else 1728, 700, scale=1.06)
            if sc.get("extra"):
                cards[(i, "x")] = card_rgba(os.path.join(SHOTS, sc["extra"]), 420, 360)

    cmd = [FF, "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", wav,
           "-i", srt_path,
           "-map", "0:v", "-map", "1:a", "-map", "2:s",
           "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-ac", "2",
           "-c:s", "mov_text", "-metadata:s:s:0", "language=hin", "-metadata:s:s:0", "title=Hinglish",
           "-metadata", "title=PDF Q&A — Start here (2026 update)",
           "-movflags", "+faststart", "-shortest", OUT]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    nframes = int(total * FPS)
    for f in range(nframes):
        t = f / FPS
        i = max(k for k in range(len(SCENES)) if starts[k] <= t)
        sc, st, d = SCENES[i], starts[i], durs[i]
        p = (t - st) / d
        frame = statics[i].copy()
        if sc["kind"] == "shot":
            card = cards[i]
            z = (1 / 1.06) * (1.0 + 0.06 * (0.5 - 0.5 * math.cos(math.pi * p)))  # 0.943 -> 1.0 eased
            cw, ch = int(card.width * z), int(card.height * z)
            c = card.resize((cw, ch), Image.BILINEAR)
            fx, fy = sc.get("focus", (0.5, 0.5))
            area_cx = 96 + (1500 if sc.get("extra") else 1728) / 2
            cx = area_cx - (fx - 0.5) * (cw - card.width / 1.06) * 0.8
            cy = 215 + 700 / 2 - (fy - 0.5) * (ch - card.height / 1.06) * 0.8
            frame.paste(c, (int(cx - cw / 2), int(cy - ch / 2)), c)
            if sc.get("extra"):
                x2 = cards[(i, "x")]
                a = min(1, max(0, (p - 0.35) / 0.12))
                if a > 0:
                    x2a = x2.copy(); x2a.putalpha(x2.getchannel("A").point(lambda v: int(v * a)))
                    frame.paste(x2a, (W - x2.width - 40, 300), x2a)
        elif sc["kind"] in ("title", "outro", "problem", "terminal", "aws"):
            z = 1.0 + 0.025 * p
            if z > 1.001:
                cw, ch = int(W / z), int(H / z)
                frame = frame.crop(((W - cw) // 2, (H - ch) // 2, (W + cw) // 2, (H + ch) // 2)).resize((W, H), Image.BILINEAR)
        # subtitle
        for j, (a0, a1, _) in enumerate(cues):
            if a0 <= t < a1:
                s = sub_imgs[j]
                frame.paste(s, ((W - s.width) // 2, H - s.height - 52), s)
                break
        # progress bar
        dr = ImageDraw.Draw(frame)
        dr.rectangle((0, H - 6, int(W * t / total), H), fill=ACC)
        # fade through dark at scene edges
        e = min(t - st, st + d - t)
        if e < 0.25:
            k = max(0.0, e / 0.25)
            frame = Image.blend(Image.new("RGB", (W, H), BG1), frame, k)
        proc.stdin.write(frame.tobytes())
        if f % 250 == 0:
            print(f"frame {f}/{nframes}", flush=True)
    proc.stdin.close()
    proc.wait()
    print(f"done: {OUT}  duration={total:.1f}s scenes={len(SCENES)}")

main()
