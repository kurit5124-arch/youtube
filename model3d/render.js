// 3Dモデルのアニメーションを1コマずつ透過PNGに書き出す。
//   node model3d/render.js job.json
// job.json = {"model": "cat", "size": 900, "fps": 30,
//             "scenes": [{"action": "talk", "duration": 6.2, "mouth": [0, 0.3, ...（1コマごと）], "out": "dir"}]}
// Playwright は pip/npm どちらの環境でも使えるよう、require できなければ NODE_PATH を探す。
const fs = require("fs");
const path = require("path");
const http = require("http");

let chromium;
try { ({ chromium } = require("playwright")); } catch (e) { ({ chromium } = require("playwright-core")); }

const job = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const ROOT = __dirname;
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript" };

const server = http.createServer((req, res) => {
  const p = path.join(ROOT, decodeURIComponent(req.url.split("?")[0]));
  if (!p.startsWith(ROOT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "Content-Type": TYPES[path.extname(p)] || "application/octet-stream" });
  fs.createReadStream(p).pipe(res);
});

(async () => {
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const port = server.address().port;
  const size = job.size || 900, fps = job.fps || 30;
  const opts = { args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] };
  if (process.env.CHROMIUM_PATH) opts.executablePath = process.env.CHROMIUM_PATH;
  const browser = await chromium.launch(opts);
  const page = await browser.newPage({ viewport: { width: size, height: size } });
  page.on("pageerror", (e) => console.error("[3d] page error:", e.message));
  await page.goto(`http://127.0.0.1:${port}/${job.model || "cat"}.html?size=${size}`);
  await page.waitForFunction(() => window.ready === true, null, { timeout: 60000 });

  let count = 0;
  const t0 = Date.now();
  for (const sc of job.scenes) {
    fs.mkdirSync(sc.out, { recursive: true });
    const n = Math.max(1, Math.round(sc.duration * fps));
    for (let f = 0; f < n; f++) {
      const m = sc.mouth && sc.mouth.length ? sc.mouth[Math.min(f, sc.mouth.length - 1)] : 0;
      const data = await page.evaluate(([a, t, T, m]) => {
        window.renderFrame(a, t, T, m);
        return document.querySelector("canvas").toDataURL("image/png");
      }, [sc.action, f / fps, sc.duration, m]);
      fs.writeFileSync(path.join(sc.out, `f_${String(f).padStart(5, "0")}.png`), Buffer.from(data.split(",")[1], "base64"));
      count++;
    }
    console.log(`[3d] ${sc.action}: ${n}コマ`);
  }
  console.log(`[3d] 合計 ${count}コマ / ${((Date.now() - t0) / 1000).toFixed(1)}秒`);
  await browser.close();
  server.close();
})().catch((e) => { console.error(e); server.close(); process.exit(1); });
