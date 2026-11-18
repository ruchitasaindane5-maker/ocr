// Python extraction worker ko chalana (PDF/OCR Python ka kaam hai,
// database/API Prisma+Node ka). worker.py JSON result likhta hai.
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Extracted } from "./store.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

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
  return new Promise((resolve, reject) => {
    const proc = spawn(
      pythonBin(),
      [path.join(root, "worker.py"), pdfPath, ocrMode, outJson],
      { cwd: root }
    );
    let err = "";
    proc.stderr.on("data", (d) => (err += d.toString()));
    proc.on("error", (e) =>
      reject(new Error(`Python worker start nahi hua (${pythonBin()}): ${e.message}. ` +
        `requirements.txt install kiya hai na? (pip install -r requirements.txt)`)));
    proc.on("close", (code) => {
      if (code !== 0) {
        return reject(new Error(`PDF process fail: ${err.slice(-400) || "unknown error"}`));
      }
      try {
        const data = JSON.parse(fs.readFileSync(outJson, "utf-8")) as Extracted;
        fs.unlinkSync(outJson);
        resolve(data);
      } catch (e) {
        reject(new Error(`Worker result padh nahi paya: ${e}`));
      }
    });
  });
}

let ocrEngineCache: Promise<string | null> | null = null;
export function detectOcrEngine(): Promise<string | null> {
  if (!ocrEngineCache) {
    ocrEngineCache = new Promise((resolve) => {
      const proc = spawn(
        pythonBin(),
        ["-c", "import sys; sys.path.insert(0,'.'); from pdf_ocr_qa import ocr; print(ocr.detect_engine() or '')"],
        { cwd: root }
      );
      let out = "";
      proc.stdout.on("data", (d) => (out += d.toString()));
      proc.on("error", () => resolve(null));
      proc.on("close", () => resolve(out.trim() || null));
    });
  }
  return ocrEngineCache;
}
