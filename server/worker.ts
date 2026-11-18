// Python extraction worker ko chalana (PDF/OCR Python ka kaam hai,
// database/API Prisma+Node ka). worker.py JSON result likhta hai.
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Extracted } from "./store.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

// Ek PDF kitni der process ho sakti hai (default 15 min — badi scanned
// PDF par OCR slow hota hai, lekin hamesha ke liye atakna nahi chahiye)
const WORKER_TIMEOUT_MS = (() => {
  const n = Number(process.env.WORKER_TIMEOUT_MS);
  return Number.isFinite(n) && n > 0 ? n : 15 * 60 * 1000;
})();

export function pythonBin(): string {
  if (process.env.PYTHON_BIN) return process.env.PYTHON_BIN;
  const venvUnix = path.join(root, ".venv", "bin", "python");
  const venvWin = path.join(root, ".venv", "Scripts", "python.exe");
  if (fs.existsSync(venvUnix)) return venvUnix;
  if (fs.existsSync(venvWin)) return venvWin;
  return process.platform === "win32" ? "python" : "python3";
}

export function extractWithPython(pdfPath: string, ocrMode: string): Promise<Extracted> {
  const outJson = pdfPath + ".extracted.json";
  const cleanup = () => { try { fs.unlinkSync(outJson); } catch { /* ignore */ } };
  return new Promise((resolve, reject) => {
    const proc = spawn(
      pythonBin(),
      [path.join(root, "worker.py"), pdfPath, ocrMode, outJson],
      { cwd: root }
    );
    let err = ""; // stderr cap — warna badi warning par memory bharti thi
    proc.stderr.on("data", (d) => { if (err.length < 8000) err += d.toString(); });
    proc.stdout.on("data", () => { /* stdout consume karo warna pipe bhar ke deadlock */ });
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; proc.kill("SIGKILL"); }, WORKER_TIMEOUT_MS);
    proc.on("error", (e) => {
      clearTimeout(timer);
      cleanup();
      reject(new Error(`Python worker start nahi hua (${pythonBin()}): ${e.message}. ` +
        `requirements.txt install kiya hai na? (pip install -r requirements.txt)`));
    });
    proc.on("close", (code) => {
      clearTimeout(timer);
      if (timedOut) {
        cleanup();
        return reject(new Error(
          `PDF process timeout ho gaya (${Math.round(WORKER_TIMEOUT_MS / 60000)} min). ` +
          `File bahut badi hai ya OCR atak gaya — OCR mode 'never' ya chhoti file try karo.`));
      }
      if (code !== 0) {
        cleanup();
        return reject(new Error(`PDF process fail: ${err.slice(-400) || "unknown error"}`));
      }
      try {
        const data = JSON.parse(fs.readFileSync(outJson, "utf-8")) as Extracted;
        if (!data || !Array.isArray(data.pages) || typeof data.total_chars !== "number") {
          throw new Error("worker ne adhoora result diya");
        }
        resolve(data);
      } catch (e) {
        reject(new Error(`Worker result padh nahi paya: ${e}`));
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
