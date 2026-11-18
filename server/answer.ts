// Sawaal -> database search -> jawab. 100% bina AI ke (Python version ka port)
import { STOPWORDS, tokenize } from "./chunk.js";
import { search, type Hit } from "./search.js";
import { listDocs, termIdf } from "./store.js";

async function extractiveAnswer(question: string, hits: Hit[]): Promise<string> {
  const qTerms = new Set(tokenize(question).filter((t) => !STOPWORDS.has(t)));
  const terms = qTerms.size ? qTerms : new Set(tokenize(question));
  const candidates: { score: number; window: string; h: Hit }[] = [];
  for (const [hitRank, h] of hits.entries()) {
    const lines = h.text.split("\n").map((l) => l.trim());
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line.length < 15 || line.toLowerCase().includes("trademark")) continue;
      const matched = [...terms].filter((t) => new Set(tokenize(line)).has(t));
      if (!matched.length) continue;
      let score = -hitRank * 0.3;
      for (const t of matched) score += await termIdf(t);
      const window = lines.slice(Math.max(0, i - 1), i + 5).filter(Boolean).join(" ");
      candidates.push({ score, window, h });
    }
  }
  candidates.sort((a, b) => b.score - a.score);
  const picked: { window: string; h: Hit }[] = [];
  const seen = new Set<string>();
  for (const c of candidates) {
    const key = c.window.toLowerCase().replace(/\W+/g, "").slice(0, 80);
    if (seen.has(key) || [...seen].some((s) => s.length > 40 && (key.includes(s) || s.includes(key)))) continue;
    seen.add(key);
    picked.push(c);
    if (picked.length >= 3) break;
  }
  const final = picked.length ? picked : [{ window: hits[0].text.slice(0, 500), h: hits[0] }];
  return [
    "Database mein mile sabse relevant hisso ke hisaab se:\n",
    ...final.map((p) => `• ${p.window}  — (${p.h.doc_name}, page ${p.h.page})`),
  ].join("\n");
}

export async function answerQuestion(
  question: string, docId?: string | null, topK = 5
) {
  const hits = await search(question, docId, topK);
  if (!hits.length) {
    const docs = (await listDocs()).map((d) => d.name).join(", ") || "koi PDF nahi";
    return {
      answer:
        `Is sawaal ke shabd kisi PDF mein nahi mile.\n` +
        `Database mein abhi ye PDFs hain: ${docs}\n` +
        `Tip: PDF mein use hue exact shabd try karo (jaise heading ya step ka naam).`,
      sources: [], mode: "database-search",
    };
  }
  const sources: Record<string, unknown>[] = [];
  const seen = new Set<string>();
  for (const h of hits) {
    const key = `${h.doc_id}|${h.page}`;
    if (seen.has(key)) continue;
    seen.add(key);
    sources.push({
      doc_id: h.doc_id, doc_name: h.doc_name, page: h.page, score: h.score,
      method: h.method, passage: h.text.slice(0, 600),
    });
  }
  return {
    answer: await extractiveAnswer(question, hits),
    sources, mode: "database-search",
  };
}
