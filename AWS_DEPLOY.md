# 🚀 Deploy to AWS — Step-by-Step Guide

The product is ready to deploy: **Dockerfile + docker-compose + health
check** are all in place. The easiest and cheapest way is **one EC2
instance + Docker** — that is what's described below.

---

## First, understand what runs on AWS and what doesn't

| Item | On AWS EC2 |
|---|---|
| Website + API + Prisma DB | ✅ Works (inside a Docker container) |
| PDF upload + OCR | ✅ Works (RapidOCR is inside the image) |
| GLM / NVIDIA / OpenRouter / Gemini AI chain | ✅ Works (keys in `.env`) |
| **Ollama (local AI)** | ⚠️ EC2 has no GPU and it is very slow on CPU — the app **skips** it automatically and the cloud chain runs. Ollama stays on your laptop at home. |
| Database data | ✅ Stays on the EC2 disk (`./data` folder) — it is **not lost** when the container is stopped/updated |

**Instance recommendation:** `t3.medium` (2 vCPU, 4 GB RAM) runs comfortably.
`t2.micro` (free tier, 1 GB RAM) may hang during OCR — fine for
testing only. Use a 20 GB disk.

---

## Step 1 — Create an EC2 instance

1. AWS Console → **EC2 → Launch instance**
2. Name: `pdf-qa`, OS: **Ubuntu Server 24.04 LTS**
3. Instance type: `t3.medium` · Create/download a key pair (keep the `.pem` file safe)
4. Open these ports under **Network settings → Security group**:
   | Port | Source | Purpose |
   |---|---|---|
   | 22 | My IP | SSH (just for you) |
   | 8000 | Anywhere (0.0.0.0/0) | Website (for testing) |
   | 80, 443 | Anywhere | For a domain/HTTPS later |
5. Storage: **20 GiB** → Launch

## Step 2 — Install Docker on the server

SSH into EC2 (or use the browser terminal from the AWS Console "Connect" button):

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER
# log out/in once (or run `newgrp docker`)
```

## Step 3 — Get the code and add keys

```bash
git clone https://github.com/akashshinde700/ocr_pdf.git
cd ocr_pdf
cp .env.example .env
nano .env        # fill in your GLM / NVIDIA / OpenRouter / Gemini keys
```

Important points for `.env`:
- **Leave the Ollama lines commented out** (Ollama won't run on AWS; the chain moves to the cloud APIs automatically)
- For free DeepSeek: `NVIDIA_MODEL=deepseek-ai/deepseek-r1` (no need for the paid DeepSeek API)

## Step 4 — Run it! 🎉

```bash
docker compose up -d --build
docker compose logs -f        # press Ctrl+C once you see "running at: http://localhost:8000"
```

Open in the browser: `http://<EC2-public-IP>:8000`

Health check (is everything OK?):
```bash
curl http://localhost:8000/api/health
# {"ok":true,"docs":0,...} means the server is fine
```

## Step 5 — Auto-deploy: GitHub push = website updates itself 🤖

Set it up once and you never have to touch the server again:
change code on your computer → `git push` → the live website updates in
2–4 minutes. The workflow file for this **already exists in the
project**: `.github/workflows/deploy.yml` (GitHub Actions).

**How it works:** push to master → the GitHub runner SSHes into EC2 →
on the server `git pull` + `docker compose up -d --build` → `/api/health`
check. If it fails, the Actions tab shows a red mark. `.env` and `data/`
stay on the server — the deploy never touches them, so keys/data are
always safe.

**One-time setup (on GitHub):**

1. Repo → **Settings → Secrets and variables → Actions →
   New repository secret**, create three secrets:

   | Secret | Value |
   |---|---|
   | `EC2_HOST` | The server's public IP (e.g. `13.234.xx.xx`) |
   | `EC2_USER` | `ubuntu` |
   | `EC2_SSH_KEY` | The **full text** of your `.pem` file (copy-paste from `-----BEGIN ...-----` to `-----END ...-----`) |

2. That's it! Now `git push origin master` and watch "Deploy to AWS EC2"
   run in the repo's **Actions** tab. To run it manually there is also a
   **Run workflow** button there.

**Note:**
- Only pushes to `master` go live — experiment on another branch and
  merge into master only when you're sure.
- Steps 1–4 (Docker + clone + `.env`) have to be done by hand once on the
  server; auto-deploy takes over after that.
- If the repo is private, the server needs a GitHub deploy key for
  `git clone` (Settings → Deploy keys) — a public repo works directly.

**To update the code (this is the way now):**
```bash
# on your computer — nothing to do on the server!
git add . && git commit -m "my change" && git push origin master
```

Old manual way (for emergencies): on the server
`cd ocr_pdf && git pull && docker compose up -d --build`

**Database backup (an important habit):**
```bash
cp data/pdf_qa.db ~/pdf_qa_backup_$(date +%F).db
# or send it to S3: aws s3 cp data/pdf_qa.db s3://<your-bucket>/backup.db
```

**Domain + HTTPS (for a professional look):**
1. Point the domain's A record at the EC2 IP via Route 53 / any registrar
2. Open ports 80/443 in the security group and close 8000
3. Free HTTPS (Let's Encrypt) with an Nginx reverse proxy + `certbot --nginx`
4. Nginx allows only 1 MB uploads by default — for PDFs up to 1 GB that can
   take hours to OCR, add this inside the `server { }` block:
   ```nginx
   client_max_body_size 1024m;
   proxy_read_timeout 24h;
   proxy_send_timeout 24h;
   ```

---

## ⚠️ 3 security points (before going public)

1. **The app has no login** — anyone who opens the link can upload/delete PDFs. Fine for personal use; if you want to make it public, ask first and a login can be added.
2. Instead of leaving port 8000 open directly, put it **behind Nginx** once you have a domain (Step 5).
3. Never put the `.env` file (keys) on GitHub — it is already blocked in `.gitignore`; keep it only on the server.

## If you get stuck (troubleshooting)

| Problem | Check |
|---|---|
| Website won't open | Is 8000 open in the security group? Is the container `up` in `docker compose ps`? |
| Auto-deploy fails (Actions red) | Are the secrets correct? (`EC2_HOST` IP, `EC2_USER` = ubuntu, `EC2_SSH_KEY` full .pem file) · Is the server running? · Is the folder on the server `~/ocr_pdf`? |
| Container keeps restarting | Check `docker compose logs` — usually a mistake in `.env` |
| Python error on upload | Read the worker error in `docker compose logs`; rebuild the image: `docker compose build --no-cache` |
| Answers are slow | Ollama isn't running on EC2 (that's normal) — the cloud AI answers; 1–2 min of OCR on a large PDF is normal |

---

*How to run on a local PC is in README.md. If you need anything else on
AWS (such as ECS, a load balancer, S3 storage, a login system), ask —
it can be added before deploying.*
