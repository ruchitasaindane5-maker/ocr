/**
 * Capture every real screenshot used by the prototype video, through Playwright MCP.
 *
 *   node tools/capture_prototype_shots.mjs <browser_dir> <out_dir>
 *
 * <browser_dir> must contain node_modules with @playwright/mcp, playwright-core and
 * @sparticuz/chromium (the sandbox has no browser of its own; @sparticuz/chromium
 * ships one, and its al2023.tar.br provides the libnss3/libnspr4 it needs):
 *
 *   mkdir -p brag-output/work/browser && cd brag-output/work/browser
 *   npm init -y && npm i @playwright/mcp playwright-core @sparticuz/chromium
 *   node -e "const z=require('zlib'),f=require('fs');f.writeFileSync('/tmp/a.tar',z.brotliDecompressSync(f.readFileSync('node_modules/@sparticuz/chromium/bin/al2023.tar.br')))" && mkdir -p al2023 && tar -xf /tmp/a.tar -C al2023
 *
 * The app must be running on http://localhost:8000 (npm start).
 * Nothing is deleted: the delete dialog is opened and then cancelled, and the
 * temporary scanned sample used for the live-OCR shot is removed at the end.
 */
import { spawn, execFile } from 'node:child_process';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import { pathToFileURL } from 'node:url';
const { default: Chromium } = await import(pathToFileURL(path.join(
  path.resolve(process.argv[2] || path.join(process.cwd(), 'brag-output', 'work', 'browser')),
  'node_modules', '@sparticuz', 'chromium', 'build', 'index.js')).href);

const here = path.dirname(fileURLToPath(import.meta.url));
const BROWSER = path.resolve(process.argv[2] || path.join(here, '..', 'brag-output', 'work', 'browser'));
const OUT = path.resolve(process.argv[3] || path.join(here, '..', 'brag-output', 'work', 'shots_app'));
const REPO = path.resolve(path.join(here, '..'));
fs.mkdirSync(OUT, { recursive: true });

const exe = await Chromium.executablePath();
const proc = spawn('node', [
  path.join(BROWSER, 'node_modules/@playwright/mcp/cli.js'),
  '--browser', 'chromium', '--headless', '--no-sandbox', '--executable-path', exe,
  '--ignore-roots', '--allow-unrestricted-file-access', '--ignore-https-errors',
  '--device', 'Desktop Chrome HiDPI',
], { cwd: BROWSER, env: { ...process.env, LD_LIBRARY_PATH: path.join(BROWSER, 'al2023', 'lib') }, stdio: ['pipe', 'pipe', 'pipe'] });

let buf = ''; const pending = new Map(); let idc = 1;
proc.stdout.on('data', (d) => {
  buf += d.toString(); let i;
  while ((i = buf.indexOf('\n')) >= 0) {
    const l = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
    if (!l) continue; let m; try { m = JSON.parse(l); } catch { continue; }
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  }
});
proc.stderr.on('data', (d) => process.stderr.write('[mcp] ' + d));
const send = (method, params = {}) => new Promise((res, rej) => {
  const id = idc++; pending.set(id, (m) => (m.error ? rej(new Error(method + ': ' + JSON.stringify(m.error))) : res(m.result)));
  proc.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
});
const call = async (name, args) => {
  const r = await send('tools/call', { name, arguments: args });
  const t = (r.content || []).map((c) => c.text || '').join('');
  if (r.isError) throw new Error(name + ': ' + t.slice(0, 600));
  return t;
};
const run = async (code) => {
  const r = await send('tools/call', { name: 'browser_run_code_unsafe', arguments: { code } });
  const t = (r.content || []).map((c) => c.text || '').join('');
  if (r.isError) throw new Error('run: ' + t.slice(0, 900));
  return t;
};
const shot = async (filename) => {
  const p = path.join(OUT, filename);
  await run(`async (page) => { await page.screenshot({path: ${JSON.stringify(p)}, scale: 'device'}); return 'ok'; }`);
  console.log('saved', filename, fs.statSync(p).size);
};
const getJSON = (u) => fetch(u).then((r) => r.json());

await send('initialize', { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'arena', version: '1' } });
proc.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');

// ---- home + left panel cards
await call('browser_navigate', { url: 'http://localhost:8000' });
await run(`async (page) => {
  await page.setViewportSize({width:1440, height:900});
  await page.waitForFunction(() => (document.querySelector('#dbBadge')||{}).textContent?.includes('PDFs'), null, {timeout: 30000});
  await page.waitForTimeout(1500);
  return 'ready';
}`);
await shot('20_home_hidpi.png');
await run(`async (page) => {
  const cards = page.locator('#side section.card');
  const names = ['21_upload_card_hidpi.png', '22_db_card_hidpi.png', '23_ai_card_hidpi.png', '24_docs_card_hidpi.png'];
  for (let i = 0; i < names.length; i++) {
    const p = ${JSON.stringify(OUT)} + '/' + names[i];
    await cards.nth(i).screenshot({path: p, scale: 'device'});
    console.log('saved', names[i]);
  }
  return 'cards';
}`);

// ---- live OCR progress on an image-only PDF (built by tools/make_scanned_sample.py)
const sample = path.join(REPO, 'brag-output', 'work', 'scanned_sample.pdf');
if (fs.existsSync(sample)) {
  const up = execFile('curl', ['-s', '-m', '900', '-F', `files=@${sample}`, 'http://localhost:8000/api/upload'], { cwd: REPO, maxBuffer: 1 << 24 });
  let out = ''; up.stdout.on('data', (d) => { out += d; });
  await new Promise((r) => setTimeout(r, 9000));
  await shot('26_ocr_progress_full.png');
  console.log('progress:', JSON.stringify(await getJSON('http://localhost:8000/api/progress').catch(() => null)));
  await new Promise((r) => up.on('close', r));
  const docs = await getJSON('http://localhost:8000/api/docs');
  const tmp = docs.find((d) => d.name.includes('scanned_sample'));
  if (tmp) { await fetch('http://localhost:8000/api/docs/' + tmp.id, { method: 'DELETE' }); console.log('deleted sample', tmp.id); }
  await run(`async (page) => { await page.reload({waitUntil:'networkidle'}); await page.waitForTimeout(1200); return 'reloaded'; }`);
  await shot('27_home_after_cleanup.png');
}

// ---- answer + sources
await run(`async (page) => {
  await page.fill('#q', 'What are the 5 steps to set up the GTM Command Center?');
  await page.click('#askBtn');
  await page.locator('.msg.bot .foot').first().waitFor({state:'visible', timeout: 120000});
  await page.waitForTimeout(700);
  const d = page.locator('.msg.bot details.sources').last();
  await d.evaluate(el => el.open = true);
  await page.waitForTimeout(500);
  await page.evaluate(() => document.querySelector('#msgs').scrollTop = 0);
  await page.waitForTimeout(500);
  return 'answered';
}`);
await shot('40_answer_full.png');
await run(`async (page) => { await page.evaluate(() => document.querySelector('#msgs').scrollTop = document.querySelector('#msgs').scrollHeight); await page.waitForTimeout(400); return 's'; }`);
await shot('41_sources_full.png');

// ---- view data, delete confirm (then cancel), mobile
await run(`async (page) => {
  await page.locator('.doc').first().locator('[data-act=view]').click();
  await page.locator('#textDlg[open]').waitFor({state:'visible', timeout: 20000});
  await page.waitForTimeout(700);
  return 'dlg';
}`);
await shot('42_view_data.png');
await call('browser_click', { target: '#closeTextBtn', element: 'Close' });
await run(`async (page) => {
  await page.locator('.doc').first().locator('[data-act=del]').click();
  await page.locator('#confirmDlg[open]').waitFor({state:'visible', timeout: 20000});
  await page.waitForTimeout(400);
  return 'confirm';
}`);
await shot('43_delete_confirm.png');
await call('browser_click', { target: '#confirmNo', element: 'No, keep it' });
await call('browser_resize', { width: 390, height: 844 });
await run(`async (page) => { await page.waitForTimeout(900); return 'm'; }`);
await shot('44_mobile.png');

await call('browser_close', {});
proc.kill();
console.log('DONE');
