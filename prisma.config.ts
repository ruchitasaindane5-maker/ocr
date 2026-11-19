import { defineConfig } from "prisma/config";

// The SQLite file path is relative to the schema (prisma/ folder),
// so ../data/pdf_qa.db = data/pdf_qa.db in the project root
export default defineConfig({
  schema: "prisma/schema.prisma",
  migrations: { path: "prisma/migrations" },
  datasource: {
    url: process.env.DATABASE_URL ?? "file:../data/pdf_qa.db",
  },
});
