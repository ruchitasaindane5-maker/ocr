// Database tables banao — prisma/schema.prisma ke models ke hisaab se.
// Ye `prisma db push` ka bina-engine-download wala pakka alternative hai
// (Rust-free Prisma Client ko runtime par koi engine nahi chahiye).
//   node scripts/init-db.mjs [db-path]
// Default path: DATABASE_URL (file:...) ya data/pdf_qa.db
import "dotenv/config"; // .env wala DATABASE_URL server se match kare
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createClient } from "@libsql/client";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function resolveDbPath() {
  if (process.argv[2]) return path.resolve(process.argv[2]);
  const url = process.env.DATABASE_URL;
  if (url?.startsWith("file:")) {
    const p = url.slice("file:".length).split("?")[0];
    return path.isAbsolute(p) ? p : path.resolve(root, "prisma", p);
  }
  return path.join(root, "data", "pdf_qa.db");
}

const dbPath = resolveDbPath();
fs.mkdirSync(path.dirname(dbPath), { recursive: true });

const db = createClient({ url: `file:${dbPath}` });
await db.executeMultiple(`
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
`);
console.log(`Database ready: ${dbPath} (documents / pages / chunks / chunks_fts)`);
