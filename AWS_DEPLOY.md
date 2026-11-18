# 🚀 AWS par Deploy — Step-by-Step Guide (Hinglish)

Product deploy ke liye ready hai: **Dockerfile + docker-compose + health
check** sab bana diya hai. Sabse aasan aur sasta tareeka **ek EC2 instance
+ Docker** hai — wahi neeche diya hai.

---

## Pehle samjho — AWS par kya chalega, kya nahi

| Cheez | AWS EC2 par |
|---|---|
| Website + API + Prisma DB | ✅ Chalega (Docker container mein) |
| PDF upload + OCR | ✅ Chalega (RapidOCR image ke andar hai) |
| GLM / NVIDIA / Gemini AI chain | ✅ Chalega (`.env` mein keys) |
| **Ollama (local AI)** | ⚠️ EC2 par GPU nahi hota, CPU par bahut slow — app khud use **skip** kar deta hai aur cloud chain chalti hai. Ollama sirf tumhare ghar ke laptop par rahega. |
| Database ka data | ✅ EC2 ki disk (`./data` folder) par rahega — container band/update karne par **nahi udega** |

**Instance ki salah:** `t3.medium` (2 vCPU, 4 GB RAM) aaram se chalega.
`t2.micro` (free tier, 1 GB RAM) par OCR ke time atak sakta hai — sirf
test ke liye theek hai. Disk 20 GB rakho.

---

## Step 1 — EC2 instance banao

1. AWS Console → **EC2 → Launch instance**
2. Name: `pdf-qa`, OS: **Ubuntu Server 24.04 LTS**
3. Instance type: `t3.medium` · Key pair banao/download karo (`.pem` file sambhal kar rakho)
4. **Network settings → Security group** mein ye ports kholo:
   | Port | Source | Kaam |
   |---|---|---|
   | 22 | My IP | SSH (sirf tumhare liye) |
   | 8000 | Anywhere (0.0.0.0/0) | Website (testing ke liye) |
   | 80, 443 | Anywhere | Baad mein domain/HTTPS ke liye |
5. Storage: **20 GiB** → Launch

## Step 2 — Server par Docker lagao

EC2 par SSH karke (ya AWS Console ke "Connect" button se browser terminal):

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER
# ek baar logout/login karo (ya `newgrp docker` chalao)
```

## Step 3 — Code lao aur keys lagao

```bash
git clone https://github.com/akashshinde700/ocr_pdf.git
cd ocr_pdf
cp .env.example .env
nano .env        # apni GLM / NVIDIA / GEMINI keys bharo
```

`.env` mein khaas baatein:
- Ollama wali lines **band hi rehne do** (AWS par Ollama nahi chalega, chain apne aap cloud APIs par chali jayegi)
- DeepSeek free mein chahiye to: `NVIDIA_MODEL=deepseek-ai/deepseek-r1` (paid DeepSeek API lene ki zaroorat nahi)

## Step 4 — Chalao! 🎉

```bash
docker compose up -d --build
docker compose logs -f        # "chal raha hai: http://localhost:8000" dikhe to Ctrl+C
```

Browser mein kholo: `http://<EC2-ka-public-IP>:8000`

Health check (sab theek hai ya nahi):
```bash
curl http://localhost:8000/api/health
# {"ok":true,"docs":0,...} aaye to server perfect hai
```

## Step 5 — Auto-Deploy: GitHub push = website khud update 🤖

Ek baar setting kar do, phir server par haath lagana hi nahi padega:
apne computer par code badlo → `git push` → 2–4 minute mein live
website update. Iske liye workflow file **project mein pehle se bani
hui hai**: `.github/workflows/deploy.yml` (GitHub Actions).

**Kaise kaam karta hai:** master par push → GitHub ka runner SSH se
EC2 mein ghusta hai → server par `git pull` + `docker compose up -d
--build` → `/api/health` check. Fail ho to Actions tab mein laal
nishaan dikhega. `.env` aur `data/` server par hi rahte hain — deploy
unhe haath nahi lagata, isliye keys/data har baar safe.

**Ek baar ki setting (GitHub par):**

1. Repo → **Settings → Secrets and variables → Actions →
   New repository secret**, teen secret banao:

   | Secret | Value |
   |---|---|
   | `EC2_HOST` | Server ka public IP (jaise `13.234.xx.xx`) |
   | `EC2_USER` | `ubuntu` |
   | `EC2_SSH_KEY` | Tumhari `.pem` file ka **poora text** (`-----BEGIN ...-----` se `-----END ...-----` tak copy-paste) |

2. Bas! Ab `git push origin master` karo aur repo ke **Actions** tab
   mein "Deploy to AWS EC2" chalta hua dekho. Haath se chalana ho to
   wahi se **Run workflow** button bhi hai.

**Dhyaan do:**
- Sirf `master` branch ka push live hoga — experiments dusri branch
  par karo, master mein tabhi merge karo jab sure ho.
- Server par pehli baar Step 1–4 (Docker + clone + `.env`) haath se
  karna padega; auto-deploy uske baad se hai.
- Repo private ho to server par `git clone` ke liye GitHub deploy key
  lagegi (Settings → Deploy keys) — public repo mein seedha chalega.

**Code update karna ho to (ab yahi tareeka hai):**
```bash
# apne computer par — server par kuch nahi karna!
git add . && git commit -m "mera badlav" && git push origin master
```

Haath wala purana tareeka (emergency ke liye): server par
`cd ocr_pdf && git pull && docker compose up -d --build`

**Database ka backup (zaroori aadat):**
```bash
cp data/pdf_qa.db ~/pdf_qa_backup_$(date +%F).db
# ya S3 par bhej do: aws s3 cp data/pdf_qa.db s3://<tumhari-bucket>/backup.db
```

**Domain + HTTPS (professional look ke liye):**
1. Route 53 / kisi registrar se domain ka A-record EC2 ke IP par lagao
2. Security group mein port 80/443 kholo, 8000 band kar do
3. Nginx reverse-proxy + `certbot --nginx` se free HTTPS (Let's Encrypt)

---

## ⚠️ Suraksha ki 3 baatein (public karne se pehle)

1. **App mein login nahi hai** — jo bhi link kholega, wo PDF upload/delete kar sakega. Sirf apne use ke liye hai to theek; public karna hai to pehle mujhse bolo, login lagwa dunga.
2. Port 8000 seedha khula rakhne ki jagah domain lagte hi **Nginx ke peeche** kar do (Step 5).
3. `.env` file (keys) kabhi GitHub par mat daalna — `.gitignore` mein pehle se band hai, server par hi rehne do.

## Phans jao to (troubleshooting)

| Dikkat | Check karo |
|---|---|
| Website nahi khul rahi | Security group mein 8000 khula hai? `docker compose ps` mein container `up` hai? |
| Auto-deploy fail (Actions laal) | Secrets sahi hain? (`EC2_HOST` IP, `EC2_USER` = ubuntu, `EC2_SSH_KEY` poori .pem file) · Server chalu hai? · Server par folder `~/ocr_pdf` hi hai? |
| Container baar-baar restart | `docker compose logs` dekho — aksar `.env` ki galti hoti hai |
| Upload par Python error | `docker compose logs` mein worker error padho; image dobara build: `docker compose build --no-cache` |
| Jawab slow hai | EC2 par Ollama nahi chal raha (normal hai) — cloud AI jawab dega; OCR badi PDF par 1–2 min normal hai |

---

*Local PC par chalane ka tareeka README.md mein hai. AWS par kuch aur
chahiye ho (jaise ECS, load balancer, S3 storage, login system) to bolo —
deploy se pehle wo bhi jod dunga.*
