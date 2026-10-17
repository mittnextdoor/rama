/* The precision layer: every readable thing in the film. Code-rendered type, chips, cards, the amber line. */
import React from "react";
import { AbsoluteFill, Img, OffthreadVideo, Audio, staticFile, useCurrentFrame, useVideoConfig, interpolate, Easing } from "remotion";

export const C = { amber: "#ffb547", flame: "#ff8a00", silver: "#c9d4e5", ember: "#ff5a36", green: "#2ee6a6", grey: "#718096", ink: "#0b0f1f", text: "#f4f6fb", muted: "#a0aec0" };
export const FONT = "Inter, 'Plus Jakarta Sans', Helvetica, Arial, sans-serif";
const ease = Easing.bezier(0.2, 0.8, 0.2, 1);
export const fadeIn = (frame: number, at = 0, len = 12) => interpolate(frame, [at, at + len], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
export const rise = (frame: number, at = 0, len = 14, px = 18) => interpolate(frame, [at, at + len], [px, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });

/** The cinematic layer: a Higgsfield clip, else its keyframe with a slow push, else a labelled placeholder. */
export const Cinematic: React.FC<{ clip?: string | null; keyframe?: string | null; label: string; dim?: number; seconds: number }> = ({ clip, keyframe, label, dim = 0, seconds }) => {
  const frame = useCurrentFrame(); const { fps } = useVideoConfig();
  const scale = interpolate(frame, [0, seconds * fps], [1, 1.08], { extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ background: C.ink }}>
      {clip ? <OffthreadVideo src={staticFile(clip)} style={{ width: "100%", height: "100%", objectFit: "cover" }} muted />
        : keyframe ? <Img src={staticFile(keyframe)} style={{ width: "100%", height: "100%", objectFit: "cover", transform: `scale(${scale})` }} />
        : <AbsoluteFill style={{ display: "grid", placeItems: "center", color: C.muted, fontFamily: FONT, fontSize: 28, background: "#14182b" }}>Higgsfield shot pending · {label}</AbsoluteFill>}
      {dim > 0 && <AbsoluteFill style={{ background: `rgba(5,8,20,${dim})` }} />}
    </AbsoluteFill>
  );
};

/** The proof layer: a real screen capture, else a labelled grey placeholder. */
export const Capture: React.FC<{ src?: string | null; id: string; inset?: number; from?: number }> = ({ src, id, inset = 0, from = 0 }) => (
  <AbsoluteFill style={{ background: C.ink, padding: inset }}>
    {src ? <OffthreadVideo src={staticFile(src)} startFrom={from} style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: inset ? 18 : 0 }} muted />
      : <AbsoluteFill style={{ display: "grid", placeItems: "center", color: C.muted, fontFamily: FONT, fontSize: 30, background: "#2a2f3f", margin: inset, borderRadius: 18 }}>{id} · record this capture</AbsoluteFill>}
  </AbsoluteFill>
);

export const Narration: React.FC<{ src?: string | null }> = ({ src }) => (src ? <Audio src={staticFile(src)} /> : null);
/** Narration that fades out over the last 12 frames before `end` (frames, in the parent's time), never cut hard. */
export const NarrationFaded: React.FC<{ src?: string | null; end: number }> = ({ src, end }) => {
  const frame = useCurrentFrame();
  if (!src) return null;
  const vol = interpolate(frame, [Math.max(0, end - 30), Math.max(1, end - 2)], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return <Audio src={staticFile(src)} volume={vol} />;
};

/** The film's thread: a glowing amber path that draws itself. */
export const AmberLine: React.FC<{ d: string; at?: number; len?: number; width?: number; flame?: boolean; opacity?: number }> = ({ d, at = 0, len = 40, width = 4, flame = false, opacity = 1 }) => {
  const frame = useCurrentFrame();
  const k = interpolate(frame, [at, at + len], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
  const L = 4000;
  return (
    <svg width="100%" height="100%" viewBox="0 0 1920 1080" style={{ position: "absolute", inset: 0, opacity, pointerEvents: "none" }}>
      <defs>
        <filter id="glow"><feGaussianBlur stdDeviation={flame ? 7 : 4} result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
        <linearGradient id="fire" x1="0" x2="1"><stop offset="0" stopColor="#ff3d00" /><stop offset="0.5" stopColor="#ff8a00" /><stop offset="1" stopColor="#ffd166" /></linearGradient>
      </defs>
      <path d={d} fill="none" stroke={flame ? "rgba(255,120,0,.35)" : "rgba(255,181,71,.25)"} strokeWidth={width * 4} strokeLinecap="round" strokeDasharray={L} strokeDashoffset={L * (1 - k)} filter="url(#glow)" />
      <path d={d} fill="none" stroke={flame ? "url(#fire)" : C.amber} strokeWidth={width} strokeLinecap="round" strokeDasharray={L} strokeDashoffset={L * (1 - k)} filter="url(#glow)" />
    </svg>
  );
};

export const Chip: React.FC<{ children: React.ReactNode; at?: number; x: number; y: number; tone?: "amber" | "silver" | "ember" | "green" | "grey" | "red"; small?: boolean; width?: number }> = ({ children, at = 0, x, y, tone = "amber", small = false, width }) => {
  const frame = useCurrentFrame();
  const col = { amber: C.amber, silver: C.silver, ember: C.ember, green: C.green, grey: C.grey, red: "#ff4d4d" }[tone];
  return (
    <div style={{ position: "absolute", left: x, top: y + rise(frame, at), opacity: fadeIn(frame, at), fontFamily: FONT, fontSize: small ? 20 : 24, color: C.text, width,
      background: "rgba(8,12,28,.82)", border: `1px solid ${col}`, borderLeft: `4px solid ${col}`, borderRadius: 12, padding: small ? "8px 14px" : "12px 18px", lineHeight: 1.35, backdropFilter: "blur(10px)" }}>{children}</div>
  );
};

export const Label: React.FC<{ children: React.ReactNode; at?: number; x: number; y: number; size?: number; color?: string; weight?: number; align?: "left" | "center" | "right"; width?: number; italic?: boolean }> = ({ children, at = 0, x, y, size = 28, color = C.text, weight = 500, align = "left", width, italic }) => {
  const frame = useCurrentFrame();
  return <div style={{ position: "absolute", left: x, top: y + rise(frame, at), width, textAlign: align, opacity: fadeIn(frame, at), fontFamily: FONT, fontSize: size, color, fontWeight: weight, fontStyle: italic ? "italic" : "normal", lineHeight: 1.25, textShadow: "0 2px 18px rgba(0,0,0,.7)" }}>{children}</div>;
};

export const Banner: React.FC<{ children: React.ReactNode; at?: number }> = ({ children, at = 0 }) => {
  const frame = useCurrentFrame();
  return <div style={{ position: "absolute", left: 0, right: 0, top: 0, opacity: fadeIn(frame, at), fontFamily: FONT, fontSize: 22, color: C.amber, background: "rgba(40,24,0,.9)", padding: "10px 24px", fontWeight: 700, letterSpacing: 0.3 }}>{children}</div>;
};

export const Footer: React.FC<{ children: React.ReactNode; at?: number }> = ({ children, at = 0 }) => {
  const frame = useCurrentFrame();
  return <div style={{ position: "absolute", left: 0, right: 0, bottom: 0, opacity: fadeIn(frame, at), fontFamily: FONT, fontSize: 19, color: C.muted, background: "rgba(5,8,20,.85)", padding: "12px 28px", lineHeight: 1.4 }}>{children}</div>;
};

/** Scene-level caption from the narration text. */
export const Caption: React.FC<{ text: string }> = ({ text }) => {
  const frame = useCurrentFrame(); const { durationInFrames } = useVideoConfig();
  const out = interpolate(frame, [durationInFrames - 24, durationInFrames - 6], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return <div style={{ position: "absolute", left: 160, right: 160, bottom: 56, textAlign: "center", opacity: fadeIn(frame, 2, 8) * out, fontFamily: FONT, fontSize: 26, color: "#fff", textShadow: "0 2px 14px rgba(0,0,0,.9)", background: "rgba(0,0,0,.35)", borderRadius: 10, padding: "8px 16px" }}>{text}</div>;
};

export const Pulse: React.FC<{ x: number; y: number; r?: number; color?: string; at?: number }> = ({ x, y, r = 18, color = C.ember, at = 0 }) => {
  const frame = useCurrentFrame();
  const k = ((frame - at) % 45) / 45;
  return <div style={{ position: "absolute", left: x - r, top: y - r, width: r * 2, height: r * 2, borderRadius: "50%", background: color, opacity: fadeIn(frame, at), boxShadow: `0 0 ${18 + 30 * k}px ${8 * (1 - k)}px ${color}` }} />;
};

export const Tile: React.FC<{ x: number; y: number; w: number; h: number; title: string; sub?: string; state: "fired" | "clear" | "none" | "pending"; at?: number }> = ({ x, y, w, h, title, sub, state, at = 0 }) => {
  const frame = useCurrentFrame();
  const k = ((frame - at) % 60) / 60;
  const border = state === "fired" ? C.ember : state === "clear" ? C.green : state === "none" ? C.grey : "#2d3350";
  return (
    <div style={{ position: "absolute", left: x, top: y + rise(frame, at, 14, 10), width: w, height: h, opacity: fadeIn(frame, at), borderRadius: 14, fontFamily: FONT, padding: 14, color: C.text,
      background: state === "none" ? "transparent" : "rgba(10,14,34,.9)", border: `${state === "none" ? 2 : 1}px ${state === "none" ? "dashed" : "solid"} ${border}`,
      boxShadow: state === "fired" ? `0 0 ${14 + 22 * k}px rgba(255,90,54,${0.6 * (1 - k)})` : "none" }}>
      <div style={{ fontSize: 20, fontWeight: 700 }}>{title}</div>
      <div style={{ fontSize: 15, color: state === "none" ? C.grey : C.muted, marginTop: 6 }}>{sub || (state === "fired" ? "threshold crossed" : state === "clear" ? "within limits" : state === "none" ? "Not evaluated" : "")}</div>
    </div>
  );
};

export const Card: React.FC<{ x: number; y: number; w: number; title: string; body: string; tag: string; at?: number; opacity?: number }> = ({ x, y, w, title, body, tag, at = 0, opacity = 1 }) => {
  const frame = useCurrentFrame();
  return (
    <div style={{ position: "absolute", left: x, top: y + rise(frame, at, 16, 24), width: w, opacity: fadeIn(frame, at) * opacity, fontFamily: FONT, color: C.text, background: "rgba(10,14,34,.94)", border: "1px solid rgba(255,181,71,.45)", borderRadius: 18, padding: 22 }}>
      <div style={{ fontSize: 15, color: C.amber, fontWeight: 700, letterSpacing: 0.5 }}>{tag}</div>
      <div style={{ fontSize: 24, fontWeight: 700, margin: "8px 0 10px" }}>{title}</div>
      <div style={{ fontSize: 19, color: "#dfe6f3", lineHeight: 1.45 }}>{body}</div>
    </div>
  );
};

export const Table: React.FC<{ rows: [string, string][]; x: number; y: number; w: number; at?: number }> = ({ rows, x, y, w, at = 0 }) => {
  const frame = useCurrentFrame();
  return (
    <div style={{ position: "absolute", left: x, top: y, width: w, fontFamily: FONT, color: C.text, background: "rgba(6,10,26,.94)", border: "1px solid rgba(255,181,71,.35)", borderRadius: 14, overflow: "hidden", opacity: fadeIn(frame, at) }}>
      {rows.map(([k, v], i) => (
        <div key={k} style={{ display: "flex", gap: 20, padding: "12px 18px", borderTop: i ? "1px solid rgba(255,255,255,.08)" : "none", opacity: fadeIn(frame, at + 6 + i * 6), fontSize: 20 }}>
          <div style={{ width: 150, color: C.muted }}>{k}</div><div style={{ flex: 1, fontWeight: 600 }}>{v}</div>
        </div>
      ))}
    </div>
  );
};

export const Cursor: React.FC<{ path: [number, number][]; at?: number; len?: number; click?: number }> = ({ path, at = 0, len = 40, click }) => {
  const frame = useCurrentFrame();
  const k = interpolate(frame, [at, at + len], [0, path.length - 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease });
  const i = Math.min(path.length - 2, Math.floor(k)), t = k - i;
  const x = path[i][0] + (path[i + 1][0] - path[i][0]) * t, y = path[i][1] + (path[i + 1][1] - path[i][1]) * t;
  const clicking = click != null && frame >= click && frame < click + 8;
  return (
    <div style={{ position: "absolute", left: x, top: y, opacity: fadeIn(frame, at, 6), pointerEvents: "none" }}>
      {clicking && <div style={{ position: "absolute", left: -14, top: -14, width: 28, height: 28, borderRadius: "50%", border: `2px solid ${C.amber}`, opacity: 0.8 }} />}
      <svg width="22" height="28" viewBox="0 0 22 28"><path d="M2 2 L2 22 L7 17 L11 26 L15 24 L11 15 L18 15 Z" fill="#fff" stroke="#000" strokeWidth="1.5" /></svg>
    </div>
  );
};
