// 3D場面を1コマずつ JPEG に書き出す。
// node render.js <場面名> '<params JSON>' <秒数> <fps> <出力フォルダ> [幅] [高さ]
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

(async () => {
  const [name, paramsJson, durS, fpsS, outDir, wS, hS] = process.argv.slice(2);
  const dur = parseFloat(durS), fps = parseInt(fpsS, 10);
  const w = parseInt(wS || '1920', 10), h = parseInt(hS || '1080', 10);
  fs.mkdirSync(outDir, { recursive: true });
  const exe = process.env.CHROMIUM_PATH || undefined;
  const browser = await chromium.launch({
    executablePath: exe,
    args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
  });
  const page = await browser.newPage({ viewport: { width: w, height: h } });
  page.on('pageerror', (e) => { console.error('[3d] page error:', e.message); process.exitCode = 1; });
  const root = __dirname;
  await page.route('http://sim.local/**', (route) => {
    const p = path.join(root, new URL(route.request().url()).pathname);
    const type = p.endsWith('.js') ? 'text/javascript' : 'text/html';
    route.fulfill({ status: 200, contentType: type, body: fs.readFileSync(p) });
  });
  await page.goto('http://sim.local/page.html');
  await page.waitForFunction('window.ready === true');
  await page.evaluate(([n, pr, d, ww, hh]) => window.init(n, pr, d, ww, hh), [name, JSON.parse(paramsJson || '{}'), dur, w, h]);
  const n = Math.max(1, Math.round(dur * fps));
  const t0 = Date.now();
  for (let i = 0; i < n; i++) {
    await page.evaluate((t) => window.renderAt(t), i / fps);
    const buf = await page.screenshot({ type: 'jpeg', quality: 92 });
    fs.writeFileSync(path.join(outDir, `${String(i).padStart(5, '0')}.jpg`), buf);
    if (i % 60 === 0) console.log(`[3d] ${name} ${i}/${n} (${((Date.now() - t0) / 1000).toFixed(0)}秒)`);
  }
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
