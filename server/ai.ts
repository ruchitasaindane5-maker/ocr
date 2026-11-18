// AI Fallback Chain — Ollama (Local) -> GLM -> NVIDIA -> Gemini
// Ek fail hui (Ollama band, key galat, rate-limit, timeout) to dusri,
// dusri fail to teesri... Sab fail to caller database-search jawab dega.
// Cloud keys sirf .env se aati hain; Ollama ko key nahi chahiye (local PC).
import type { Hit } from "./search.js";

export type ProviderId = "ollama" | "glm" | "nvidia" | "gemini";

interface Provider {
  id: ProviderId;
  kind: "ollama" | "cloud";
  name: string;
  keyEnvs: string[];
  baseUrl: string;
  model: string;
  extraBody?: Record<string, unknown>;
  freeNote: string;
}

const env = (...names: string[]) => {
  for (const n of names) if (process.env[n]?.trim()) return process.env[n]!.trim();
  return "";
};

/** Env se number — kharab value par default, warna NaN se timeout/context toot jata tha */
function envNumber(name: string, fallback: number): number {
  const n = Number(process.env[name]);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

export function getProviders(): Provider[] {
  return [
    {
      id: "ollama",
      kind: "ollama",
      name: "Ollama (Local PC)",
      keyEnvs: [],
      baseUrl: env("OLLAMA_HOST") || "http://localhost:11434",
      // 16GB RAM + 6GB GPU ke liye best: ~4.7GB, zyada hissa GPU par, Hindi achhi
      model: env("OLLAMA_MODEL") || "qwen2.5:7b",
      freeNote: "Bilkul free, bina internet/key — ollama pull " + (env("OLLAMA_MODEL") || "qwen2.5:7b"),
    },
    {
      id: "glm",
      kind: "cloud",
      name: "GLM (z.ai)",
      keyEnvs: ["GLM_API_KEY", "ZAI_API_KEY"],
      baseUrl: env("GLM_BASE_URL") || "https://api.z.ai/api/paas/v4",
      model: env("GLM_MODEL") || "glm-4.7-flash", // z.ai par free model
      extraBody: { thinking: { type: "disabled" } },
      freeNote: "Free: glm-4.7-flash",
    },
    {
      id: "nvidia",
      kind: "cloud",
      name: "NVIDIA NIM",
      keyEnvs: ["NVIDIA_API_KEY"],
      baseUrl: env("NVIDIA_BASE_URL") || "https://integrate.api.nvidia.com/v1",
      model: env("NVIDIA_MODEL") || "meta/llama-3.3-70b-instruct",
      freeNote: "Free tier: build.nvidia.com key (nvapi-...)",
    },
    {
      id: "gemini",
      kind: "cloud",
      name: "Google Gemini",
      keyEnvs: ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
      baseUrl: env("GEMINI_BASE_URL") || "https://generativelanguage.googleapis.com/v1beta/openai",
      model: env("GEMINI_MODEL") || "gemini-2.5-flash", // free tier model
      freeNote: "Free tier: gemini-2.5-flash",
    },
  ];
}

export function providerOrder(): Provider[] {
  const all = getProviders();
  const wanted = (process.env.AI_PROVIDER_ORDER || "ollama,glm,nvidia,gemini")
    .split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
  const ordered = wanted
    .map((id) => all.find((p) => p.id === id))
    .filter((p): p is Provider => Boolean(p));
  return ordered.length ? ordered : all;
}

// ---------- Ollama health check (20 sec cache) ----------
export interface OllamaInfo { running: boolean; models: string[]; hasModel: boolean }
let ollamaCache: { at: number; info: OllamaInfo } | null = null;

export async function ollamaInfo(p?: Provider): Promise<OllamaInfo> {
  if (ollamaCache && Date.now() - ollamaCache.at < 20000) return ollamaCache.info;
  const prov = p || getProviders()[0];
  let info: OllamaInfo = { running: false, models: [], hasModel: false };
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 2000);
  try {
    const r = await fetch(`${prov.baseUrl.replace(/\/$/, "")}/api/tags`, { signal: ctrl.signal });
    if (r.ok) {
      const data = await r.json().catch(() => ({}));
      const models = (data?.models || []).map((m: any) => String(m?.name || ""));
      info = {
        running: true, models,
        hasModel: models.some((m) => m === prov.model || m.startsWith(prov.model + ":")),
      };
    }
  } catch { /* Ollama band hai — info default rahega */ } finally {
    clearTimeout(timer);
  }
  ollamaCache = { at: Date.now(), info };
  return info;
}

export async function aiStatus() {
  const disabled = (process.env.AI_MODE || "").toLowerCase() === "off";
  const providers = [];
  for (const [i, p] of providerOrder().entries()) {
    if (p.kind === "ollama") {
      const info = disabled ? { running: false, models: [], hasModel: false } : await ollamaInfo(p);
      providers.push({
        order: i + 1, id: p.id, name: p.name, model: p.model,
        configured: info.running, key_env: "key nahi chahiye (local)",
        status_text: disabled
          ? "⏸ AI_MODE=off hai"
          : info.running
            ? (info.hasModel ? "✅ Chal raha hai · model ready" : "⚠️ Chal raha hai · model download baki hai")
            : "⚠️ Chal nahi raha (Ollama app kholo)",
        free_note: p.freeNote,
        models_downloaded: info.models,
      });
    } else {
      const has = Boolean(env(...p.keyEnvs));
      providers.push({
        order: i + 1, id: p.id, name: p.name, model: p.model,
        configured: has, key_env: p.keyEnvs[0],
        status_text: disabled ? "⏸ AI_MODE=off hai" : has ? "✅ Key lagi hai" : "⚠️ Key nahi lagi",
        free_note: p.freeNote,
      });
    }
  }
  return {
    enabled: !disabled && providers.some((p) => p.configured),
    disabled_by_ai_mode_off: disabled,
    chain: providers.map((p) => p.name).join(" → "),
    providers,
  };
}

export interface Attempt {
  provider: string; model: string; ok: boolean; ms: number; error?: string;
}

type Msg = { role: string; content: string };

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: ctrl.signal });
  } catch (e: any) {
    if (e?.name === "AbortError") throw new Error(`Timeout (${Math.round(timeoutMs / 1000)}s se zyada laga)`);
    if (e?.cause?.code === "ECONNREFUSED" || /fetch failed/i.test(String(e?.message))) {
      throw new Error("Connect nahi hua (server chal nahi raha / galat URL)");
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

async function callCloud(p: Provider, messages: Msg[], maxTokens: number, timeoutMs: number): Promise<string> {
  const r = await fetchWithTimeout(
    `${p.baseUrl.replace(/\/$/, "")}/chat/completions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${env(...p.keyEnvs)}` },
      body: JSON.stringify({
        model: p.model, messages, temperature: 0.2,
        max_tokens: maxTokens, stream: false, ...(p.extraBody || {}),
      }),
    }, timeoutMs);
  const raw = await r.text();
  if (!r.ok) {
    let msg = raw.slice(0, 200);
    try { msg = JSON.parse(raw)?.error?.message || msg; } catch { /* raw hi rakho */ }
    throw new Error(`HTTP ${r.status}: ${msg}`);
  }
  const text = JSON.parse(raw)?.choices?.[0]?.message?.content;
  if (typeof text !== "string" || !text.trim()) throw new Error("Khali jawab aaya (empty response)");
  return text.trim();
}

async function callOllama(p: Provider, messages: Msg[], maxTokens: number, timeoutMs: number): Promise<string> {
  const r = await fetchWithTimeout(
    `${p.baseUrl.replace(/\/$/, "")}/api/chat`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: p.model, messages, stream: false,
        options: {
          temperature: 0.2,
          num_ctx: envNumber("OLLAMA_NUM_CTX", 8192), // PDF passages ke liye bada context
          num_predict: maxTokens,
        },
      }),
    }, timeoutMs);
  const raw = await r.text();
  if (!r.ok) {
    let msg = raw.slice(0, 200);
    try { msg = JSON.parse(raw)?.error || msg; } catch { /* raw hi rakho */ }
    if (/not found/i.test(msg)) msg = `Model download nahi hai — pehle chalao: ollama pull ${p.model}`;
    throw new Error(`HTTP ${r.status}: ${msg}`);
  }
  const text = JSON.parse(raw)?.message?.content;
  if (typeof text !== "string" || !text.trim()) throw new Error("Khali jawab aaya (empty response)");
  return text.trim();
}

function callProvider(p: Provider, messages: Msg[], maxTokens = 1024,
                       timeoutMs = envNumber("AI_TIMEOUT_MS", 60000)) {
  return p.kind === "ollama"
    ? callOllama(p, messages, maxTokens, timeoutMs)
    : callCloud(p, messages, maxTokens, timeoutMs);
}

/** Fallback chain se AI jawab. Sab fail ho to null (caller DB jawab dega). */
export interface AiOutcome {
  text: string | null; // null = koi AI nahi chala, database jawab bane
  provider: string;
  model: string;
  attempts: Attempt[];
}

export async function generateAiAnswer(
  question: string, hits: Hit[]
): Promise<AiOutcome> {
  if ((process.env.AI_MODE || "").toLowerCase() === "off") {
    return { text: null, provider: "", model: "", attempts: [] };
  }
  ollamaCache = null; // har sawaal par Ollama ki taaza halat check karo
  const context = hits
    .map((h) => `[Source: ${h.doc_name}, page ${h.page}]\n${h.text.slice(0, 1200)}`)
    .join("\n\n");
  const messages: Msg[] = [
    {
      role: "system",
      content:
        "Tum ek PDF assistant ho. Sirf diye gaye PDF passages ki base par jawab do, " +
        "bahar ki jaankari mat jodo. Jawab passages mein naa ho to saaf kaho ki PDF mein nahi mila.",
    },
    {
      role: "user",
      content:
        `PASSAGES:\n${context}\n\nSAWAAL: ${question}\n\n` +
        "Jawab usi bhasha mein do jismein sawaal hai (Hindi/Hinglish/English). " +
        "Aakhir mein sources is format mein likho: (Source: file-name, page X)",
    },
  ];
  const attempts: Attempt[] = [];
  for (const p of providerOrder()) {
    if (p.kind === "ollama") {
      const info = await ollamaInfo(p);
      if (!info.running) continue; // Ollama band hai to chup-chaap agli API
      if (!info.hasModel) {
        attempts.push({ provider: p.name, model: p.model, ok: false, ms: 0,
                        error: `Model nahi hai — ollama pull ${p.model}` });
        continue;
      }
    } else if (!env(...p.keyEnvs)) {
      continue; // key hi nahi hai to try hi mat karo
    }
    const t0 = Date.now();
    try {
      const text = await callProvider(p, messages);
      attempts.push({ provider: p.name, model: p.model, ok: true, ms: Date.now() - t0 });
      return { text, provider: p.name, model: p.model, attempts };
    } catch (e: any) {
      attempts.push({
        provider: p.name, model: p.model, ok: false, ms: Date.now() - t0,
        error: String(e?.message || e).slice(0, 200),
      });
      // fail hua -> chain ki agli API try hogi
    }
  }
  // Sab fail — attempts bhi bhejo taaki UI bata sake ki AI try hua tha
  return { text: null, provider: "", model: "", attempts };
}

/** UI ke "keys test karo" button ke liye — har provider ko chhota test call. */
export async function testAiProviders() {
  const results: (Attempt & { configured: boolean; skipped?: string })[] = [];
  ollamaCache = null;
  for (const p of providerOrder()) {
    if (p.kind === "ollama") {
      const info = await ollamaInfo(p);
      if (!info.running) {
        results.push({ provider: p.name, model: p.model, ok: false, ms: 0,
                       configured: false, skipped: "Ollama chal nahi raha — pehle Ollama app/serve chalao" });
        continue;
      }
      if (!info.hasModel) {
        results.push({ provider: p.name, model: p.model, ok: false, ms: 0,
                       configured: true, error: `Model download nahi hai — ollama pull ${p.model}` });
        continue;
      }
      const t0 = Date.now();
      try {
        await callOllama(p, [{ role: "user", content: "Sirf 'OK' likho." }], 16, 60000);
        results.push({ provider: p.name, model: p.model, ok: true, ms: Date.now() - t0, configured: true });
      } catch (e: any) {
        results.push({ provider: p.name, model: p.model, ok: false, ms: Date.now() - t0,
                       configured: true, error: String(e?.message || e).slice(0, 200) });
      }
      continue;
    }
    if (!env(...p.keyEnvs)) {
      results.push({ provider: p.name, model: p.model, ok: false, ms: 0,
                     configured: false, skipped: "key nahi lagi" });
      continue;
    }
    const t0 = Date.now();
    try {
      await callCloud(p, [{ role: "user", content: "Sirf 'OK' likho." }], 16, 30000);
      results.push({ provider: p.name, model: p.model, ok: true, ms: Date.now() - t0, configured: true });
    } catch (e: any) {
      results.push({ provider: p.name, model: p.model, ok: false, ms: Date.now() - t0,
                     configured: true, error: String(e?.message || e).slice(0, 200) });
    }
  }
  return results;
}
