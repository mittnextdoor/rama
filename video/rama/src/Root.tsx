import React from "react";
import { AbsoluteFill, Composition, Sequence } from "remotion";
import { Spark, Title, World, Books, Close, Evidence, Market, Rules, Cards, Guardrail, Release, Hood, Trace, OVERLAP } from "./scenes";
import { CutScene } from "./cut";

const FPS = 30;
const s = (sec: number) => Math.round(sec * FPS);
/* [component, start, end] in seconds, from the storyline */
const TIMELINE: [React.FC, number, number][] = [
  [Spark, 0, 10], [Title, 10, 18], [World, 18, 38], [Books, 38, 55], [Close, 55, 80], [Evidence, 80, 95], [Market, 95, 115],
  [Rules, 115, 135], [Cards, 135, 160], [Guardrail, 160, 172], [Release, 172, 200], [Hood, 200, 222], [Trace, 222, 240],
];

export const Master: React.FC = () => (
  <AbsoluteFill style={{ background: "#070a18" }}>
    {TIMELINE.map(([Scene, a, b], i) => <Sequence key={i} from={Math.max(0, s(a) - OVERLAP)} durationInFrames={s(b - a) + (i ? OVERLAP : 0) + OVERLAP}><Scene /></Sequence>)}
  </AbsoluteFill>
);

/* The 60-second cutdown: each scene lasts as long as its narration line plus a short tail, so the dissolve
   begins when the voice ends (scene order from Part 5) */
import media from "./media.json";
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
    <Composition id="Master" component={Master} durationInFrames={s(240)} fps={FPS} width={1920} height={1080} />
    <Composition id="Cutdown" component={Cutdown} durationInFrames={CUT_TOTAL} fps={FPS} width={1920} height={1080} />
  </>
);
