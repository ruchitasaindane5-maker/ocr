// Saare database operations Prisma ORM se (Document / Page / Chunk models)
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { prisma, refreshFtsForDoc, removeFtsForDoc } from "./prisma.js";
import { chunkPageText } from "./chunk.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const UPLOAD_DIR = path.join(root, "data", "uploads");

export interface ExtractedPage {
  page: number;
  text: string;
  method: string;
}
export interface Extracted {
  pages: ExtractedPage[];
  page_count: number;
  total_chars: number;
  ocr_engine: string | null;
  ocr_pages: number;
  tables_found: number;
  metadata: Record<string, unknown>;
}

export function summaryOf(d: {
  id: string; name: string; pageCount: number; totalChars: number;
  ocrEngine: string | null; ocrPages: number; tablesFound: number;
  fileSize: number; createdAt: string; _count?: { chunks: number };
}) {
  return {
    id: d.id, name: d.name, pages: d.pageCount, chars: d.totalChars,
    chunks: d._count?.chunks ?? 0, ocr_engine: d.ocrEngine,
    ocr_pages: d.ocrPages, tables_found: d.tablesFound,
    file_size: d.fileSize, created_at: d.createdAt, saved_in_db: true,
  };
}

export async function addDocument(name: string, data: Buffer, ex: Extracted) {
  const sha = crypto.createHash("sha256").update(data).digest("hex");
  const id = sha.slice(0, 12);
  fs.mkdirSync(UPLOAD_DIR, { recursive: true });
  const storedFile = path.join(UPLOAD_DIR, `${id}.pdf`);
  fs.writeFileSync(storedFile, data);

  // Document upsert (Prisma) + purane pages/chunks saaf karke naye daalo
  await prisma.document.upsert({
    where: { id },
    create: {
      id, name, sha256: sha, fileSize: data.length,
      pageCount: ex.page_count, totalChars: ex.total_chars,
      ocrEngine: ex.ocr_engine, ocrPages: ex.ocr_pages,
      tablesFound: ex.tables_found,
      metadata: JSON.stringify(ex.metadata ?? {}),
      storedFile, createdAt: new Date().toISOString(),
    },
    update: {
      name, fileSize: data.length, pageCount: ex.page_count,
      totalChars: ex.total_chars, ocrEngine: ex.ocr_engine,
      ocrPages: ex.ocr_pages, tablesFound: ex.tables_found,
      metadata: JSON.stringify(ex.metadata ?? {}),
      storedFile, createdAt: new Date().toISOString(),
    },
  });
  await prisma.chunk.deleteMany({ where: { docId: id } });
  await prisma.page.deleteMany({ where: { docId: id } });
  await prisma.page.createMany({
    data: ex.pages.map((p) => ({
      docId: id, pageNo: p.page, method: p.method,
      text: p.text, charCount: p.text.length,
    })),
  });
  const chunkRows = ex.pages.flatMap((p) =>
    chunkPageText(p.text).map((text) => ({
      docId: id, pageNo: p.page, method: p.method, text,
    }))
  );
  if (chunkRows.length) await prisma.chunk.createMany({ data: chunkRows });
  await refreshFtsForDoc(id);
  invalidateIdf();
  return getSummary(id);
}

export async function getSummary(id: string) {
  const d = await prisma.document.findUnique({
    where: { id }, include: { _count: { select: { chunks: true } } },
  });
  if (!d) throw new Error("doc not found");
  return summaryOf(d);
}

export async function listDocs() {
  const docs = await prisma.document.findMany({
    orderBy: { createdAt: "asc" },
    include: { _count: { select: { chunks: true } } },
  });
  return docs.map(summaryOf);
}

export async function getDocument(id: string) {
  const d = await prisma.document.findUnique({
    where: { id },
    include: {
      pages: { orderBy: { pageNo: "asc" } },
      _count: { select: { chunks: true } },
    },
  });
  if (!d) return null;
  return {
    ...summaryOf(d), name: d.name,
    pages: d.pages.map((p) => ({ page: p.pageNo, text: p.text, method: p.method })),
  };
}

export async function deleteDocument(id: string): Promise<boolean> {
  await removeFtsForDoc(id);
  try {
    await prisma.document.delete({ where: { id } }); // pages/chunks cascade
  } catch {
    return false;
  }
  try { fs.unlinkSync(path.join(UPLOAD_DIR, `${id}.pdf`)); } catch { /* ignore */ }
  invalidateIdf();
  return true;
}

export async function dbStats() {
  const [docs, pages, chunks] = await Promise.all([
    prisma.document.count(), prisma.page.count(), prisma.chunk.count(),
  ]);
  return { docs, pages, chunks };
}

// ---------- TF-IDF fallback ke liye IDF cache (Prisma se chunks padh kar) ----------
let idfCache: Map<string, number> | null = null;
export function invalidateIdf() { idfCache = null; }

export async function termIdf(term: string): Promise<number> {
  if (!idfCache) {
    const rows = await prisma.chunk.findMany({ select: { text: true } });
    const df = new Map<string, number>();
    const { tokenize } = await import("./chunk.js");
    for (const r of rows) {
      for (const t of new Set(tokenize(r.text))) df.set(t, (df.get(t) ?? 0) + 1);
    }
    const n = Math.max(rows.length, 1);
    idfCache = new Map(
      [...df].map(([t, c]) => [t, Math.log((n + 1) / (c + 1)) + 1.0])
    );
  }
  return idfCache.get(term) ?? 1.0;
}
