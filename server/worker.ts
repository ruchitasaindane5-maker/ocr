// Runs the Python extraction worker (PDF/OCR is Python's job,
// database/API is Prisma+Node's). worker.py writes a JSON result.
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Extracted } from "./store.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

// Stall timeout: the worker is killed only if NO page finishes for this long
// (default 10 min). A fixed total limit failed big scanned PDFs — 960 pages of
// OCR at ~5 s/page take over an hour — so the clock restarts after every page.
const WORKER_TIMEOUT_MS = (() => {
  const n = Number(process.env.WORKER_TIMEOUT_MS);
  return Number.isFinite(n) && n > 0 ? n : 10 * 60 * 1000;
})();

export function pythonBin(): string {
  if (process.env.PYTHON_BIN) return process.env.PYTHON_BIN;
  const venvUnix = path.join(root, ".venv", "bin", "python");
  const venvWin = path.join(root, ".venv", "Scripts", "python.exe");
  if (fs.existsSync(venvUnix)) return venvUnix;
  if (fs.existsSync(venvWin)) return venvWin;
  return process.platform === "win32" ? "python" : "python3";
}

export function extractWithPython(
  pdfPath: string, ocrMode: string,
  onProgress?: (done: number, total: number) => void,
): Promise<Extracted> {
  const outJson = pdfPath + ".extracted.json";
  const cleanup = () => { try { fs.unlinkSync(outJson); } catch { /* ignore */ } };
  return new Promise((resolve, reject) => {
    const proc = spawn(
      pythonBin(),
      [path.join(root, "worker.py"), pdfPath, ocrMode, outJson],
      { cwd: root }
    );
    let err = ""; // stderr cap — otherwise huge warnings filled memory
    proc.stderr.on("data", (d) => { if (err.length < 8000) err += d.toString(); });
    let timedOut = false;
    let timer = setTimeout(() => { timedOut = true; proc.kill("SIGKILL"); }, WORKER_TIMEOUT_MS);
    // Always consume stdout (otherwise the pipe fills up and deadlocks);
    // each "PROGRESS done total" line restarts the stall timer.
    let outBuf = "";
    proc.stdout.on("data", (d) => {
      outBuf += d.toString();
      const lines = outBuf.split("\n");
      outBuf = lines.pop() ?? "";
      for (const line of lines) {
        const m = /^PROGRESS (\d+) (\d+)/.exec(line.trim());
        if (!m) continue;
        clearTimeout(timer);
        timer = setTimeout(() => { timedOut = true; proc.kill("SIGKILL"); }, WORKER_TIMEOUT_MS);
        onProgress?.(Number(m[1]), Number(m[2]));
      }
      if (outBuf.length > 4000) outBuf = "";
    });
    proc.on("error", (e) => {
      clearTimeout(timer);
      cleanup();
      reject(new Error(`Python worker failed to start (${pythonBin()}): ${e.message}. ` +
        `Is requirements.txt installed? (pip install -r requirements.txt)`));
    });
    proc.on("close", (code) => {
      clearTimeout(timer);
      if (timedOut) {
        cleanup();
        return reject(new Error(
          `PDF processing stopped: no page finished for ${Math.round(WORKER_TIMEOUT_MS / 60000)} min, ` +
          `so OCR looks stuck. Try again, or raise WORKER_TIMEOUT_MS in .env for very heavy pages.`));
      }
      if (code !== 0) {
        cleanup();
        return reject(new Error(`PDF process fail: ${err.slice(-400) || "unknown error"}`));
      }
      try {
        const data = JSON.parse(fs.readFileSync(outJson, "utf-8")) as Extracted;
        if (!data || !Array.isArray(data.pages) || typeof data.total_chars !== "number") {
          throw new Error("worker returned an incomplete result");
        }
        resolve(data);
      } catch (e) {
        reject(new Error(`Could not read worker result: ${e}`));
      } finally {
        cleanup();
      }
    });
  });
}

let ocrEngineCache: Promise<string | null> | null = null;
export function detectOcrEngine(): Promise<string | null> {
  if (!ocrEngineCache) {
    ocrEngineCache = new Promise((resolve) => {
      let settled = false;
      const done = (v: string | null) => { if (!settled) { settled = true; resolve(v); } };
      try {
        const proc = spawn(
          pythonBin(),
          ["-c", "import sys; sys.path.insert(0,'.'); from pdf_ocr_qa import ocr; print(ocr.detect_engine() or '')"],
          { cwd: root }
        );
        let out = "";
        proc.stdout.on("data", (d) => { if (out.length < 200) out += d.toString(); });
        proc.stderr.on("data", () => { /* warnings ignore */ });
        const timer = setTimeout(() => { proc.kill("SIGKILL"); done(null); }, 30000);
        proc.on("error", () => { clearTimeout(timer); done(null); });
        proc.on("close", () => { clearTimeout(timer); done(out.trim() || null); });
      } catch {
        done(null);
      }
    });
  }
  return ocrEngineCache;
}
