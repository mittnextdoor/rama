/* One component per scene of the storyline. Times inside a scene are frames at 30 fps (so 30 = one second). */
import React from "react";
import { AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig, interpolate } from "remotion";
import media from "./media.json";
import nar from "./narration.json";
import { Cinematic, Capture, Narration, NarrationFaded, AmberLine, Chip, Label, Banner, Footer, Caption, Pulse, Tile, Card, Table, Cursor, C, FONT, fadeIn } from "./ui";

const shot = (id: string) => (media as any).shots[id] || {};
const cap = (id: string) => (media as any).captures[id];
const voice = (scene: number) => (media as any).narration[String(scene)];
export const cutVoice = (scene: number) => ((media as any).cutNarration || {})[String(scene)] || null;
export const cutLine = (scene: number) => ((nar as any).cut_scenes || []).find((s: any) => s.scene === scene)?.text || line(scene);
const line = (scene: number) => (nar as any).scenes.find((s: any) => s.scene === scene)?.text || "";
export const DISCLOSURE = "Risk analytics based on your fund's reported data and third-party market data as of the dates shown. Estimates depend on stated assumptions. Not investment advice.";
export const DEST_LABEL = "Demonstration destination — no live Chronograph connection.";
export const PRISM_FROM = Number((media as any).prismFrom || 0);   // frames of the PRISM recording to skip (the sign-in)
export const PRISM_SECOND = Number((media as any).prismSecond || 1500);  // frames from the first window to the guardrail trace
export const APP = { accrued: "$5.75M", cash: "$4.00M", pik: "$1.75M", fee: "$14,800", r1: "17.6%", r1Limit: "5%", r5: "98.5%", r5Origination: "65%", lpL2: "$75.4M", nav: "$1,698.5M" };

/** The scene's length in frames (its Sequence), so internal beats scale when the film is cut shorter. */
const useLen = () => useVideoConfig().durationInFrames;
export type SceneProps = { voiceSrc?: string | null; captionText?: string; cut?: boolean };
export const OVERLAP = 18;                                   // frames of cross-dissolve between scenes (0.6 s)
/** A scene: fades in over the previous one, its narration starts after the dissolve and fades at the scene's end. */
const Wrap: React.FC<{ scene: number; children: React.ReactNode; caption?: boolean; voiceSrc?: string | null; captionText?: string }> = ({ scene, children, caption = true, voiceSrc, captionText }) => {
  const frame = useCurrentFrame(); const { durationInFrames } = useVideoConfig();
  const opacity = interpolate(frame, [0, OVERLAP], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const src = voiceSrc === undefined ? voice(scene) : voiceSrc;
  return (
    <AbsoluteFill style={{ opacity }}>{children}
      <Sequence from={OVERLAP}><NarrationFaded src={src} end={durationInFrames - OVERLAP} /></Sequence>
      {caption && <Caption text={captionText ?? line(scene)} />}</AbsoluteFill>
  );
};

// 0 — The Spark
export const Spark: React.FC<SceneProps> = (props) => (
  <Wrap scene={0} {...props}><Cinematic {...shot("spark")} label="spark" seconds={10} /></Wrap>
);

// 1 — Title
export const Title: React.FC<SceneProps> = (props) => {
  const frame = useCurrentFrame();
  return (
    <Wrap scene={1} {...props}>
      <Cinematic {...shot("title")} label="title" seconds={8} dim={0.25} />
      <AmberLine d="M 120 560 L 1800 560" at={0} len={30} width={5} />
      <Label x={0} y={400} width={1920} align="center" size={96} weight={800} at={14} color="#fff">RAMA</Label>
      <Label x={0} y={600} width={1920} align="center" size={34} weight={400} at={26} color={C.amber} italic>From books to foresight</Label>
    </Wrap>
  );
};

// 2 — The World
export const World: React.FC<SceneProps> = (props) => {
  const frame = useCurrentFrame();
  const nodes: [string, number, number][] = [["L1", 420, 420], ["L2", 560, 300], ["L3", 760, 240], ["L4", 960, 260], ["L5", 1150, 330], ["L6", 1290, 440]];
  const dimK = interpolate(frame, [90, 150], [0, 0.55], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <Wrap scene={2} {...props}>
      <Cinematic {...shot("campus")} label="campus" seconds={20} dim={dimK} />
      <Chip x={80} y={80} at={30} tone="silver" small>U.S. private credit default rate: <b>6.0%</b>, a record · Fitch Ratings, Q2 2026</Chip>
      <svg width="100%" height="100%" viewBox="0 0 1920 1080" style={{ position: "absolute", inset: 0 }}>
        {nodes.map(([n, x, y], i) => <g key={n} opacity={fadeIn(frame, 150 + i * 8)}><line x1={x} y1={y} x2={860} y2={640} stroke={C.amber} strokeOpacity={0.5} strokeWidth={2} /><circle cx={x} cy={y} r={n === "L2" ? 22 : 16} fill={n === "L2" ? C.amber : "#1a1f37"} stroke={C.amber} strokeWidth={2} /><text x={x} y={y + 6} textAnchor="middle" fontFamily={FONT} fontSize={16} fontWeight={700} fill={n === "L2" ? "#1a0d00" : "#fff"}>{n}</text></g>)}
        <g opacity={fadeIn(frame, 200)}><circle cx={860} cy={640} r={34} fill="#0b1035" stroke={C.amber} strokeWidth={3} /><text x={860} y={646} textAnchor="middle" fontFamily={FONT} fontSize={16} fontWeight={700} fill="#fff">FUND</text>
          <line x1={894} y1={640} x2={1400} y2={760} stroke={C.amber} strokeOpacity={0.6} strokeWidth={2} /><circle cx={1400} cy={760} r={30} fill="#0b1035" stroke={C.silver} strokeWidth={3} /><text x={1400} y={766} textAnchor="middle" fontFamily={FONT} fontSize={16} fontWeight={700} fill="#fff">LP</text></g>
      </svg>
      <Label x={700} y={690} at={210} size={22} color={C.text}>RAMA Credit Fund I · <span style={{ color: C.muted }}>Synthetic fund · six loans to AI infrastructure</span></Label>
      <Label x={1240} y={810} at={240} size={22}>Hudson State Teachers' Pension · <span style={{ color: C.muted }}>Synthetic LP</span></Label>
      <Pulse x={560} y={300} color={C.amber} at={300} />
      <Chip x={60} y={160} at={330} tone="amber">Helios Compute · <span style={{ color: C.muted }}>Synthetic borrower · Public proxy: CRWV</span><br /><span style={{ fontSize: 18, color: C.muted }}>Loan L2 · GPU-backed · {APP.lpL2} Hudson look-through exposure</span></Chip>
      <AmberLine d="M 560 300 C 480 240, 420 230, 380 240" at={335} len={20} width={3} />
      <Cursor path={[[1500, 900], [600, 320]]} at={300} len={40} click={345} />
    </Wrap>
  );
};

// 3 — The Books Arrive
export const Books: React.FC<SceneProps> = (props) => { const L = useLen(), a = Math.round(L * 0.4); return (
  <Wrap scene={3} {...props}>
    <Sequence from={0} durationInFrames={a}><Cinematic {...shot("documents")} label="documents" seconds={7} /></Sequence>
    <Sequence from={a}><Capture src={cap("CAPTURE_03")} id="CAPTURE_03" inset={40} />
      <Chip x={120} y={120} at={20} tone="green" small>Bank statement · Operating · Sept 2026 ✓</Chip>
      <Chip x={120} y={180} at={40} tone="green" small>Bank statement · Debt service reserve · Sept 2026 ✓</Chip>
      <Chip x={120} y={240} at={60} tone="green" small>Lender statement · Loan L2 · Sept 2026 ✓</Chip>
      <Chip x={120} y={300} at={80} tone="green" small>PIK election notice · Loan L2 · 2026-09-15 ✓</Chip>
    </Sequence>
  </Wrap>
); };

// 4 — The Close
export const Close: React.FC<SceneProps> = (props) => (
  <Wrap scene={4} {...props}>
    <Capture src={cap("CAPTURE_04")} id="CAPTURE_04" />
    <Chip x={1180} y={120} at={200} tone="amber" width={640}>Ledger · interest on L2, booked as paid in cash<br /><b style={{ fontSize: 30 }}>{APP.accrued}</b></Chip>
    <Chip x={1180} y={240} at={230} tone="amber" width={640}>Bank · wire received by the lender<br /><b style={{ fontSize: 30 }}>{APP.cash}</b></Chip>
    <Pulse x={1160} y={330} color={C.amber} at={260} />
    <Chip x={1180} y={360} at={290} tone="silver" width={640}>Agent: the difference, <b>{APP.pik}</b>, matches the PIK election notice of 2026-09-15 (p.1): paid in kind, added to the loan. Source: notice; bank line S1000-09-008.</Chip>
    <Chip x={1180} y={520} at={420} tone="red" width={640}>Unidentified fee <b>{APP.fee}</b> · no support · left as an exception<br /><span style={{ fontSize: 18, color: C.muted }}>RAMA won't force this to balance.</span></Chip>
  </Wrap>
);

// 5 — Evidence reveal
export const Evidence: React.FC<SceneProps> = (props) => (
  <Wrap scene={5} {...props}>
    <Capture src={cap("CAPTURE_05")} id="CAPTURE_05" />
    <Chip x={1380} y={80} at={100} tone="green" small>✓ Agreed to bank statement · line S1000-09-008</Chip>
    <Chip x={1380} y={140} at={120} tone="green" small>✓ Agreed to PIK election notice · p.1</Chip>
  </Wrap>
);

// 6 — The Market Speaks
export const Market: React.FC<SceneProps> = (props) => {
  const chips = [
    ["CRWV (proxy) · S&P B+ · Net debt/EBITDA 8.2x · EBITDA/interest 3.0x", "S&P Capital IQ Pro · 2026-10-16"],
    ["Oracle · S&P BBB-, downgraded 2026-07-09", "S&P Global Ratings via Capital IQ Pro"],
    ["Oracle · Force majeure notice, Project Jupiter · 2026-09-24", "Bloomberg / Reuters reporting"],
    ["H100 rental: $8–10/hr (2024) → $1.80–3.50/hr (Q2 2026)", "public trackers · non-S&P"],
  ];
  return (
    <Wrap scene={6} {...props}>
      <Cinematic {...shot("threads")} label="threads" seconds={20} dim={0.2} />
      <Chip x={80} y={80} at={10} tone="silver" small><span style={{ color: C.amber }}>■</span> Amber = verified books &nbsp;&nbsp; <span style={{ color: C.silver }}>■</span> Silver = dated market evidence</Chip>
      {chips.map(([t, s], i) => <Chip key={t} x={1040} y={300 + i * 140} at={120 + i * 70} tone="silver" width={800}>{t}<br /><span style={{ fontSize: 17, color: C.muted }}>{s}</span></Chip>)}
    </Wrap>
  );
};

// 7 — The Rules
export const Rules: React.FC<SceneProps> = (props) => {
  const frame = useCurrentFrame();
  const tiles: [string, "fired" | "clear" | "none", string?][] = [
    ["Income quality", "fired", `${APP.r1} of NAV vs ${APP.r1Limit}`], ["Tenant concentration", "fired", "34.0% vs 25% cap"], ["Tenant credit drift", "fired", "ORCL BBB-, downgraded"], ["Tenant / project event", "fired", "force majeure 2026-09-24"],
    ["GPU collateral value", "fired", `LTV ${APP.r5} vs ${APP.r5Origination}`], ["Contract cover", "none", "input not pulled"], ["Refinancing wall", "fired", "CRWV 8.2x vs 6.0x"],
    ["Power / construction", "none", "input not pulled"], ["Market supply", "none", "input not pulled"], ["Valuation gap", "none", "no price history"], ["Rating divergence", "fired", "B+ vs GP 'performing'"],
    ["LP liquidity", "fired", "net calls $45.0M vs $40.0M floor"], ["Fund leverage headroom", "fired", "11.5% vs 15% floor"], ["Covenant headroom", "fired", "L2 9.7% vs 10% floor"],
  ];
  return (
    <Wrap scene={7} {...props}>
      <AbsoluteFill style={{ background: "radial-gradient(900px 500px at 50% 30%, #141a3a, #070a18)" }} />
      <Label x={120} y={70} at={0} size={34} weight={700}>Fourteen fixed rules · <span style={{ color: C.muted, fontWeight: 400 }}>thresholds from Hudson's policy, the loan documents, or labeled defaults</span></Label>
      {tiles.map(([t, s, sub], i) => <Tile key={t} x={120 + (i % 7) * 243} y={160 + Math.floor(i / 7) * 150} w={225} h={126} title={t} sub={sub} state={s} at={20 + i * 10} />)}
      <AmberLine d="M 1100 460 C 1100 620, 960 700, 960 760" at={260} len={40} width={4} />
      <div style={{ position: "absolute", left: 760, top: 760, width: 400, opacity: fadeIn(frame, 290), fontFamily: FONT, color: C.text, textAlign: "center", background: "rgba(10,14,34,.94)", border: `2px solid ${C.amber}`, borderRadius: 18, padding: 18, boxShadow: "0 0 40px rgba(255,181,71,.35)" }}>
        <div style={{ fontSize: 22, fontWeight: 700 }}>RAMA Credit Fund I</div><div style={{ fontSize: 17, color: C.muted }}>Helios's signals roll up into the fund Hudson owns · NAV {APP.nav}</div></div>
      <Cursor path={[[1500, 980], [1470, 500]]} at={360} len={40} />
      <Chip x={1300} y={420} at={400} tone="grey" small>Missing input — nothing estimated.</Chip>
    </Wrap>
  );
};

// 8 — Cards and the explanation reveal
export const Cards: React.FC<SceneProps> = (props) => {
  const frame = useCurrentFrame();
  const expanded = frame > (props.cut ? 120 : 300);
  return (
    <Wrap scene={8} {...props}>
      <AbsoluteFill style={{ background: "radial-gradient(900px 500px at 50% 30%, #141a3a, #070a18)" }} />
      <Card x={120} y={160} w={520} tag="INCOME QUALITY" title="PIK and non-accrual above the watch limit" body={`Loans paying in kind or on non-accrual are ${APP.r1} of fund NAV, above Hudson's ${APP.r1Limit} watch limit.`} at={10} opacity={expanded ? 0.35 : 1} />
      <Card x={700} y={140} w={520} tag="REFINANCING WALL" title="Borrower leverage above threshold" body="Helios's public proxy carries net debt of 8.2x EBITDA, above the 6.0x threshold, with 13.5 months to maturity." at={40} />
      <Card x={1280} y={160} w={520} tag="TENANT CREDIT DRIFT · TENANT EVENT" title="A tenant behind two loans was downgraded" body="Oracle was downgraded to BBB- on 2026-07-09 and issued a force majeure notice on 2026-09-24. Look-through exposure $782.1M." at={70} opacity={expanded ? 0.35 : 1} />
      <Cursor path={[[1500, 980], [960, 300]]} at={props.cut ? 40 : 220} len={50} click={props.cut ? 110 : 290} />
      {expanded && <Table x={700} y={440} w={620} at={props.cut ? 120 : 300} rows={[["Metric", "Net debt / EBITDA = 8.2x"], ["Threshold", "6.0x — labeled default, editable by Hudson"], ["Calculation", "Rule R7: (total debt − cash) ÷ LTM EBITDA"], ["Source", "S&P Capital IQ Pro · CoreWeave (CRWV) · public proxy"], ["As of", "FY0 debt / LTM EBITDA · pulled 2026-10-16"]]} />}
      {expanded && <AmberLine d="M 1000 250 C 1000 400, 1000 500, 1000 650" at={props.cut ? 150 : 330} len={30} width={3} />}
    </Wrap>
  );
};

// 9 — The Guardrail
export const Guardrail: React.FC<SceneProps> = (props) => {
  const frame = useCurrentFrame(), L = useLen();
  const typed = "Should Hudson sell its stake in the fund?";
  const draft = "Hudson should reduce its commitment and rebalance into safer funds.";
  const t1 = L * 0.30, t2 = L * 0.38, t3 = L * 0.62, t4 = L * 0.72;      // typed by t1; draft from t2 to t3; struck at t3; hand-off at t4
  const n = Math.min(typed.length, Math.floor((frame / t1) * typed.length));
  const dn = Math.max(0, Math.min(draft.length, Math.floor(((frame - t2) / (t3 - t2)) * draft.length)));
  const struck = frame > t3;
  return (
    <Wrap scene={9} {...props}>
      {cap("CAPTURE_09") ? <Capture src={cap("CAPTURE_09")} id="CAPTURE_09" /> : <AbsoluteFill style={{ background: "#070a18" }} />}
      <div style={{ position: "absolute", left: 160, top: 150, width: 1600, fontFamily: FONT, color: C.text, background: "rgba(6,10,26,.96)", borderRadius: 18, padding: 28, border: "1px solid rgba(255,255,255,.1)" }}>
        <div style={{ fontSize: 20, color: C.muted }}>Controlled test</div>
        <div style={{ fontSize: 30, marginTop: 10 }}>{typed.slice(0, n)}<span style={{ opacity: frame % 20 < 10 ? 1 : 0 }}>|</span></div>
        <div style={{ fontSize: 26, marginTop: 24, color: "#ffb0a0", textDecoration: struck ? "line-through" : "none", opacity: struck ? 0.6 : 1 }}>{draft.slice(0, dn)}</div>
        {struck && <div style={{ marginTop: 18, display: "inline-block", background: "#ff4d4d", color: "#1a0000", fontWeight: 800, padding: "8px 14px", borderRadius: 10, fontSize: 20 }}>Blocked: prescriptive language</div>}
        {frame > t4 && <div style={{ marginTop: 20, fontSize: 24, color: C.text, opacity: fadeIn(frame, t4) }}>RAMA provides risk analysis only. Decisions sit with Hudson and its advisers. For questions about the fund, contact the GP's investor relations team.</div>}
      </div>
      <Footer at={t4}>{DISCLOSURE}</Footer>
    </Wrap>
  );
};

// 10 — Approval release
export const Release: React.FC<SceneProps> = (props) => {
  const a = props.cut ? 75 : 270, f = props.cut ? 75 : 180;      // approval (before the in-app line fires), the fiery line, the destination
  return (
    <Wrap scene={10} {...props}>
      <Sequence from={0} durationInFrames={a}><Capture src={cap("CAPTURE_10a")} id="CAPTURE_10a" from={props.cut ? 150 : 0} /><Chip x={1200} y={120} at={Math.round(a * 0.6)} tone="amber" small>Held — confirm with deal team · stays behind</Chip></Sequence>
      <Sequence from={a} durationInFrames={f}><Cinematic {...shot("fire")} label="fire" seconds={6} /><AmberLine d="M -50 700 C 500 700, 900 300, 2000 380" at={0} len={60} width={6} flame /></Sequence>
      <Sequence from={a + f}><Capture src={cap("CAPTURE_10b")} id="CAPTURE_10b" /><Banner at={5}>{DEST_LABEL}</Banner><Chip x={1300} y={160} at={40} tone="green" small>Approved · reviewer · 3 of 4 cards travelled</Chip></Sequence>
    </Wrap>
  );
};

// 11 — Under the hood: two windows of the PRISM recording (the traces list with the Nicrron-routed model, then the
// trace where the guardrail blocked the advisory sentence); the sign-in at the start of the recording is never shown
export const Hood: React.FC<SceneProps> = (props) => { const L = useLen(), h = Math.round(L * 0.5); return (
  <Wrap scene={11} {...props}>
    <Sequence from={0} durationInFrames={h}><Capture src={cap("CAPTURE_11")} id="CAPTURE_11 · PRISM dashboard (record after sign-in)" from={PRISM_FROM} />
      <div style={{ position: "absolute", left: 0, top: 1016, width: 222, height: 64, background: "#f5f7fb" }} />
      <Chip x={1180} y={100} at={30} tone="amber" small>Session helios-2026-09 · agent rama</Chip>
      <Chip x={1180} y={160} at={120} tone="amber" small>Model calls · openai-agents:generation:anthropic/claude-haiku-5-5 · via Nicrron</Chip>
      <Chip x={1180} y={220} at={210} tone="amber" small>Close tools · rules · guardrails as function spans</Chip></Sequence>
    <Sequence from={h}><Capture src={cap("CAPTURE_11")} id="CAPTURE_11" from={PRISM_FROM + PRISM_SECOND} />
      <div style={{ position: "absolute", left: 0, top: 1016, width: 222, height: 64, background: "#f5f7fb" }} />
      <Chip x={1180} y={100} at={20} tone="red" small>Guardrail: blocked · "descriptive": false</Chip>
      <Chip x={1180} y={160} at={110} tone="amber" small>The reason, recorded: it recommends reducing and rebalancing</Chip></Sequence>
  </Wrap>
); };

// 12 — Trace it back
export const Trace: React.FC<SceneProps> = (props) => {
  const L = useLen(), t = Math.round(L * (props.cut ? 0.35 : 0.55));   // the trace back, then the end card
  return (
    <Wrap scene={12} {...props}>
      <Sequence from={0} durationInFrames={t}><Capture src={cap("CAPTURE_12")} id="CAPTURE_12" from={props.cut ? 240 : 0} /></Sequence>
      <Sequence from={t}><Cinematic {...shot("pullback")} label="pullback" seconds={8} dim={0.35} />
        <Label x={0} y={380} width={1920} align="center" size={84} weight={800} at={30}>RAMA</Label>
        <Label x={0} y={500} width={1920} align="center" size={34} at={50} color={C.amber} italic>From reconciled books to reviewed intelligence.</Label>
        <Label x={0} y={620} width={1920} align="center" size={20} at={80} color={C.muted}>Synthetic data. Public market data from S&P Capital IQ Pro and cited public sources. Not investment advice.</Label>
      </Sequence>
    </Wrap>
  );
};
