# Brag Plan — PDF Q&A (Tutorial Edition)

**Input:** Project (ye repo) + live local app (http://localhost:8000)
**Angle:** "Koi bhi PDF daalo → database mein save → page number ke saath jawab"
**Hook:** Pehle 5 second mein promise — scanned/screenshot PDF se bhi sawaal ka jawab, page citation ke saath.
**Tone:** default (punchy, dostana Hinglish teacher-style)
**Format:** landscape 1920×1080, slideshow of REAL app screenshots + terminal cards, Hinglish voiceover (user ne manga hai isiliye brag ke 20s rule se lamba tutorial cut)
**Visual identity:** App ka apna dark blue (#0b101d bg, #5b8cff→#7c5cff gradient), DejaVu titles.

## Storyboard (narration = Hinglish voiceover)

| # | Scene (visual) | Narration ka mudda | Est. |
|---|---|---|---|
| 1 | Title card (PIL) | Namaste + product promise | ~20s |
| 2 | Terminal card: setup | bash setup.sh / setup.bat — ek command setup | ~20s |
| 3 | 01_home.png | npm start → localhost:8000, screen tour | ~22s |
| 4 | 02_upload.png | Drag-drop upload, OCR auto, DB save | ~24s |
| 5 | 03_answer.png | Sawaal → jawab + Sources (page citation) | ~22s |
| 6 | 05_ai_panel.png | Ollama → GLM → NVIDIA → Gemini fallback | ~26s |
| 7 | 06_viewer.png | Data dekho + TXT/CSV/JSON export, Prisma DB | ~20s |
| 8 | Outro card | Summary commands + AWS_DEPLOY.md note | ~18s |

**Frames:** har scene = 1920×1080 dark canvas, upar scene-title band, beech mein asli screenshot (brag law: real UI, no fake visuals).
**Poster:** scene 1 ka title card → brag.jpg, video ka frame 0 wahi.
**Music/SFX:** koi external asset nahi milega sandbox mein; voiceover hi track hai (tempo grid ka sawal hi nahi). Final delivery mein mention karna hai.
