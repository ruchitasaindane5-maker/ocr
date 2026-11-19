// PDF OCR + Prisma Database Q&A — Node/Express server (MAIN server)
// To run:  npm install  &&  npm run db:setup  &&  npm start
// Then open http://localhost:8000
// AI (optional): configure Ollama/GLM/NVIDIA/OpenRouter/Gemini in .env and answers
// come from the AI fallback chain; otherwise you get the database-search answer.
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

// Express 4 does not catch errors from async handlers — a single Prisma error
// used to crash the whole process. This wrapper makes every async route safe,
// and the error middleware below returns clean JSON.
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
// Uploads interrupted by a server stop leave temp files behind (up to 1 GB
// each). Nothing is in flight at boot, so clear them all.
for (const f of fs.readdirSync(uploadDir)) {
  try { fs.rmSync(path.join(uploadDir, f), { force: true }); } catch { /* ignore */ }
}
// Max size per uploaded file (default 1024 MB — scanned manuals easily pass 100 MB)
const MAX_UPLOAD_MB = (() => {
  const n = Number(process.env.MAX_UPLOAD_MB);
  return Number.isFinite(n) && n > 0 ? n : 1024;
})();
const upload = multer({
  dest: uploadDir,
  limits: { fileSize: MAX_UPLOAD_MB * 1024 * 1024, files: 20 }, // max 20 files per upload
});

// Live progress of PDFs being processed, polled by the UI via /api/progress.
// Large scanned PDFs take an hour or more, so the user needs to see it moving.
interface Progress {
  name: string; file: number; files: number;
  done: number; total: number; started_at: string;
}
const processing = new Map<number, Progress>();
let progressSeq = 0;

// Health check — for AWS ALB / EC2 / Docker (lightweight, with DB count)
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

app.get("/api/progress", (_req, res) => {
  res.json({ items: [...processing.values()] });
});

app.post("/api/upload", upload.array("files"), ah(async (req, res) => {
  const ocrMode = String(req.body?.ocr_mode || "auto");
  const files = (req.files as Express.Multer.File[] | undefined) || [];
  if (!files.length) {
    return res.status(400).json({ error: "No file received. Choose a PDF first." });
  }
  const added: unknown[] = [], errors: unknown[] = [], warnings: unknown[] = [];
  for (const [i, f] of files.entries()) {
    const pid = ++progressSeq;
    processing.set(pid, {
      name: f.originalname, file: i + 1, files: files.length,
      done: 0, total: 0, started_at: new Date().toISOString(),
    });
    try {
      // Only the first bytes are read to check the type — files can be up to 1 GB
      const head = Buffer.alloc(5);
      const fd = fs.openSync(f.path, "r");
      const n = (() => { try { return fs.readSync(fd, head, 0, 5, 0); } finally { fs.closeSync(fd); } })();
      if (n < 5 || head.subarray(0, 4).toString() !== "%PDF") {
        errors.push({ name: f.originalname, error: "This is not a PDF file" });
        continue;
      }
      const extracted = await extractWithPython(f.path, ocrMode, (done, total) => {
        const p = processing.get(pid);
        if (p) { p.done = done; p.total = total; }
      });
      if (extracted.total_chars < 20) {
        const why = extracted.warnings?.[0];
        errors.push({
          name: f.originalname,
          error: why
            ? `${why}. Install an OCR engine and try again.`
            : "Could not extract text from this PDF. Set OCR to 'always' and try again.",
        });
        continue;
      }
      if (extracted.warnings?.length) {
        warnings.push({ name: f.originalname, warning: extracted.warnings[0] });
      }
      // Store only a safe name in the database (trim long names / strip control chars)
      const safeName = (f.originalname || "file.pdf")
        .replace(/[\u0000-\u001f\u007f]/g, "").slice(0, 200) || "file.pdf";
      added.push(await store.addDocument(safeName, f.path, extracted));
    } catch (e) {
      errors.push({ name: f.originalname, error: String((e as Error).message || e).slice(0, 300) });
    } finally {
      processing.delete(pid);
      try { fs.unlinkSync(f.path); } catch { /* ignore */ }
    }
  }
  res.json({ added, errors, warnings });
}));

app.delete("/api/docs/:id", ah(async (req, res) => {
  if (!isValidDocId(req.params.id)) return res.status(400).json({ error: "Invalid doc id" });
  res.json({ deleted: await store.deleteDocument(req.params.id) });
}));

app.get("/api/docs/:id/text", ah(async (req, res) => {
  if (!isValidDocId(req.params.id)) return res.status(400).json({ error: "Invalid doc id" });
  const d = await store.getDocument(req.params.id);
  if (!d) return res.status(404).json({ error: "doc not found" });
  res.json({ name: d.name, pages: d.pages });
}));

function csvCell(v: unknown): string {
  const s = String(v ?? "");
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** Make the download filename header-safe (quotes/CRLF used to break the header) */
function safeFilename(name: string, ext: string): string {
  const base = name.replace(/\.pdf$/i, "")
    .replace(/["\r\n\\/:*?<>|]+/g, "_").replace(/\s+/g, " ").trim().slice(0, 120) || "document";
  return `${base}.${ext}`;
}

app.get("/api/docs/:id/export", ah(async (req, res) => {
  if (!isValidDocId(req.params.id)) return res.status(400).json({ error: "Invalid doc id" });
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
  if (format !== "txt") return res.status(400).json({ error: "format must be txt|csv|json" });
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
  if (!q) return res.status(400).json({ error: "Question is empty" });
  if (q.length > 2000) return res.status(400).json({ error: "Question is too long (max 2000 characters)" });
  const docId = req.body?.doc_id || null;
  if (docId !== null && !isValidDocId(docId)) {
    return res.status(400).json({ error: "Invalid doc_id" });
  }
  if ((await store.dbStats()).docs === 0) {
    return res.json({
      answer: "Upload at least one PDF first, then ask a question.",
      sources: [], mode: "database-search",
    });
  }
  res.json(await answerQuestion(q, docId));
}));

// Clean JSON instead of HTML for unknown API URLs
app.use("/api", (_req, res) => res.status(404).json({ error: "API route not found" }));

// Clean responses for Multer errors too (file too large, too many files)
app.use((err: unknown, _req: Request, res: Response, _next: NextFunction) => {
  if (err instanceof multer.MulterError) {
    const msg = err.code === "LIMIT_FILE_SIZE"
      ? `File is too large (max ${MAX_UPLOAD_MB} MB per file)`
      : err.code === "LIMIT_FILE_COUNT"
        ? "Upload at most 20 files at a time"
        : `Upload error: ${err.message}`;
    return res.status(400).json({ error: msg });
  }
  console.error("API error:", err);
  if (!res.headersSent) {
    res.status(500).json({ error: "Something went wrong on the server. Please try again." });
  }
});

ensureSchema()
  .then(() => {
    const server = app.listen(PORT, "0.0.0.0", () => {
      console.log(`PDF OCR + Prisma Q&A running at: http://localhost:${PORT}`);
      console.log(`Database (Prisma/SQLite): ${DB_PATH}`);
    });
    // Node cuts off a request body after 5 min by default — a 1 GB upload
    // over a slow connection (e.g. to AWS) needs longer. Processing itself
    // can take hours, so the response must not time out either.
    server.requestTimeout = 0;
    server.timeout = 0;
  })
  .catch((e) => {
    console.error("Database could not be initialised:", String(e?.message || e).slice(0, 500));
    process.exit(1);
  });
