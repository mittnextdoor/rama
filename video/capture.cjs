/* Records the RAMA app journey as the film's capture clips (video/captures/CAPTURE_xx.webm), driving the real app on
   port 8810 through its API and screens. Run: PW=<path to playwright module> node video/capture.cjs */
const { chromium } = require(process.env.PW || "playwright");
const fs = require("fs");
const path = require("path");
const B = process.env.RAMA || "http://127.0.0.1:8810";
const OUT = path.join(__dirname, "captures");
fs.mkdirSync(OUT, { recursive: true });

const api = async (p, body) => { const r = await fetch(B + p, { method: body === undefined ? "GET" : "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) }); return r.json(); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function idle() { for (let i = 0; i < 180; i++) { const s = await api("/api/state"); if (!s.busy) return s; await sleep(1000); } throw new Error("busy too long"); }

async function record(name, fn) {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, recordVideo: { dir: OUT, size: { width: 1920, height: 1080 } }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  const errs = []; page.on("pageerror", (e) => errs.push(e.message));
  try { await fn(page); } catch (e) { console.log(name, "ERROR", e.message); }
  await sleep(600);
  const v = page.video();
  await ctx.close();
  const p = await v.path();
  fs.renameSync(p, path.join(OUT, name + ".webm"));
  await browser.close();
  console.log("captured", name, errs.length ? "errors: " + errs.join(" | ") : "");
}
const go = async (page, hash) => { await page.goto(B + "/#" + hash); await page.waitForTimeout(1600); };
async function hover(page, sel, ms = 900) { const el = await page.$(sel); if (el) { await el.hover(); await page.waitForTimeout(ms); } }
async function click(page, sel, ms = 1200) { await page.click(sel); await page.waitForTimeout(ms); }

(async () => {
  await api("/api/reset", {});
  // CAPTURE_03: the source package
  await record("CAPTURE_03", async (page) => { await go(page, "close"); await page.waitForTimeout(2500); await hover(page, ".stepc", 1500); });
  // CAPTURE_04: the close runs; the break and the exception
  await record("CAPTURE_04", async (page) => {
    await go(page, "close"); await click(page, "text=Run the close", 500);
    await idle(); await page.waitForTimeout(2500);
    await hover(page, ".exc:has-text('booked as')", 2500);
    await hover(page, ".exc:has-text('MISC FEE')", 2500);
    await hover(page, ".exc:has-text('booked as') .btn.green", 1200);
  });
  // the reviewer's decisions (off camera, through the API) then CAPTURE_05: the evidence reveal
  const s = await idle();
  const split = s.close.final.findings.find((f) => f.check === "pik_split");
  const fee = s.close.final.findings.find((f) => f.check === "unrecorded");
  await api("/api/close/resolve", { key: split.key, decision: { action: "accept_pik_split" } }); await idle();
  await api("/api/close/resolve", { key: fee.key, decision: { action: "leave_open", note: "no support; immaterial" } }); await idle();
  await record("CAPTURE_05", async (page) => {
    await go(page, "close"); await page.waitForTimeout(1200);
    await click(page, "tr:has-text('Operating Account') >> nth=0", 2200);
    const hl = await page.$(".drawer tr.hl"); if (hl) { await hl.scrollIntoViewIfNeeded(); await hl.hover(); await page.waitForTimeout(2500); }
    await click(page, ".drawer .btn.ghost", 600);
    await click(page, "tr:has-text('Term Loan L2')", 2500);
    await hover(page, ".drawer .hl", 2000);
  });
  // CAPTURE_07: the indicators build
  await record("CAPTURE_07", async (page) => {
    await go(page, "intelligence"); await click(page, "text=Build indicators", 500);
    await idle(); await page.waitForTimeout(3500);
    await hover(page, ".ind:has-text('Valuation gap')", 2200);
    await hover(page, ".ind:has-text('Income quality')", 1500);
  });
  // CAPTURE_08: open the indicator, then the card's explanation
  await record("CAPTURE_08", async (page) => {
    await go(page, "intelligence"); await click(page, ".ind:has-text('Refinancing wall')", 2600);
    const sl = await page.$("#detail input[type=range]"); if (sl) { const bb = await sl.boundingBox(); await page.mouse.move(bb.x + bb.width * 0.4, bb.y + bb.height / 2); await page.mouse.down(); await page.mouse.move(bb.x + bb.width * 0.15, bb.y + bb.height / 2, { steps: 20 }); await page.mouse.up(); await page.waitForTimeout(1500); await page.mouse.move(bb.x + bb.width * 0.4, bb.y + bb.height / 2, { steps: 10 }); }
    await go(page, "review"); await page.waitForTimeout(800);
    const card = await page.$(".icard:has-text('Refinancing wall')"); if (card) { await card.scrollIntoViewIfNeeded(); await (await card.$("button:has-text('Explain')")).click(); await page.waitForTimeout(3500); }
  });
  // CAPTURE_09: the guardrail test
  await record("CAPTURE_09", async (page) => {
    await go(page, "review"); const ta = await page.$("#guard-text"); await ta.scrollIntoViewIfNeeded(); await ta.fill("");
    await ta.type("Should Hudson sell its stake in the fund? Hudson should reduce its commitment and rebalance into safer funds.", { delay: 28 });
    await click(page, "button:has-text('Run test')", 500); await idle(); await page.waitForTimeout(3000);
  });
  // CAPTURE_10a: approvals, one card held, the release line
  await record("CAPTURE_10a", async (page) => {
    await go(page, "review");
    const st = await api("/api/state");
    const ids = st.cards.filter((c) => c.publishable).map((c) => c.id);
    for (const id of ids.slice(0, 3)) { const c = await page.$(`.icard:has(button[onclick*="'${id}'"]) button.btn.green`); if (c) { await c.scrollIntoViewIfNeeded(); await c.click(); await page.waitForTimeout(1500); } }
    page.once("dialog", (d) => d.accept("Hold — confirm with deal team"));
    const rej = await page.$(`.icard:has(button[onclick*="'${ids[3]}'"]) button.btn.ghost:has-text('Reject')`); if (rej) { await rej.scrollIntoViewIfNeeded(); await rej.click(); await page.waitForTimeout(1500); }
    await page.evaluate(() => scrollTo(0, 0)); await page.waitForTimeout(800);
    await click(page, "button.btn.fire", 4200);
  });
  // CAPTURE_10b: the destination
  await record("CAPTURE_10b", async (page) => { await go(page, "chronograph"); await page.waitForTimeout(3000); await page.evaluate(() => scrollTo({ top: 600, behavior: "smooth" })); await page.waitForTimeout(2500); });
  // CAPTURE_12: trace back from a note to the indicator to the lender statement and the bank line
  await record("CAPTURE_12", async (page) => {
    await go(page, "chronograph"); const link = await page.$(".rn:has-text('Income quality') a"); if (link) { await link.scrollIntoViewIfNeeded(); await page.waitForTimeout(800); await link.click(); await page.waitForTimeout(2600); }
    await go(page, "close"); await click(page, "tr:has-text('Term Loan L2')", 2200); await click(page, ".drawer .btn.ghost", 500);
    await click(page, "tr:has-text('Operating Account') >> nth=0", 2000); const hl = await page.$(".drawer tr.hl"); if (hl) { await hl.scrollIntoViewIfNeeded(); await hl.hover(); await page.waitForTimeout(2500); }
  });
  // CAPTURE_11 is the PRISM dashboard: recorded by hand after sign-in.
  console.log("done");
})();
