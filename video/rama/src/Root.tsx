import React from "react";
import { AbsoluteFill, Composition, Sequence } from "remotion";
import { Spark, Title, World, Books, Close, Evidence, Market, Rules, Cards, Guardrail, Release, Hood, Trace, OVERLAP } from "./scenes";
import { CutScene } from "./cut";

const FPS = 30;
const s = (sec: number) => Math.round(sec * FPS);
/* The master: thirteen scenes in the storyline's order; each lasts its narration line plus a tail chosen so the whole
   film runs TARGET seconds (the storyline's 4:00 timings are kept in docs; the film is cut to 3:00). */
import media from "./media.json";
const ORDER: [React.FC<any>, number][] = [[Spark, 0], [Title, 1], [World, 2], [Books, 3], [Close, 4], [Evidence, 5], [Market, 6], [Rules, 7], [Cards, 8], [Guardrail, 9], [Release, 10], [Hood, 11], [Trace, 12]];
const TARGET = Number((media as any).targetSeconds || 180);
const lineSec = (scene: number) => { const f = (media as any).narration?.[String(scene)]; return (f && (media as any).durations?.[f]) || 6; };
const total = ORDER.reduce((a, [, sc]) => a + lineSec(sc), 0);
const MTAIL = Math.max(0.6, (TARGET - total) / ORDER.length);
const TIMELINE: [React.FC<any>, number, number][] = (() => { let t = 0; return ORDER.map(([Scene, sc]) => { const len = lineSec(sc) + MTAIL; const r: [React.FC<any>, number, number] = [Scene, t, t + len]; t += len; return r; }); })();
export const MASTER_TOTAL = s(TIMELINE[TIMELINE.length - 1][2]);

export const Master: React.FC = () => (
  <AbsoluteFill style={{ background: "#070a18" }}>
    {TIMELINE.map(([Scene, a, b], i) => <Sequence key={i} from={Math.max(0, s(a) - OVERLAP)} durationInFrames={s(b - a) + (i ? OVERLAP : 0) + OVERLAP}><Scene /></Sequence>)}
  </AbsoluteFill>
);

/* The 60-second cutdown: each scene lasts as long as its narration line plus a short tail, so the dissolve
   begins when the voice ends (scene order from Part 5) */
const CUT_ORDER = [0, 4, 5, 7, 8, 10, 12];
const TAIL = 2.5;                                            // seconds after the line ends before the dissolve begins
const cutFrames = (scene: number) => { const f = (media as any).cutNarration?.[String(scene)]; const d = f ? (media as any).durations?.[f] : 0; return Math.max(120, Math.round(((d || 2) + TAIL) * FPS)) + (scene === 12 ? 90 : 0); };
const CUT: [number, number, number][] = (() => { let t = 0; return CUT_ORDER.map((sc) => { const len = cutFrames(sc); const r: [number, number, number] = [sc, t, t + len]; t += len; return r; }); })();
export const CUT_TOTAL = CUT[CUT.length - 1][2];
export const Cutdown: React.FC = () => (
  <AbsoluteFill style={{ background: "#070a18" }}>
    {CUT.map(([scene, a, b], i) => <Sequence key={i} from={Math.max(0, a - OVERLAP)} durationInFrames={b - a + (i ? OVERLAP : 0) + OVERLAP}><CutScene scene={scene} /></Sequence>)}
  </AbsoluteFill>
);

export const Root: React.FC = () => (
  <>
    <Composition id="Master" component={Master} durationInFrames={MASTER_TOTAL} fps={FPS} width={1920} height={1080} />
    <Composition id="Cutdown" component={Cutdown} durationInFrames={CUT_TOTAL} fps={FPS} width={1920} height={1080} />
  </>
);
