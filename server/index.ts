// PDF OCR + Prisma Database Q&A — Node/Express server (MAIN server)
// Chalane ke liye:  npm install  &&  npm run db:setup  &&  npm start
// Phir http://localhost:8000 kholo.
// AI (optional): .env mein Ollama/GLM/NVIDIA/GEMINI lagao to jawab AI
// fallback chain se aayega, warna database-search jawab milta hai.
import "dotenv/config";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import express, { type NextFunction, type Request, type Response } from "express";
import multer from "multer";
import { DB_PATH, ensureSchema, prisma, isValidDocId } from "./prisma.js";
import * as store from "./store.js";
import { answerQuestion } from "./answer.js";
import { aiStatus, testAiProviders } from "./ai.js";
import { detectOcrEngine, extractWithPython } from "./worker.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const app = express();
const PORT = (() => {
  const n = Number(process.env.PORT);
  return Number.isFinite(n) && n > 0 && n < 65536 ? n : 8000;
})();

// Express 4 async handlers ke errors khud nahi pakadta — ek Prisma error
// par pehle poora process crash ho jata tha. Ye wrapper har async route
// ko surakshit banata hai, aur neeche wala error middleware saaf JSON deta hai.
const ah = (fn: (req: Request, res: Response) => Promise<unknown>) =>
  (req: Request, res: Response, next: NextFunction) =>
    Promise.resolve(fn(req, res)).catch(next);

app.disable("x-powered-by");
app.use((_req, res, next) => {
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("Referrer-Policy", "no-referrer");
  next();
});
app.use(express.json({ limit: "64kb" }));
app.use(express.static(path.join(root, "static")));

const uploadDir = path.join(root, "data", "tmp_uploads");
fs.mkdirSync(uploadDir, { recursive: true });
const upload = multer({
  dest: uploadDir,
  limits: { fileSize: 100 * 1024 * 1024, files: 20 }, // 100 MB/file, max 20 files
});

// Health check — AWS ALB / EC2 / Docker ke liye (halka, DB count ke saath)
app.get("/api/health", ah(async (_req, res) => {
  const docs = (await store.dbStats()).docs;
  res.json({ ok: true, docs, uptime_s: Math.round(process.uptime()) });
}));
app.get("/healthz", (_req, res) => res.json({ ok: true }));

app.get("/api/status", ah(async (_req, res) => {
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
}));

app.get("/api/docs", ah(async (_req, res) => res.json(await store.listDocs())));

app.post("/api/upload", upload.array("files"), ah(async (req, res) => {
  const ocrMode = String(req.body?.ocr_mode || "auto");
  const files = (req.files as Express.Multer.File[] | undefined) || [];
  if (!files.length) {
    return res.status(400).json({ error: "Koi file nahi mili. Pehle PDF choose karo." });
  }
  const added: unknown[] = [], errors: unknown[] = [], warnings: unknown[] = [];
  for (const f of files) {
    try {
      const data = fs.readFileSync(f.path);
      if (data.length < 5 || data.subarray(0, 4).toString() !== "%PDF") {
        errors.push({ name: f.originalname, error: "Ye PDF file nahi hai" });
        continue;
      }
      const extracted = await extractWithPython(f.path, ocrMode);
      if (extracted.total_chars < 20) {
        const why = extracted.warnings?.[0];
        errors.push({
          name: f.originalname,
          error: why
            ? `${why}. OCR engine install karke dobara try karo.`
            : "Is PDF se text nahi nikal paya. OCR 'always' karke dobara try karo.",
        });
        continue;
      }
      if (extracted.warnings?.length) {
        warnings.push({ name: f.originalname, warning: extracted.warnings[0] });
      }
      // Database mein sirf surakshit naam rakho (lambe/control-char wale kaat do)
      const safeName = (f.originalname || "file.pdf")
        .replace(/[\u0000-\u001f\u007f]/g, "").slice(0, 200) || "file.pdf";
      added.push(await store.addDocument(safeName, data, extracted));
    } catch (e) {
      errors.push({ name: f.originalname, error: String((e as Error).message || e).slice(0, 300) });
    } finally {
      try { fs.unlinkSync(f.path); } catch { /* ignore */ }
    }
  }
  res.json({ added, errors, warnings });
}));

app.delete("/api/docs/:id", ah(async (req, res) => {
  if (!isValidDocId(req.params.id)) return res.status(400).json({ error: "Galat doc id" });
  res.json({ deleted: await store.deleteDocument(req.params.id) });
}));

app.get("/api/docs/:id/text", ah(async (req, res) => {
  if (!isValidDocId(req.params.id)) return res.status(400).json({ error: "Galat doc id" });
  const d = await store.getDocument(req.params.id);
  if (!d) return res.status(404).json({ error: "doc not found" });
  res.json({ name: d.name, pages: d.pages });
}));

function csvCell(v: unknown): string {
  const s = String(v ?? "");
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** Download filename ko header-safe banao (quote/CRLF se header toot’ta tha) */
function safeFilename(name: string, ext: string): string {
  const base = name.replace(/\.pdf$/i, "")
    .replace(/["\r\n\\/:*?<>|]+/g, "_").replace(/\s+/g, " ").trim().slice(0, 120) || "document";
  return `${base}.${ext}`;
}

app.get("/api/docs/:id/export", ah(async (req, res) => {
  if (!isValidDocId(req.params.id)) return res.status(400).json({ error: "Galat doc id" });
  const d = await store.getDocument(req.params.id);
  if (!d) return res.status(404).json({ error: "doc not found" });
  const format = String(req.query.format || "txt");
  if (format === "json") {
    const chunks = await prisma.chunk.findMany({
      where: { docId: d.id }, orderBy: [{ pageNo: "asc" }, { id: "asc" }],
    });
    res.setHeader("Content-Disposition", `attachment; filename="${safeFilename(d.name, "json")}"`);
    return res.json({ ...d, chunks: chunks.map((c) => ({
      doc_id: c.docId, doc_name: d.name, page: c.pageNo, method: c.method, text: c.text,
    })) });
  }
  if (format === "csv") {
    const lines = [["document", "page", "method", "chars", "text"].join(",")];
    for (const p of d.pages) {
      lines.push([csvCell(d.name), p.page, csvCell(p.method), p.text.length, csvCell(p.text)].join(","));
    }
    res.setHeader("Content-Type", "text/csv; charset=utf-8");
    res.setHeader("Content-Disposition", `attachment; filename="${safeFilename(d.name, "csv")}"`);
    return res.send(lines.join("\r\n"));
  }
  if (format !== "txt") return res.status(400).json({ error: "format txt|csv|json hona chahiye" });
  const txt = d.pages
    .map((p) => `\n===== Page ${p.page} [${p.method}] =====\n${p.text}`)
    .join("\n");
  res.setHeader("Content-Type", "text/plain; charset=utf-8");
  res.setHeader("Content-Disposition", `attachment; filename="${safeFilename(d.name, "txt")}"`);
  res.send(txt);
}));

app.post("/api/ai/test", ah(async (_req, res) => {
  res.json({ results: await testAiProviders() });
}));

app.post("/api/ask", ah(async (req, res) => {
  const q = String(req.body?.question || "").trim();
  if (!q) return res.status(400).json({ error: "Sawaal khali hai" });
  if (q.length > 2000) return res.status(400).json({ error: "Sawaal bahut lamba hai (max 2000 characters)" });
  const docId = req.body?.doc_id || null;
  if (docId !== null && !isValidDocId(docId)) {
    return res.status(400).json({ error: "Galat doc_id" });
  }
  if ((await store.dbStats()).docs === 0) {
    return res.json({
      answer: "Pehle kam se kam ek PDF upload karo, phir sawaal puchho.",
      sources: [], mode: "database-search",
    });
  }
  res.json(await answerQuestion(q, docId));
}));

// Galat URL par HTML ki jagah saaf JSON
app.use("/api", (_req, res) => res.status(404).json({ error: "API route nahi mila" }));

// Multer ki galtiyon (badi file, zyada files) ko bhi saaf jawab do
app.use((err: unknown, _req: Request, res: Response, _next: NextFunction) => {
  if (err instanceof multer.MulterError) {
    const msg = err.code === "LIMIT_FILE_SIZE"
      ? "File bahut badi hai (max 100 MB per file)"
      : err.code === "LIMIT_FILE_COUNT"
        ? "Ek baar mein max 20 files upload karo"
        : `Upload error: ${err.message}`;
    return res.status(400).json({ error: msg });
  }
  console.error("API error:", err);
  if (!res.headersSent) {
    res.status(500).json({ error: "Server par kuch gadbad ho gayi. Dobara try karo." });
  }
});

ensureSchema()
  .then(() => {
    app.listen(PORT, "0.0.0.0", () => {
      console.log(`PDF OCR + Prisma Q&A chal raha hai: http://localhost:${PORT}`);
      console.log(`Database (Prisma/SQLite): ${DB_PATH}`);
    });
  })
  .catch((e) => {
    console.error("Database ready nahi ho paya:", String(e?.message || e).slice(0, 500));
    process.exit(1);
  });
