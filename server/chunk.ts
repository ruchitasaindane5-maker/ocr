// Text tokenize + chunking (TS port of the Python version, for search without AI)
// Hindi/Hinglish stopwords are intentional so Hinglish questions still match.
export const STOPWORDS = new Set(
  `the a an is are was were what how why when where who which in on of to for
   and or ke ka ki hai hain kya kaise karna kare mujhe batao bataiye me mein ye
   yeh wo woh se par bhi nahi to tha thi ho hota hoti aur ya lekin`.split(/\s+/)
);

export function tokenize(text: string): string[] {
  return (text || "")
    .toLowerCase()
    .split(/[^\p{L}\p{N}]+/u)
    .filter((t) => t.length > 1 || /\p{N}/u.test(t));
}

const CHUNK_TARGET = 900;
const CHUNK_OVERLAP = 150;

export function chunkPageText(
  text: string,
  target = CHUNK_TARGET,
  overlap = CHUNK_OVERLAP
): string[] {
  const paras = text
    .split(/\n{2,}|\n/)
    .map((p) => p.trim())
    .filter(Boolean);
  const chunks: string[] = [];
  let cur = "";
  for (let para of paras) {
    if (cur.length + para.length + 1 <= target) {
      cur = cur ? `${cur}\n${para}` : para;
    } else {
      if (cur) chunks.push(cur);
      while (para.length > target) {
        chunks.push(para.slice(0, target));
        para = para.slice(target - overlap);
      }
      cur = para;
    }
  }
  if (cur.trim()) chunks.push(cur);
  return chunks
    .map((c, i) => (i && overlap ? chunks[i - 1].slice(-overlap) + "\n" + c : c).trim())
    .filter((c) => c.length >= 30);
}
