# PDF Q&A: prototype film, setup, code flow, and AWS deployment

**New — prototype & technology film (19 November 2026).** A 3:00 English-narration film that presents the prototype and then goes deep on the stack: live app screenshots (captured from the running server through Playwright MCP), the ingest/query architecture, the five-provider AI fallback chain with the real in-app key test beside it, every library and model, and the verified results of this run. Female neural voice, burned-in English captions plus **two selectable subtitle tracks (English and Hinglish)**, brag's CC BY 4.0 Ende.app track and Kenney SFX. The presentable Word document is [docs/Prototype_Technology_Stack.docx](../docs/Prototype_Technology_Stack.docx). See [brag-plan.md](./brag-plan.md) for the storyboard.

Prototype film chapters: **0:00** hook · **0:17** the app · **0:38** upload + live OCR · **0:56** ask + sources · **1:12** architecture · **1:37** AI fallback chain · **1:58** libraries and models · **2:30** your data + mobile · **2:47** outro.

The three earlier 1080p videos have feminine Hinglish narration and a selectable subtitle track. The app is run locally for the demos; no EC2 resources were created.

**Start here (updated November 2026)** is rebuilt from real screenshots of the current app with two scanned Hitachi Zosen MAN B&W engine instruction books loaded (960 + 663 pages, ~15 lakh characters after OCR). It shows the one-time setup, live OCR progress on a large scan, the five-provider AI chain with its live key test (one provider rate-limited, the rest answering), a cited answer from page 11 with its sources, viewing/exporting/deleting data, the mobile layout and the AWS deploy path. Hinglish subtitles are burned in and also included as a separate track. Voice: Microsoft Edge neural TTS (hi-IN-SwaraNeural); the background pad is synthesized, no third-party music.

The code-flow deep dive and the AWS deploy video were recorded earlier: their demo uses a synthetic two-page, image-only coffee guide (RapidOCR extracts both pages and a database-only query returns **92°C from page 2**), and the UI they show predates the English interface and the OpenRouter provider.

| Video | File | Length |
| --- | --- | ---: |
| Prototype demo & technology deep dive (English, EN + HI subtitles) | [prototype-tech-video.mp4](./prototype-tech-video.mp4) | 3:00 |
| Start here: setup, upload a large scan, ask, verify and manage (updated) | [brag.mp4](./brag.mp4) | 2:44 |
| Code-flow deep dive | [code-flow-deep-dive.mp4](./code-flow-deep-dive.mp4) | 6:18 |
| Local install to Docker on AWS EC2 | [full-setup-deploy.mp4](./full-setup-deploy.mp4) | 4:45 |

The three final MP4s are included in `brag-output/`. On GitHub, open a file above and choose **Download raw file**. Intermediate audio, screenshots, and renders are not tracked.

## Jump to a chapter

| Code-flow deep dive | Install to AWS deploy |
| --- | --- |
| **0:10** · Ingest path vs. question path | **0:19** · Local prerequisites and setup |
| **0:32** · FormData, Express and the Python worker | **0:40** · EC2 launch and Security Group |
| **1:32** · Text extraction and OCR decision chart | **1:11** · SSH, Docker, Compose and `.env` |
| **2:32** · Prisma `Document`, `Page`, `Chunk`, and transaction | **2:19** · First build and `/api/health` |
| **3:06** · Chunking, FTS5/BM25 and TF-IDF | **2:48** · Private browser access via SSH tunnel |
| **4:39** · Provider chain and extractive fallback | **3:10** · Persistence and backup |
| **5:53** · Debugging by stage | **3:33** · GitHub Actions and secure access |

The deep dive covers the default `npm start` path at `e1794aa`: `static/index.html` → `server/index.ts` → `server/worker.ts` and `worker.py` → `pdf_ocr_qa/extract.py` and `ocr.py` → `server/store.ts`, `chunk.ts`, and `prisma.ts`. Questions go through `server/search.ts`, `answer.ts`, and optionally `ai.ts`. The standalone Python web/CLI entry points are not part of this request path.

## Commands from the deployment video

### 1. Run locally

Install Git, Node.js 20.19+ (Node 22 is a good match for the Docker image), and Python 3.10+. On Windows, enable Python on `PATH` during installation.

```bash
# Your computer: Linux or macOS
git clone https://github.com/akashshinde700/ocr_pdf.git
cd ocr_pdf
bash setup.sh
npm start
```

On Windows, run `setup.bat` and then `npm start` from the project folder in Command Prompt. Visit `http://localhost:8000` and verify a test upload and cited answer.

### 2. Provision and connect to Ubuntu EC2

In EC2, launch an Ubuntu Server 24.04 LTS instance. `t3.medium` with a 20 GiB disk is an example, not a requirement; check the price before launch. Create an SSH key pair and keep the private key private. Initially allow TCP 22 only from your own IP. Do **not** add a public TCP 8000 rule.

```bash
# Your computer: replace the hostname and key path with your own.
EC2_HOST=your-ec2-public-dns
chmod 600 ./pdf-qa.pem
ssh -i ./pdf-qa.pem "ubuntu@$EC2_HOST"
```

Verify the host key fingerprint before trusting the first connection. The Windows OpenSSH client can use the same `ssh -i` pattern with a Windows key path and private file permissions.

### 3. Install and deploy on EC2

```bash
# EC2 server (Ubuntu 24.04)
sudo apt update
sudo apt install -y docker.io docker-compose-v2 git
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
# Log out, reconnect with SSH, then verify:
docker compose version

cd ~
git clone https://github.com/akashshinde700/ocr_pdf.git
cd ocr_pdf
cp .env.example .env
chmod 600 .env
nano .env
# Set AI_MODE=off for the first smoke test.

docker compose up -d --build
docker compose ps
docker compose logs --tail 50
curl -fsS http://127.0.0.1:8000/api/health
```

Docker-group membership has root-equivalent privileges; only grant it to a trusted account. The container supplies Node, Prisma and the Python OCR runtime. If you decide to use a cloud AI provider, set keys only in the server-side `.env`; selected passages will be sent to that provider. A private GitHub repo also needs suitable read access on the server for `git clone`/`git pull`.

### 4. Use a tunnel, then verify and back up

```bash
# Your computer: new terminal, not inside the EC2 SSH shell
EC2_HOST=your-ec2-public-dns
ssh -N -L 127.0.0.1:8081:127.0.0.1:8000 \
    -i ./pdf-qa.pem "ubuntu@$EC2_HOST"
```

With the tunnel open, visit `http://localhost:8081`. Upload a small scanned PDF, ask a question, and check the cited page. `docker-compose.yml` mounts `./data` into the container, including the SQLite database and stored PDFs. To make an offline backup, pause the app briefly and copy the whole directory, not just the SQLite main file:

```bash
# EC2 server, from ~/ocr_pdf
umask 077
docker compose stop app
tar -czf "$HOME/pdf-qa-$(date +%F).tgz" data/
docker compose up -d
# Copy the archive to protected storage away from the EC2 instance.
```

### 5. Optional auto-deploy

After the first manual deployment works, configure `EC2_HOST`, `EC2_USER` and `EC2_SSH_KEY` under **Settings → Secrets and variables → Actions** in GitHub. The repository's [workflow](../.github/workflows/deploy.yml) responds to pushes to `master` or a manual run. It SSHes to `~/ocr_pdf`, pulls with `--ff-only`, rebuilds with Compose and retries `/api/health`.

Before enabling it for production, give the runner a restricted network path to the instance and pin a verified SSH host key instead of trusting `ssh-keyscan` alone. The app has no built-in login. Keep it private, or add authentication/private network access before introducing an HTTPS reverse proxy. Do not expose port 8000 directly. For a reverse proxy running on the EC2 host, bind the Compose mapping to `127.0.0.1:8000:8000` and leave the Security Group's public 8000 rule absent.

## Production credits and constraints

- [Brag](https://github.com/latent-spaces/brag) supplied the storyboard and real-app visual approach and the bundled music. **Happy Beats / Business Moves Vol. 1**, by [Ende.app](https://ende.app/en), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The track was trimmed, looped, faded and mixed under the narration.
- [OmniVoice](https://github.com/k2-fsa/OmniVoice) punctuation-aware text chunking was used to prepare the subtitles. Its model weights were not accessible in the workspace, so the speech is the auditioned feminine fallback voice, **not** OmniVoice synthesis.
- [VoiceStudio](https://github.com/debpalash/VoiceStudio) audio quality analysis and stereo voice-over mixing logic were used to check and master the clips. No real person's reference recording was used.
