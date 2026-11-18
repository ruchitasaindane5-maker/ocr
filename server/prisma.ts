// Prisma Client (Rust-free, libSQL adapter) — database: data/pdf_qa.db
// Saare DB operations Prisma ORM se hote hain (server/store.ts dekho).
// Sirf FTS5 virtual table Prisma model nahi ban sakti, wo raw SQL se banti hai.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createClient } from "@libsql/client";
import { PrismaLibSql } from "@prisma/adapter-libsql";
import { PrismaClient } from "./generated/prisma/client.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function resolveDbPath(): string {
  const url = process.env.DATABASE_URL;
  if (url?.startsWith("file:")) {
    const p = url.slice("file:".length).split("?")[0];
    // prisma.config mein path prisma/ folder ke relative hai
    return path.isAbsolute(p) ? p : path.resolve(root, "prisma", p);
  }
  return path.join(root, "data", "pdf_qa.db");
}

export const DB_PATH = resolveDbPath();
fs.mkdirSync(path.dirname(DB_PATH), { recursive: true });

const adapter = new PrismaLibSql({ url: `file:${DB_PATH}` });
export const prisma = new PrismaClient({ adapter });

// prisma/schema.prisma ke models ke hisaab se DDL — scripts/init-db.mjs
// ke saath ek hi sach (parity) rakha gaya hai. IF NOT EXISTS ki wajah se
// `prisma db push` wali DB par bhi chalana safe hai.
const SCHEMA_DDL = `
CREATE TABLE IF NOT EXISTS "documents" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "name" TEXT NOT NULL,
    "sha256" TEXT NOT NULL,
    "file_size" INTEGER NOT NULL DEFAULT 0,
    "page_count" INTEGER NOT NULL DEFAULT 0,
    "total_chars" INTEGER NOT NULL DEFAULT 0,
    "ocr_engine" TEXT,
    "ocr_pages" INTEGER NOT NULL DEFAULT 0,
    "tables_found" INTEGER NOT NULL DEFAULT 0,
    "metadata" TEXT NOT NULL DEFAULT '{}',
    "stored_file" TEXT,
    "created_at" TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS "documents_sha256_key" ON "documents"("sha256");
CREATE TABLE IF NOT EXISTS "pages" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "doc_id" TEXT NOT NULL,
    "page_no" INTEGER NOT NULL,
    "method" TEXT NOT NULL DEFAULT 'text',
    "text" TEXT NOT NULL DEFAULT '',
    "char_count" INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT "pages_doc_id_fkey" FOREIGN KEY ("doc_id") REFERENCES "documents" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS "pages_doc_id_page_no_key" ON "pages"("doc_id", "page_no");
CREATE INDEX IF NOT EXISTS "pages_doc_id_idx" ON "pages"("doc_id");
CREATE TABLE IF NOT EXISTS "chunks" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "doc_id" TEXT NOT NULL,
    "page_no" INTEGER NOT NULL,
    "method" TEXT NOT NULL DEFAULT 'text',
    "text" TEXT NOT NULL,
    CONSTRAINT "chunks_doc_id_fkey" FOREIGN KEY ("doc_id") REFERENCES "documents" ("id") ON DELETE CASCADE ON UPDATE CASCADE
);
CREATE INDEX IF NOT EXISTS "chunks_doc_id_idx" ON "chunks"("doc_id");
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, doc_id UNINDEXED, page_no UNINDEXED, chunk_id UNINDEXED,
    tokenize='unicode61'
);
`;

/**
 * Server boot par database ready karo. Pehle ye nahi hota tha — fresh DB
 * par sirf chunks_fts banti thi aur pehli API call par Prisma error se
 * poora server crash ho jata tha. Ab tables na hon to khud ban jati hain
 * (`npm run db:setup` bhool bhi jao to server chalega).
 */
let schemaReady: Promise<void> | null = null;
export function ensureSchema(): Promise<void> {
  if (!schemaReady) {
    schemaReady = (async () => {
      const raw = createClient({ url: `file:${DB_PATH}` });
      try {
        await raw.executeMultiple(SCHEMA_DDL);
      } finally {
        raw.close();
      }
    })();
  }
  return schemaReady;
}

/** @deprecated ensureSchema use karo (wahi FTS bhi bana deta hai). */
export async function ensureFtsTable(): Promise<void> {
  await ensureSchema();
}

const DOC_ID_RE = /^[A-Za-z0-9_-]{1,64}$/;

/** Route se aaya doc id surakshit hai ya nahi (path traversal rokne ke liye). */
export function isValidDocId(id: unknown): id is string {
  return typeof id === "string" && DOC_ID_RE.test(id);
}

/** Ek document ke chunks ko FTS index mein (dobara) daalo. */
export async function refreshFtsForDoc(docId: string): Promise<void> {
  if (!isValidDocId(docId)) return;
  await prisma.$executeRawUnsafe(`DELETE FROM chunks_fts WHERE doc_id = ?`, docId);
  await prisma.$executeRawUnsafe(
    `INSERT INTO chunks_fts(text, doc_id, page_no, chunk_id)
     SELECT text, doc_id, page_no, id FROM chunks WHERE doc_id = ?`,
    docId
  );
}

export async function removeFtsForDoc(docId: string): Promise<void> {
  if (!isValidDocId(docId)) return;
  await prisma.$executeRawUnsafe(`DELETE FROM chunks_fts WHERE doc_id = ?`, docId);
}
