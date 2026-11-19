# Brag Plan — PDF Q&A prototype & technology film

**Input:** this project + the live local app (`http://localhost:8000`), two real PDFs loaded
**Angle:** "Scanned PDFs are pictures, not text — this system reads them, stores them and answers with the page number"
**Hook (first 5 s):** 1,623 scanned pages, zero searchable characters — the problem, in three numbers
**Tone:** `cinematic` / `app-store` mix — trailer-scale type, clean feature cards, cuts on the beat grid
**Format:** landscape 1920×1080, 30 fps, English narration (female neural voice)
**Visual identity:** the app's own dark navy (#0b0d1a → #101830), accent #7da2ff, DejaVu type — the real UI is always the hero

## Storyboard

| # | Scene | Visual | Narration point | Est. |
|---|---|---|---|---|
| 1 | Hook | title card, three real stats | scanned ≠ text, 1,623 pages, 0 characters | 18 s |
| 2 | The app | `20_home_hidpi.png` + notice panel | what PDF Q&A is, one screen | 19 s |
| 3 | Upload + OCR | `26_ocr_progress_full.png` | drag & drop, local RapidOCR, live progress | 17 s |
| 4 | Ask | `40_answer_full.png` | answer carries its source (file, page, score) | 15 s |
| 5 | Architecture | drawn board | ingest path + query path | 24 s |
| 6 | AI chain | five provider rows + fallback, real in-app key test beside | Ollama → GLM → NVIDIA → OpenRouter → Gemini | 21 s |
| 7 | Stack | five library/model groups | exact versions and model ids | 34 s |
| 8 | Open source | five repo cards | the five repositories behind the film | 21 s |
| 9 | Your data | `42_view_data.png` + `44_mobile.png` + notice panel | view / export / delete / mobile | 16 s |
| 10 | Outro | command card + narration | setup one command, run one command | 12 s |

**Total:** 201 s (3:21). Every cut is snapped to the 0.5 s beat grid of the 120 BPM track.
**Subtitles:** two selectable tracks — English (`prototype-tech-video.srt`) and Hinglish (`prototype-tech-video.hi.srt`).

## Creative laws applied

- **brag** (`latent-spaces/brag`, `/brag-slim`): hook first, show the real product (every screenshot is a live capture, no mockups), one idea per scene, readable type, poster = a settled frame.
- **cinematic-skill** (`Moh4696/cinematic-skill`): one hero per line, the camera notices the hero ~0.3 s after it appears, captions as sentence chunks, chronology/line-length lint on the script.
- **VoiceStudio** (`debpalash/VoiceStudio`): voice-over mixed against the music bed with ducking and loudness normalisation.
- **OmniVoice** (`k2-fsa/OmniVoice`): punctuation-aware text chunking for the subtitle cues.
- **playwright-mcp** (`microsoft/playwright-mcp`): every app screenshot captured from the running server through the MCP browser tools.

## Sound

- Music: **Happy Beats / Business Moves Vol. 1** by [Ende.app](https://ende.app/en), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) (bundled with brag), looped with a 1.5 s crossfade.
- SFX: Kenney interface/impact effects (bundled with brag) on scene cuts.
- Voice: one neural female voice, one clip per scene, ducked against the bed.

## Deliverables

- `prototype-tech-video.mp4` — 1920×1080, 30 fps, AAC stereo, English + Hinglish subtitle tracks
- `prototype-tech-video.jpg` — poster (also frame 0 of the video)
- `prototype-tech-video.srt` — English captions
- `docs/Prototype_Technology_Stack.docx` — the presentable Word document (technology, libraries, models, AI, the five repositories, verified results)
