/* Opens a visible browser that records itself, for the PRISM dashboard capture (CAPTURE_11). The person signs in and
   walks through the session; closing the window ends the recording, saved as video/captures/CAPTURE_11.webm.
   Run: PW=<path to playwright module> node video/record_prism.cjs */
const { chromium } = require(process.env.PW || "playwright");
const fs = require("fs");
const path = require("path");
const OUT = path.join(__dirname, "captures");
fs.mkdirSync(OUT, { recursive: true });

(async () => {
  const browser = await chromium.launch({ headless: false, args: ["--window-size=1920,1120", "--window-position=0,0"] });
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, recordVideo: { dir: OUT, size: { width: 1920, height: 1080 } } });
  const page = await ctx.newPage();
  await page.goto("https://prism.blockconvey.com");
  console.log("RECORDING. Sign in, open Agent Runs, filter the session helios-2026-09, scrub the steps. Close the window to finish.");
  const done = new Promise((resolve) => { page.on("close", resolve); browser.on("disconnected", resolve); setTimeout(resolve, 25 * 60 * 1000); });
  await done;
  let video;
  try { video = page.video(); } catch (e) {}
  try { await ctx.close(); } catch (e) {}
  if (video) { const p = await video.path(); fs.renameSync(p, path.join(OUT, "CAPTURE_11.webm")); console.log("saved", path.join(OUT, "CAPTURE_11.webm")); }
  try { await browser.close(); } catch (e) {}
})();
