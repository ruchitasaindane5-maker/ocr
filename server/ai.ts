// AI Fallback Chain — Ollama (Local) -> GLM -> NVIDIA -> OpenRouter -> Gemini
// If one fails (Ollama down, bad key, rate limit, timeout) the next one is tried,
// and so on. If all fail, the caller returns the database-search answer.
// Cloud keys come only from .env; Ollama needs no key (runs on the local PC).
import type { Hit } from "./search.js";

export type ProviderId = "ollama" | "glm" | "nvidia" | "openrouter" | "gemini";

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

/** Number from env — falls back to the default on bad values, otherwise NaN broke timeout/context */
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
      // Best for 16GB RAM + 6GB GPU: ~4.7GB, mostly on the GPU, good Hindi support
      model: env("OLLAMA_MODEL") || "qwen2.5:7b",
      freeNote: "Completely free, no internet/key — ollama pull " + (env("OLLAMA_MODEL") || "qwen2.5:7b"),
    },
    {
      id: "glm",
      kind: "cloud",
      name: "GLM (z.ai)",
      keyEnvs: ["GLM_API_KEY", "ZAI_API_KEY"],
      baseUrl: env("GLM_BASE_URL") || "https://api.z.ai/api/paas/v4",
      model: env("GLM_MODEL") || "glm-4.7-flash", // free model on z.ai
      extraBody: { thinking: { type: "disabled" } },
      freeNote: "Free: glm-4.7-flash",
    },
    {
      id: "nvidia",
      kind: "cloud",
      name: "NVIDIA NIM",
      keyEnvs: ["NVIDIA_API_KEY"],
      baseUrl: env("NVIDIA_BASE_URL") || "https://integrate.api.nvidia.com/v1",
      model: env("NVIDIA_MODEL") || "nvidia/nemotron-3.5-lightning-30b-a3b",
      // Reasoning off — otherwise all max_tokens go to "thinking" and the answer comes back empty
      extraBody: { chat_template_kwargs: { enable_thinking: false } },
      freeNote: "Free tier: build.nvidia.com key (nvapi-...)",
    },
    {
      id: "openrouter",
      kind: "cloud",
      name: "OpenRouter",
      keyEnvs: ["OPENROUTER_API_KEY"],
      baseUrl: env("OPENROUTER_BASE_URL") || "https://openrouter.ai/api/v1",
      model: env("OPENROUTER_MODEL") || "nvidia/nemotron-3.5-lightning:free", // ":free" models are free
      // Reasoning off (avoids empty answers); models that can't disable reasoning return 400
      extraBody: { reasoning: { enabled: false } },
      freeNote: "Free: ':free' models (openrouter.ai/keys)",
    },
    {
      id: "gemini",
      kind: "cloud",
      name: "Google Gemini",
      keyEnvs: ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
      baseUrl: env("GEMINI_BASE_URL") || "https://generativelanguage.googleapis.com/v1beta/openai",
      // alias that tracks Google's current lite model — gemini-2.5-flash was closed to new users
      model: env("GEMINI_MODEL") || "gemini-flash-lite-latest",
      freeNote: "Free tier: gemini-flash-lite-latest",
    },
  ];
}

export function providerOrder(): Provider[] {
  const all = getProviders();
  const wanted = (process.env.AI_PROVIDER_ORDER || "ollama,glm,nvidia,openrouter,gemini")
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
  } catch { /* Ollama is not running — keep the default info */ } finally {
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
        configured: info.running, key_env: "no key needed (local)",
        status_text: disabled
          ? "⏸ AI_MODE=off"
          : info.running
            ? (info.hasModel ? "✅ Running · model ready" : "⚠️ Running · model not downloaded yet")
            : "⚠️ Not running (open the Ollama app)",
        free_note: p.freeNote,
        models_downloaded: info.models,
      });
    } else {
      const has = Boolean(env(...p.keyEnvs));
      providers.push({
        order: i + 1, id: p.id, name: p.name, model: p.model,
        configured: has, key_env: p.keyEnvs[0],
        status_text: disabled ? "⏸ AI_MODE=off" : has ? "✅ Key set" : "⚠️ Key not set",
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
    if (e?.name === "AbortError") throw new Error(`Timeout (took longer than ${Math.round(timeoutMs / 1000)}s)`);
    if (e?.cause?.code === "ECONNREFUSED" || /fetch failed/i.test(String(e?.message))) {
      throw new Error("Could not connect (server not running / wrong URL)");
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
    try { msg = JSON.parse(raw)?.error?.message || msg; } catch { /* keep raw */ }
    throw new Error(`HTTP ${r.status}: ${msg}`);
  }
  const text = JSON.parse(raw)?.choices?.[0]?.message?.content;
  if (typeof text !== "string" || !text.trim()) throw new Error("Empty response");
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
          num_ctx: envNumber("OLLAMA_NUM_CTX", 8192), // large context for PDF passages
          num_predict: maxTokens,
        },
      }),
    }, timeoutMs);
  const raw = await r.text();
  if (!r.ok) {
    let msg = raw.slice(0, 200);
    try { msg = JSON.parse(raw)?.error || msg; } catch { /* keep raw */ }
    if (/not found/i.test(msg)) msg = `Model not downloaded — run first: ollama pull ${p.model}`;
    throw new Error(`HTTP ${r.status}: ${msg}`);
  }
  const text = JSON.parse(raw)?.message?.content;
  if (typeof text !== "string" || !text.trim()) throw new Error("Empty response");
  return text.trim();
}

function callProvider(p: Provider, messages: Msg[], maxTokens = 1024,
                       timeoutMs = envNumber("AI_TIMEOUT_MS", 60000)) {
  return p.kind === "ollama"
    ? callOllama(p, messages, maxTokens, timeoutMs)
    : callCloud(p, messages, maxTokens, timeoutMs);
}

/** AI answer from the fallback chain. null if all fail (caller builds the DB answer). */
export interface AiOutcome {
  text: string | null; // null = no AI worked, use the database answer
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
  ollamaCache = null; // check Ollama's current state on every question
  const context = hits
    .map((h) => `[Source: ${h.doc_name}, page ${h.page}]\n${h.text.slice(0, 1200)}`)
    .join("\n\n");
  const messages: Msg[] = [
    {
      role: "system",
      content:
        "You are a PDF assistant. Answer only from the given PDF passages and do not add " +
        "outside information. If the answer is not in the passages, say clearly that it was not found in the PDF.",
    },
    {
      role: "user",
      content:
        `PASSAGES:\n${context}\n\nQUESTION: ${question}\n\n` +
        "Answer in English. " +
        "At the end, list sources in this format: (Source: file-name, page X)",
    },
  ];
  const attempts: Attempt[] = [];
  for (const p of providerOrder()) {
    if (p.kind === "ollama") {
      const info = await ollamaInfo(p);
      if (!info.running) continue; // Ollama is down — silently try the next API
      if (!info.hasModel) {
        attempts.push({ provider: p.name, model: p.model, ok: false, ms: 0,
                        error: `Model not downloaded — ollama pull ${p.model}` });
        continue;
      }
    } else if (!env(...p.keyEnvs)) {
      continue; // no key — don't even try
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
      // failed -> the next API in the chain is tried
    }
  }
  // All failed — still return attempts so the UI can show that AI was tried
  return { text: null, provider: "", model: "", attempts };
}

/** For the UI "test keys" button — a small test call to each provider. */
export async function testAiProviders() {
  const results: (Attempt & { configured: boolean; skipped?: string })[] = [];
  ollamaCache = null;
  for (const p of providerOrder()) {
    if (p.kind === "ollama") {
      const info = await ollamaInfo(p);
      if (!info.running) {
        results.push({ provider: p.name, model: p.model, ok: false, ms: 0,
                       configured: false, skipped: "Ollama not running — start the Ollama app/serve first" });
        continue;
      }
      if (!info.hasModel) {
        results.push({ provider: p.name, model: p.model, ok: false, ms: 0,
                       configured: true, error: `Model not downloaded — ollama pull ${p.model}` });
        continue;
      }
      const t0 = Date.now();
      try {
        await callOllama(p, [{ role: "user", content: "Reply with just 'OK'." }], 16, 60000);
        results.push({ provider: p.name, model: p.model, ok: true, ms: Date.now() - t0, configured: true });
      } catch (e: any) {
        results.push({ provider: p.name, model: p.model, ok: false, ms: Date.now() - t0,
                       configured: true, error: String(e?.message || e).slice(0, 200) });
      }
      continue;
    }
    if (!env(...p.keyEnvs)) {
      results.push({ provider: p.name, model: p.model, ok: false, ms: 0,
                     configured: false, skipped: "key not set" });
      continue;
    }
    const t0 = Date.now();
    try {
      // 16 tokens is too few for reasoning models (nemotron, ernie) — the answer came back empty
      await callCloud(p, [{ role: "user", content: "Reply with just 'OK'." }], 512, 30000);
      results.push({ provider: p.name, model: p.model, ok: true, ms: Date.now() - t0, configured: true });
    } catch (e: any) {
      results.push({ provider: p.name, model: p.model, ok: false, ms: Date.now() - t0,
                     configured: true, error: String(e?.message || e).slice(0, 200) });
    }
  }
  return results;
}
