/* Scene-level captions from the narration lines, timed like Root.tsx: each scene = its line + a tail chosen so the
   film runs targetSeconds (180). Writes out/rama_master.srt. */
const fs = require("fs"), path = require("path");
const root = path.join(__dirname, "..", "..");
const nar = JSON.parse(fs.readFileSync(path.join(root, "narration.json")));
const media = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "src", "media.json")));
const TARGET = Number(media.targetSeconds || 180), OVERLAP = 18 / 30;
const lineSec = (sc) => { const f = media.narration?.[String(sc.scene)]; return (f && media.durations?.[f]) || 6; };
const total = nar.scenes.reduce((a, sc) => a + lineSec(sc), 0);
const tail = Math.max(0.6, (TARGET - total) / nar.scenes.length);
const ts = (s) => { const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = Math.floor(s % 60), ms = Math.round((s - Math.floor(s)) * 1000); return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")},${String(ms).padStart(3, "0")}`; };
const wrap = (t) => t.replace(/(.{1,80})(\s+|$)/g, "$1\n").trim();
let t = 0, i = 1, out = "";
for (const sc of nar.scenes) { const start = t + OVERLAP, end = t + OVERLAP + lineSec(sc); out += `${i++}\n${ts(start)} --> ${ts(end)}\n${wrap(sc.text)}\n\n`; t += lineSec(sc) + tail; }
fs.mkdirSync(path.join(__dirname, "..", "out"), { recursive: true });
fs.writeFileSync(path.join(__dirname, "..", "out", "rama_master.srt"), out);
console.log("wrote out/rama_master.srt", i - 1, "cues, film", t.toFixed(1), "s");
