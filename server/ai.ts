// Free AI APIs — Fallback Chain (GLM -> NVIDIA -> Gemini)
// Ek fail hui (key galat, rate-limit, timeout, server down) to dusri,
// dusri fail to teesri. Teeno fail to caller database-search jawab dega.
// Keys sirf .env / environment se aati hain — code mein koi key nahi hai.
import type { Hit } from "./search.js";

export type ProviderId = "glm" | "nvidia" | "gemini";

interface Provider {
  id: ProviderId;
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

export function getProviders(): Provider[] {
  return [
    {
      id: "glm",
      name: "GLM (z.ai)",
      keyEnvs: ["GLM_API_KEY", "ZAI_API_KEY"],
      baseUrl: env("GLM_BASE_URL") || "https://api.z.ai/api/paas/v4",
      model: env("GLM_MODEL") || "glm-4.7-flash", // z.ai par free model
      extraBody: { thinking: { type: "disabled" } },
      freeNote: "Free: glm-4.7-flash",
    },
    {
      id: "nvidia",
      name: "NVIDIA NIM",
      keyEnvs: ["NVIDIA_API_KEY"],
      baseUrl: env("NVIDIA_BASE_URL") || "https://integrate.api.nvidia.com/v1",
      model: env("NVIDIA_MODEL") || "meta/llama-3.3-70b-instruct",
      freeNote: "Free tier: build.nvidia.com key (nvapi-...)",
    },
    {
      id: "gemini",
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
  const wanted = (process.env.AI_PROVIDER_ORDER || "glm,nvidia,gemini")
    .split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
  const ordered = wanted
    .map((id) => all.find((p) => p.id === id))
    .filter((p): p is Provider => Boolean(p));
  return ordered.length ? ordered : all;
}

export function aiStatus() {
  const disabled = (process.env.AI_MODE || "").toLowerCase() === "off";
  const providers = providerOrder().map((p, i) => ({
    order: i + 1, id: p.id, name: p.name, model: p.model,
    configured: Boolean(env(...p.keyEnvs)), key_env: p.keyEnvs[0],
    free_note: p.freeNote,
  }));
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

async function callChat(
  p: Provider, messages: { role: string; content: string }[],
  maxTokens = 1024, timeoutMs = Number(process.env.AI_TIMEOUT_MS || 45000)
): Promise<string> {
  const key = env(...p.keyEnvs);
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(`${p.baseUrl.replace(/\/$/, "")}/chat/completions`, {
      method: "POST",
      signal: ctrl.signal,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${key}` },
      body: JSON.stringify({
        model: p.model, messages, temperature: 0.2,
        max_tokens: maxTokens, stream: false, ...(p.extraBody || {}),
      }),
    });
    const raw = await r.text();
    if (!r.ok) {
      let msg = raw.slice(0, 200);
      try { msg = JSON.parse(raw)?.error?.message || msg; } catch { /* raw hi rakho */ }
      throw new Error(`HTTP ${r.status}: ${msg}`);
    }
    const data = JSON.parse(raw);
    const content = data?.choices?.[0]?.message?.content;
    const text = typeof content === "string" ? content.trim() : "";
    if (!text) throw new Error("Khali jawab aaya (empty response)");
    return text;
  } catch (e: any) {
    if (e?.name === "AbortError") throw new Error(`Timeout (${Math.round(timeoutMs / 1000)}s se zyada laga)`);
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

/** Fallback chain se AI jawab. Sab fail ho to null (caller DB jawab dega). */
export async function generateAiAnswer(
  question: string, hits: Hit[]
): Promise<{ text: string; provider: string; model: string; attempts: Attempt[] } | null> {
  if ((process.env.AI_MODE || "").toLowerCase() === "off") return null;
  const context = hits
    .map((h) => `[Source: ${h.doc_name}, page ${h.page}]\n${h.text.slice(0, 1200)}`)
    .join("\n\n");
  const messages = [
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
    if (!env(...p.keyEnvs)) continue; // key hi nahi hai to try hi mat karo
    const t0 = Date.now();
    try {
      const text = await callChat(p, messages);
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
  return null;
}

/** UI ke "keys test karo" button ke liye — har lagi hui key ko chhota call. */
export async function testAiProviders() {
  const results: (Attempt & { configured: boolean; skipped?: string })[] = [];
  for (const p of providerOrder()) {
    if (!env(...p.keyEnvs)) {
      results.push({ provider: p.name, model: p.model, ok: false, ms: 0,
                     configured: false, skipped: "key nahi lagi" });
      continue;
    }
    const t0 = Date.now();
    try {
      const sample = await callChat(p, [{ role: "user", content: "Sirf 'OK' likho." }], 16, 30000);
      results.push({ provider: p.name, model: p.model, ok: true, ms: Date.now() - t0,
                     configured: true, error: undefined });
      void sample;
    } catch (e: any) {
      results.push({ provider: p.name, model: p.model, ok: false, ms: Date.now() - t0,
                     configured: true, error: String(e?.message || e).slice(0, 200) });
    }
  }
  return results;
}
