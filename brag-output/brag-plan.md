# Brag Plan — PDF Q&A (Tutorial Edition)

**Input:** Project (this repo) + live local app (http://localhost:8000)
**Angle:** "Drop in any PDF → saved to the database → answers with page numbers"
**Hook:** Promise in the first 5 seconds — answers even from scanned/screenshot PDFs, with page citations.
**Tone:** default (punchy, friendly teacher-style)
**Format:** landscape 1920×1080, slideshow of REAL app screenshots + terminal cards, Hindi voiceover (the user asked for it, so this tutorial cut is longer than the 20s brag rule)
**Visual identity:** The app's own dark blue (#0b101d bg, #5b8cff→#7c5cff gradient), DejaVu titles.

## Storyboard (narration = Hindi voiceover)

| # | Scene (visual) | Narration point | Est. |
|---|---|---|---|
| 1 | Title card (PIL) | Greeting + product promise | ~20s |
| 2 | Terminal card: setup | bash setup.sh / setup.bat — one-command setup | ~20s |
| 3 | 01_home.png | npm start → localhost:8000, screen tour | ~22s |
| 4 | 02_upload.png | Drag-drop upload, auto OCR, DB save | ~24s |
| 5 | 03_answer.png | Question → answer + Sources (page citation) | ~22s |
| 6 | 05_ai_panel.png | Ollama → GLM → NVIDIA → Gemini fallback | ~26s |
| 7 | 06_viewer.png | View data + TXT/CSV/JSON export, Prisma DB | ~20s |
| 8 | Outro card | Summary commands + AWS_DEPLOY.md note | ~18s |

**Frames:** each scene = 1920×1080 dark canvas, scene-title band on top, the real screenshot in the middle (brag law: real UI, no fake visuals).
**Poster:** scene 1 title card → brag.jpg, which is also frame 0 of the video.
**Music/SFX:** no external assets available in the sandbox; the voiceover is the only track (so no tempo grid). Mention this in the final delivery.
