// Render video.html frame by frame through the Chrome DevTools Protocol.
// usage: node scripts/render-video.mjs <absolute path to incident-atlas-video.html> <outdir> <fps> [theme]
// then: ffmpeg -framerate 30 -i <outdir>/f%05d.jpg -c:v libx264 -crf 18 -pix_fmt yuv420p docs/media/incident-atlas.mp4
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';

const [,, page, outdir, fpsArg, theme] = process.argv;
const fps = Number(fpsArg || 30);
mkdirSync(outdir, { recursive: true });
const port = 9333;
const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', [
  '--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run', '--window-size=1920,1080',
  `--remote-debugging-port=${port}`, '--user-data-dir=' + outdir + '/.profile', 'about:blank',
], { stdio: 'ignore' });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function targets() {
  for (let i = 0; i < 50; i++) {
    try { const r = await fetch(`http://127.0.0.1:${port}/json`); return await r.json(); } catch { await sleep(200); }
  }
  throw new Error('chrome did not start');
}
const list = await targets();
const target = list.find((t) => t.type === 'page');
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let id = 0; const pending = new Map();
ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
function send(method, params = {}) { return new Promise((resolve) => { const mid = ++id; pending.set(mid, resolve); ws.send(JSON.stringify({ id: mid, method, params })); }); }

await send('Page.enable');
await send('Emulation.setDeviceMetricsOverride', { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
await send('Page.navigate', { url: `file://${page}?t=0${theme ? '&theme=' + theme : ''}` });
await sleep(1500);
const dur = (await send('Runtime.evaluate', { expression: 'window.DURATION', returnByValue: true })).result.result.value;
const total = Math.round(dur * fps);
console.log(`duration ${dur}s, ${total} frames at ${fps} fps`);
const t0 = Date.now();
for (let f = 0; f < total; f++) {
  const t = f / fps;
  await send('Runtime.evaluate', { expression: `window.seek(${t})`, returnByValue: true });
  const shot = await send('Page.captureScreenshot', { format: 'jpeg', quality: 92, captureBeyondViewport: false });
  writeFileSync(`${outdir}/f${String(f).padStart(5, '0')}.jpg`, Buffer.from(shot.result.data, 'base64'));
  if (f % 120 === 0) console.log(`frame ${f}/${total} ${(Date.now() - t0) / 1000}s`);
}
console.log(`done in ${(Date.now() - t0) / 1000}s`);
ws.close(); chrome.kill();
