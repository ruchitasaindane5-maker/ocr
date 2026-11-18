import { defineConfig } from "prisma/config";

// SQLite file ka path schema (prisma/ folder) ke hisaab se banta hai,
// isliye ../data/pdf_qa.db = project root ki data/pdf_qa.db
export default defineConfig({
  schema: "prisma/schema.prisma",
  migrations: { path: "prisma/migrations" },
  datasource: {
    url: process.env.DATABASE_URL ?? "file:../data/pdf_qa.db",
  },
});
