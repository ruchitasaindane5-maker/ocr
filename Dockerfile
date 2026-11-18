# ============================================================
#  PDF Q&A — Docker image (AWS EC2 / ECS / kahin bhi chalegi)
#  Build:  docker build -t pdf-qa .
#  Run:    docker run -p 8000:8000 -v ./data:/app/data --env-file .env pdf-qa
#  Ya aasan: docker compose up -d --build
# ============================================================
FROM node:22-bookworm-slim

# Python (PDF/OCR worker ke liye) + certificates
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-venv python3-pip ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PORT=8000 \
    PYTHON_BIN=/app/.venv/bin/python \
    DATABASE_URL="file:../data/pdf_qa.db"

# --- Node packages (layer cache ke liye pehle sirf manifests) ---
COPY package.json package-lock.json ./
COPY prisma ./prisma
COPY prisma.config.ts ./prisma.config.ts
RUN npm install

# --- Python packages (setup.sh wala hi verified order) ---
COPY requirements.txt ./
RUN python3 -m venv .venv \
    && .venv/bin/pip install -q --upgrade pip \
    && .venv/bin/pip install -q -r requirements.txt \
    && (.venv/bin/pip uninstall -y -q opencv-python || true) \
    && .venv/bin/pip install -q --force-reinstall --no-cache-dir opencv-python-headless \
    && rm -rf /root/.cache/pip

# --- Baaki app ---
COPY . .
RUN mkdir -p data \
    && .venv/bin/python -c "import sys; sys.path.insert(0,'.'); from pdf_ocr_qa import ocr; print('OCR engine:', ocr.detect_engine())"

EXPOSE 8000
# data/ ko volume rakhna — warna container delete par database udega!
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD node -e "fetch('http://127.0.0.1:8000/healthz').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"

CMD ["npm", "start"]
