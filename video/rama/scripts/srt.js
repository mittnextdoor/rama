/* Scene-level captions from narration.json timings → out/rama_master.srt (and the cutdown's). */
const fs = require("fs"), path = require("path");
const nar = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "narration.json")));
const ends = { 0: 10, 1: 18, 2: 38, 3: 55, 4: 80, 5: 95, 6: 115, 7: 135, 8: 160, 9: 172, 10: 200, 11: 222, 12: 240 };
const ts = (s) => { const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = Math.floor(s % 60), ms = Math.round((s - Math.floor(s)) * 1000); return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")},${String(ms).padStart(3, "0")}`; };
const wrap = (t) => t.replace(/(.{1,80})(\s+|$)/g, "$1\n").trim();
let i = 1, out = "";
for (const sc of nar.scenes) { out += `${i++}\n${ts(sc.start + 0.3)} --> ${ts(Math.min(ends[sc.scene], sc.start + 3 + sc.text.split(" ").length * 0.42))}\n${wrap(sc.text)}\n\n`; }
fs.mkdirSync(path.join(__dirname, "..", "out"), { recursive: true });
fs.writeFileSync(path.join(__dirname, "..", "out", "rama_master.srt"), out);
console.log("wrote out/rama_master.srt", i - 1, "cues");
