/* Writes src/media.json: which keyframes, clips, captures and narration files exist, so the composition can render
   placeholders for anything not generated yet. Run before `remotion render`. */
const fs = require("fs"), path = require("path");
const root = path.join(__dirname, "..", "..");
const shots = JSON.parse(fs.readFileSync(path.join(root, "shotlist.json")));
const sel = fs.existsSync(path.join(root, "selection.json")) ? JSON.parse(fs.readFileSync(path.join(root, "selection.json"))) : {};
const ex = (p) => fs.existsSync(path.join(root, p));
const media = { shots: {}, captures: {}, narration: {} };
for (const s of shots.higgsfield_shots) {
  const v = sel[s.id] ?? 0;
  const clip = `higgsfield/${s.id}_v${v}.mp4`, key = `higgsfield/${s.id}_v${v}.png`;
  media.shots[s.id] = { clip: ex(clip) ? clip : null, keyframe: ex(key) ? key : null, variant: v };
}
for (const c of shots.captures) { const f = `captures/${c.id}.webm`; media.captures[c.id] = ex(f) ? f : null; }
const nar = JSON.parse(fs.readFileSync(path.join(root, "narration.json")));
for (const sc of nar.scenes) { const f = `narration/scene${String(sc.scene).padStart(2, "0")}.mp3`; media.narration[sc.scene] = ex(f) ? f : null; }
media.cutNarration = {};
for (const sc of nar.cut_scenes || []) { const f = `narration/cut${String(sc.scene).padStart(2, "0")}.mp3`; media.cutNarration[sc.scene] = ex(f) ? f : null; }
// narration durations (seconds), so the cutdown's scenes can follow the voice
const { execSync } = require("child_process");
media.durations = {};
for (const f of fs.readdirSync(path.join(root, "narration"))) {
  if (!/\.mp3$/.test(f)) continue;
  try { const out = execSync(`npx remotion ffprobe "${path.join(root, "narration", f)}" 2>&1`).toString(); const m = out.match(/Duration: (\d+):(\d+):([\d.]+)/); if (m) media.durations["narration/" + f] = +m[1] * 3600 + +m[2] * 60 + +m[3]; } catch (e) {}
}
media.prismSecond = Number(process.env.PRISM_SECOND || (fs.existsSync(path.join(root, "selection.json")) ? (JSON.parse(fs.readFileSync(path.join(root, "selection.json"))).prism_second_frames || 1500) : 1500));
media.prismFrom = Number(process.env.PRISM_FROM || (fs.existsSync(path.join(root, "selection.json")) ? (JSON.parse(fs.readFileSync(path.join(root, "selection.json"))).prism_from_frames || 0) : 0));
fs.writeFileSync(path.join(__dirname, "..", "src", "media.json"), JSON.stringify(media, null, 1));
console.log(JSON.stringify(media));
// copy the media into public/ (Remotion's server doesn't follow symlinks)
for (const d of ["higgsfield", "captures", "narration"]) {
  const src = path.join(root, d), dst = path.join(__dirname, "..", "public", d);
  fs.mkdirSync(dst, { recursive: true });
  if (fs.existsSync(src)) for (const f of fs.readdirSync(src)) { if (!/\.(png|mp4|webm|mp3|wav)$/.test(f)) continue; const s = path.join(src, f), t = path.join(dst, f); if (!fs.existsSync(t) || fs.statSync(t).mtimeMs < fs.statSync(s).mtimeMs) fs.copyFileSync(s, t); }
}
