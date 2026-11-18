// Prisma Client (Rust-free, libSQL adapter) — database: data/pdf_qa.db
// Saare DB operations Prisma ORM se hote hain (server/store.ts dekho).
// Sirf FTS5 virtual table Prisma model nahi ban sakti, wo raw SQL se banti hai.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
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

/** FTS5 full-text index table (SQLite ki apni search, koi AI nahi). */
export async function ensureFtsTable(): Promise<void> {
  await prisma.$executeRawUnsafe(
    `CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
       text, doc_id UNINDEXED, page_no UNINDEXED, chunk_id UNINDEXED,
       tokenize='unicode61')`
  );
}

/** Ek document ke chunks ko FTS index mein (dobara) daalo. */
export async function refreshFtsForDoc(docId: string): Promise<void> {
  await prisma.$executeRawUnsafe(`DELETE FROM chunks_fts WHERE doc_id = ?`, docId);
  await prisma.$executeRawUnsafe(
    `INSERT INTO chunks_fts(text, doc_id, page_no, chunk_id)
     SELECT text, doc_id, page_no, id FROM chunks WHERE doc_id = ?`,
    docId
  );
}

export async function removeFtsForDoc(docId: string): Promise<void> {
  await prisma.$executeRawUnsafe(`DELETE FROM chunks_fts WHERE doc_id = ?`, docId);
}
