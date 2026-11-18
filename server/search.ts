// Database search bina AI ke:
//  1) SQLite FTS5 + BM25 (raw SQL — FTS virtual table Prisma model nahi hoti)
//  2) TF-IDF fallback (Prisma ORM se chunks padh kar) jab FTS se kam mile
import { prisma } from "./prisma.js";
import { STOPWORDS, tokenize } from "./chunk.js";
import { ensureIdf, idfOf } from "./store.js";

export interface Hit {
  doc_id: string; doc_name: string; page: number;
  method: string; text: string; score: number;
}

export async function search(
  query: string, docId?: string | null, topK = 5
): Promise<Hit[]> {
  const terms = tokenize(query).filter((t) => !STOPWORDS.has(t));
  const useTerms = terms.length ? terms : tokenize(query);
  if (!useTerms.length) return [];
  const hits = await ftsSearch(useTerms, docId, topK);
  if (hits.length < topK) {
    const seen = new Set(hits.map((h) => `${h.doc_id}|${h.page}|${h.text.slice(0, 60)}`));
    for (const h of await tfidfSearch(useTerms, docId, topK)) {
      if (!seen.has(`${h.doc_id}|${h.page}|${h.text.slice(0, 60)}`)) hits.push(h);
      if (hits.length >= topK) break;
    }
  }
  return hits.slice(0, topK);
}

async function ftsSearch(
  terms: string[], docId: string | null | undefined, topK: number
): Promise<Hit[]> {
  const match = [...new Set(terms)].map((t) => `"${t.replace(/"/g, "")}"`).join(" OR ");
  const rows = await prisma.$queryRawUnsafe<any[]>(
    `SELECT c.doc_id AS docId, d.name AS docName, c.page_no AS pageNo,
            c.method AS method, c.text AS text, bm25(chunks_fts) AS rank
     FROM chunks_fts
     JOIN chunks c ON c.id = chunks_fts.chunk_id
     JOIN documents d ON d.id = c.doc_id
     WHERE chunks_fts MATCH ?
       ${docId ? "AND c.doc_id = ?" : ""}
     ORDER BY rank LIMIT ?`,
    ...(docId ? [match, docId, topK * 2] : [match, topK * 2])
  ).catch(() => [] as any[]);
  return rows.map((r) => {
    const a = Math.abs(Number(r.rank));
    return {
      doc_id: String(r.docId), doc_name: String(r.docName),
      page: Number(r.pageNo), method: String(r.method), text: String(r.text),
      score: Math.round((a / (1 + a)) * 10000) / 10000,
    };
  });
}

async function tfidfSearch(
  terms: string[], docId: string | null | undefined, topK: number
): Promise<Hit[]> {
  const chunks = await prisma.chunk.findMany({
    where: docId ? { docId } : {},
    include: { document: { select: { name: true } } },
  });
  const idf = await ensureIdf(); // ek baar — pehle har token par await hota tha
  const qCounts = new Map<string, number>();
  for (const t of terms) qCounts.set(t, (qCounts.get(t) ?? 0) + 1);
  const qVec = new Map<string, number>();
  for (const [t, v] of qCounts) qVec.set(t, (1 + Math.log(v)) * idfOf(idf, t));
  const qNorm = Math.sqrt([...qVec.values()].reduce((s, v) => s + v * v, 0)) || 1;
  const scored: Hit[] = [];
  for (const c of chunks) {
    const counts = new Map<string, number>();
    for (const t of tokenize(c.text)) counts.set(t, (counts.get(t) ?? 0) + 1);
    let dot = 0, norm = 0;
    for (const [t, v] of counts) {
      const w = (1 + Math.log(v)) * idfOf(idf, t);
      norm += w * w;
      if (qVec.has(t)) dot += (qVec.get(t)! / qNorm) * w;
    }
    const score = dot / (Math.sqrt(norm) || 1);
    if (score > 0.02) {
      scored.push({
        doc_id: c.docId, doc_name: c.document.name, page: c.pageNo,
        method: c.method, text: c.text, score: Math.round(score * 10000) / 10000,
      });
    }
  }
  return scored.sort((a, b) => b.score - a.score).slice(0, topK);
}
