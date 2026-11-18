// PDF OCR + Prisma Database Q&A — Node/Express server
// Chalane ke liye:  npm install  &&  npm run db:setup  &&  npm start
// Phir http://localhost:8000 kholo.
// AI (optional): .env mein GLM/NVIDIA/GEMINI keys daalo to jawab AI se
// aayega (fallback chain), warna database-search jawab milta hai.
import "dotenv/config";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import express from "express";
import multer from "multer";
import { DB_PATH, ensureFtsTable, prisma } from "./prisma.js";
import * as store from "./store.js";
import { answerQuestion } from "./answer.js";
import { aiStatus, testAiProviders } from "./ai.js";
import { detectOcrEngine, extractWithPython } from "./worker.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const app = express();
const PORT = Number(process.env.PORT || 8000);

app.use(express.json());
app.use(express.static(path.join(root, "static")));

const uploadDir = path.join(root, "data", "tmp_uploads");
fs.mkdirSync(uploadDir, { recursive: true });
const upload = multer({
  dest: uploadDir,
  limits: { fileSize: 100 * 1024 * 1024 }, // 100 MB per file
});

app.get("/api/status", async (_req, res) => {
  const stats = await store.dbStats();
  const sizeKb = ["", "-wal", "-shm"].reduce((sum, suf) => {
    const p = DB_PATH + suf;
    return sum + (fs.existsSync(p) ? fs.statSync(p).size : 0);
  }, 0) / 1024;
  res.json({
    mode: "Prisma database + AI fallback chain",
    orm: "Prisma",
    ocr_engine: await detectOcrEngine(),
    ai: await aiStatus(),
    database: { ...stats, db_path: DB_PATH, db_size_kb: Math.round(sizeKb * 10) / 10 },
  });
});

app.get("/api/docs", async (_req, res) => res.json(await store.listDocs()));

app.post("/api/upload", upload.array("files"), async (req, res) => {
  const ocrMode = String(req.body?.ocr_mode || "auto");
  const files = (req.files as Express.Multer.File[]) || [];
  const added: unknown[] = [], errors: unknown[] = [];
  for (const f of files) {
    try {
      const data = fs.readFileSync(f.path);
      if (data.subarray(0, 4).toString() !== "%PDF") {
        errors.push({ name: f.originalname, error: "Ye PDF file nahi hai" });
        continue;
      }
      const extracted = await extractWithPython(f.path, ocrMode);
      if (extracted.total_chars < 20) {
        errors.push({
          name: f.originalname,
          error: "Is PDF se text nahi nikal paya. OCR 'always' karke dobara try karo.",
        });
        continue;
      }
      added.push(await store.addDocument(f.originalname, data, extracted));
    } catch (e) {
      errors.push({ name: f.originalname, error: String((e as Error).message || e).slice(0, 300) });
    } finally {
      try { fs.unlinkSync(f.path); } catch { /* ignore */ }
    }
  }
  res.json({ added, errors });
});

app.delete("/api/docs/:id", async (req, res) => {
  res.json({ deleted: await store.deleteDocument(req.params.id) });
});

app.get("/api/docs/:id/text", async (req, res) => {
  const d = await store.getDocument(req.params.id);
  if (!d) return res.status(404).json({ error: "doc not found" });
  res.json({ name: d.name, pages: d.pages });
});

function csvCell(v: unknown): string {
  const s = String(v ?? "");
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

app.get("/api/docs/:id/export", async (req, res) => {
  const d = await store.getDocument(req.params.id);
  if (!d) return res.status(404).json({ error: "doc not found" });
  const format = String(req.query.format || "txt");
  const base = d.name.replace(/\.pdf$/i, "");
  if (format === "json") {
    const chunks = await prisma.chunk.findMany({
      where: { docId: d.id }, orderBy: [{ pageNo: "asc" }, { id: "asc" }],
    });
    res.setHeader("Content-Disposition", `attachment; filename="${base}.json"`);
    return res.json({ ...d, chunks: chunks.map((c) => ({
      doc_id: c.docId, doc_name: d.name, page: c.pageNo, method: c.method, text: c.text,
    })) });
  }
  if (format === "csv") {
    const lines = [["document", "page", "method", "chars", "text"].join(",")];
    for (const p of d.pages) {
      lines.push([csvCell(d.name), p.page, csvCell(p.method), p.text.length, csvCell(p.text)].join(","));
    }
    res.setHeader("Content-Type", "text/csv");
    res.setHeader("Content-Disposition", `attachment; filename="${base}.csv"`);
    return res.send(lines.join("\r\n"));
  }
  const txt = d.pages
    .map((p) => `\n===== Page ${p.page} [${p.method}] =====\n${p.text}`)
    .join("\n");
  res.setHeader("Content-Type", "text/plain; charset=utf-8");
  res.setHeader("Content-Disposition", `attachment; filename="${base}.txt"`);
  res.send(txt);
});

app.post("/api/ai/test", async (_req, res) => {
  res.json({ results: await testAiProviders() });
});

app.post("/api/ask", async (req, res) => {
  const q = String(req.body?.question || "").trim();
  if (!q) return res.status(400).json({ error: "Sawaal khali hai" });
  if ((await store.dbStats()).docs === 0) {
    return res.json({
      answer: "Pehle kam se kam ek PDF upload karo, phir sawaal puchho.",
      sources: [], mode: "database-search",
    });
  }
  res.json(await answerQuestion(q, req.body?.doc_id || null));
});

// purana Python (FastAPI) server bhi same DB use karta tha; Node ab main hai.
ensureFtsTable()
  .then(() => {
    app.listen(PORT, "0.0.0.0", () => {
      console.log(`PDF OCR + Prisma Q&A chal raha hai: http://localhost:${PORT}`);
      console.log(`Database (Prisma/SQLite): ${DB_PATH}`);
    });
  })
  .catch((e) => {
    console.error("Database ready nahi hai. Pehle chalao:  npm run db:setup");
    console.error(String(e?.message || e).slice(0, 500));
    process.exit(1);
  });
