/* RAMA web app: one state document from /api/state, six screens, polling while the agents work.
   The indicators are drawn from the rules' figures with inline SVG; what-if sliders recompute the same formulas
   client-side and are always labelled "what-if", never shown as rule outputs. */
(function () {
  "use strict";
  const I = {
    home: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 3 2 12h3v8h6v-6h2v6h6v-8h3z"/></svg>',
    ledger: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M4 3h16v18H4zM7 7v2h10V7zm0 4v2h10v-2zm0 4v2h6v-2z"/></svg>',
    pulse: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h4l3-7 4 14 3-7h4"/></svg>',
    check: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z"/></svg>',
    share: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M18 16a3 3 0 0 0-2.4 1.2l-6.7-3.4a3 3 0 0 0 0-1.6l6.7-3.4A3 3 0 1 0 15 7l-6.7 3.4a3 3 0 1 0 0 3.2L15 17a3 3 0 1 0 3-1z"/></svg>',
    bolt: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></svg>',
    search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
    user: '<svg viewBox="0 0 24 24" fill="currentColor" width="13" height="13"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6z"/></svg>',
    gear: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M19.4 13a7.5 7.5 0 0 0 0-2l2.1-1.6-2-3.5-2.5 1a7.6 7.6 0 0 0-1.7-1L15 3h-4l-.4 2.9a7.6 7.6 0 0 0-1.7 1l-2.5-1-2 3.5L6.6 11a7.5 7.5 0 0 0 0 2l-2.1 1.6 2 3.5 2.5-1a7.6 7.6 0 0 0 1.7 1L11 21h4l.4-2.9a7.6 7.6 0 0 0 1.7-1l2.5 1 2-3.5zM13 15.5a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7z"/></svg>',
    bell: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 22a2.5 2.5 0 0 0 2.5-2.5h-5A2.5 2.5 0 0 0 12 22zm7-6V11a7 7 0 0 0-5-6.7V3h-4v1.3A7 7 0 0 0 5 11v5l-2 2v1h18v-1z"/></svg>',
    wallet: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M21 7H5a1 1 0 0 1 0-2h14V3H5a3 3 0 0 0-3 3v12a3 3 0 0 0 3 3h16zm-3 8a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3z"/></svg>',
    globe: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm6.9 6h-3a15.6 15.6 0 0 0-1.4-3.6A8 8 0 0 1 18.9 8zM12 4c.8 1.2 1.5 2.5 1.9 4h-3.8c.4-1.5 1.1-2.8 1.9-4zM4.3 14a8 8 0 0 1 0-4h3.4a16 16 0 0 0 0 4zm.8 2h3a15.6 15.6 0 0 0 1.4 3.6A8 8 0 0 1 5.1 16zm3-8h-3a8 8 0 0 1 4.4-3.6C8.9 5.5 8.4 6.7 8.1 8zM12 20c-.8-1.2-1.5-2.5-1.9-4h3.8c-.4 1.5-1.1 2.8-1.9 4zm2.3-6H9.7a14 14 0 0 1 0-4h4.6a14 14 0 0 1 0 4zm.2 5.6c.6-1.1 1.1-2.3 1.4-3.6h3a8 8 0 0 1-4.4 3.6zM16.3 14a16 16 0 0 0 0-4h3.4a8 8 0 0 1 0 4z"/></svg>',
    doc: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zm-1 7V3.5L18.5 9z"/></svg>',
    cart: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 4h2l3.6 7.6L7.2 14A2 2 0 0 0 9 17h11v-2H9.4l1.1-2h7.4a2 2 0 0 0 1.8-1.1L22 6H6.2L5.3 4zM9 18a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm9 0a2 2 0 1 0 0 4 2 2 0 0 0 0-4z"/></svg>',
    shield: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2 4 5v6c0 5 3.4 9.7 8 11 4.6-1.3 8-6 8-11V5z"/></svg>',
    flame: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M13.5 1s1 3.5-1.5 6.5S7 12 7 15a5 5 0 0 0 10 0c0-2-1-3.5-1-3.5S18 13 18 15a6 6 0 0 1-12 0c0-5 7.5-8 7.5-14z"/></svg>',
    arrow: '<svg viewBox="0 0 24 24" fill="currentColor" width="13"><path d="M13 5l7 7-7 7-1.4-1.4 4.6-4.6H4v-2h12.2l-4.6-4.6z"/></svg>',
  };
  const $ = (s, r = document) => r.querySelector(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtM = (v, d = 1) => (v == null ? "—" : "$" + Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }) + "M");
  const fromCents = (c) => c / 1e8;
  const fmtC = (c) => (c == null ? "—" : (c < 0 ? "(" : "") + "$" + Math.abs(c / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + (c < 0 ? ")" : ""));
  const pct = (v, d = 1) => (v == null ? "—" : (v * 100).toFixed(d) + "%");
  const xx = (v) => (v == null ? "—" : Number(v).toFixed(2) + "x");
  const icons = (root = document) => root.querySelectorAll("[data-i]").forEach((e) => { if (!e.innerHTML) e.innerHTML = I[e.dataset.i] || ""; });
  const tween = (ms, fn) => { const t0 = performance.now(); (function s(t) { const k = Math.min(1, (t - t0) / ms); fn(1 - Math.pow(1 - k, 3)); if (k < 1) requestAnimationFrame(s); })(t0); };

  let lastErr = null, S = null, files = null, prism = null, route = "dashboard", charts = [], selRule = null, polling = null, intelRun = null, whatif = {};

  async function api(path, opts = {}) {
    const r = await fetch(path, { method: opts.method || "GET", headers: { "Content-Type": "application/json" }, body: opts.body ? JSON.stringify(opts.body) : undefined });
    const t = await r.text();
    let d; try { d = t ? JSON.parse(t) : {}; } catch (e) { d = { detail: t }; }
    if (!r.ok) throw new Error(d.detail || r.statusText);
    return d;
  }
  function toast(msg, err) { const t = $("#toast"); t.textContent = msg; t.className = "toast show" + (err ? " err" : ""); clearTimeout(t._h); t._h = setTimeout(() => (t.className = "toast"), 4200); }

  async function refresh() {
    S = await api("/api/state");
    $("#busybar").classList.toggle("on", !!S.busy);
    $("#tag-close").textContent = S.close ? (blockers().length ? blockers().length + " open" : "tied") : "";
    $("#tag-intel").textContent = S.rules ? S.rules.filter((r) => r.status === "fired").length + " fired" : "";
    $("#tag-review").textContent = S.cards && S.cards.length ? S.cards.filter((c) => c.review.status === "approved").length + "/" + S.cards.filter((c) => c.publishable).length : "";
    if (S.error && !S.busy && S.error.message !== lastErr) { lastErr = S.error.message; toast(S.error.message, true); }
    render();
    clearTimeout(polling);
    polling = setTimeout(refresh, S.busy ? 1200 : 6000);
  }
  async function loadPrism() {
    try { prism = await api("/api/prism"); } catch (e) { prism = null; }
    const d = (prism || {}).doctor || {};
    const p = $("#prism-pill");
    p.className = "pill" + (d.live_connected ? " live" : "");
    p.lastChild.textContent = d.live_connected ? "PRISM live" : "PRISM";
    $("#help-line").textContent = d.live_connected ? `PRISM live · ${d.live_trace_count || 0} traces · models via Nicrron` : "PRISM via the Agent Frameworks card · models via Nicrron";
  }
  const blockers = () => ((S.close || {}).final || {}).findings ? S.close.final.findings.filter((f) => f.severity === "blocker" && !(S.accepted || []).includes(f.key)) : [];
  const metric = (k) => ((S.metrics || {}).metrics || []).find((m) => m.key === k);
  const rule = (id) => (S.rules || []).find((r) => r.id === id);

  // ------------------------------------------------------------------ actions
  const act = async (fn, msg) => { try { await fn(); if (msg) toast(msg); } catch (e) { toast(e.message, true); } finally { await refresh(); } };
  window.RAMA = {
    reset: () => confirm("Reset the demo: reload the borrower's source package and clear the close, intelligence and approvals?") && act(() => api("/api/reset", { method: "POST" }), "Scenario reset: source package loaded"),
    runClose: () => act(() => api("/api/close/run", { method: "POST" }), "The agents are closing September"),
    runIntel: () => { whatif = {}; act(() => api("/api/intel/run", { method: "POST" }), "Building the leading indicators"); },
    resolve: (key, action) => {
      const decision = { action };
      if (action === "book_line") { const sel = document.querySelector(`[data-acct="${key}"]`); decision.account = sel.value; decision.note = (document.querySelector(`[data-note="${key}"]`) || {}).value || ""; if (!decision.account) return toast("Choose an account first", true); }
      act(() => api("/api/close/resolve", { method: "POST", body: { key, decision } }), "Decision posted with its citation; closing again");
    },
    review: (id, d) => act(() => api(`/api/cards/${id}/${d}`, { method: "POST", body: { note: d === "reject" ? prompt("Why is this card not right?") || "" : "" } }), d === "approve" ? "Card approved" : "Card " + d + "ed"),
    approvePackage: async (btn) => {
      try {
        const from = btn.getBoundingClientRect();
        await api("/api/package/approve", { method: "POST", body: {} });
        await refresh();
        await fire(from);
        location.hash = "#chronograph";
      } catch (e) { toast(e.message, true); }
    },
    guard: () => act(() => api("/api/guardrail/test", { method: "POST", body: { text: ($("#guard-text") || {}).value || null } }), "Guardrail test recorded"),
    toggle: (id) => { const e = document.getElementById(id); if (e) e.classList.toggle("open"); },
    rule: (id) => { selRule = id; render().then(() => { const d = $("#detail"); if (d) d.scrollIntoView({ behavior: "smooth", block: "start" }); }); },
    paper: (acct) => openPaper(acct),
    closeDrawer: () => { $("#drawer").classList.remove("open"); $("#drawer-bg").classList.remove("open"); },
    ask: () => { const o = $("#ask-out"); if (o) { o.textContent = S.handoff; o.classList.remove("hidden"); } },
    run: (id) => openRun(id),
    wi: (id, key, v) => { whatif[id] = { ...(whatif[id] || {}), [key]: +v }; drawDetail(); },
    wiReset: (id) => { delete whatif[id]; drawDetail(); },
  };

  // ------------------------------------------------------------------ the release line
  function fire(fromRect) {
    return new Promise((resolve) => {
      const svg = $("#fire");
      svg.classList.remove("hidden");
      svg.setAttribute("width", innerWidth); svg.setAttribute("height", innerHeight);
      [...svg.querySelectorAll("path,circle")].forEach((n) => n.remove());
      const to = $("#nav-chrono").getBoundingClientRect();
      const x1 = fromRect.left + fromRect.width / 2, y1 = fromRect.top + fromRect.height / 2, x2 = to.right - 10, y2 = to.top + to.height / 2;
      const d = `M ${x1} ${y1} C ${x1} ${y1 - 260}, ${x2 + 420} ${y2 + 120}, ${x2} ${y2}`;
      const ns = "http://www.w3.org/2000/svg";
      const halo = document.createElementNS(ns, "path"); halo.setAttribute("d", d); halo.setAttribute("class", "halo");
      const core = document.createElementNS(ns, "path"); core.setAttribute("d", d); core.setAttribute("class", "core");
      svg.appendChild(halo); svg.appendChild(core);
      const len = core.getTotalLength();
      [halo, core].forEach((p) => { p.style.strokeDasharray = len; p.style.strokeDashoffset = len; });
      const sparks = [...Array(8)].map(() => { const c = document.createElementNS(ns, "circle"); c.setAttribute("r", 2 + Math.random() * 2.5); c.setAttribute("fill", Math.random() > .5 ? "#ffd166" : "#ff8a00"); c.setAttribute("filter", "url(#glow)"); svg.appendChild(c); return { c, lag: Math.random() * 0.12 }; });
      tween(1700, (e) => {
        [halo, core].forEach((p) => (p.style.strokeDashoffset = len * (1 - e)));
        sparks.forEach((s) => { const kk = Math.max(0, e - s.lag); const pt = core.getPointAtLength(len * kk); s.c.setAttribute("cx", pt.x + (Math.random() - .5) * 8); s.c.setAttribute("cy", pt.y + (Math.random() - .5) * 8); s.c.setAttribute("opacity", 1 - kk * 0.6); });
        if (e >= 1) { $("#nav-chrono").animate([{ boxShadow: "0 0 0 0 rgba(255,140,0,.0)" }, { boxShadow: "0 0 24px 6px rgba(255,140,0,.7)" }, { boxShadow: "0 0 0 0 rgba(255,140,0,0)" }], { duration: 900 }); setTimeout(() => { svg.classList.add("hidden"); resolve(); }, 650); }
      });
    });
  }

  // ------------------------------------------------------------------ charts (the cash chart only)
  function killCharts() { charts.forEach((c) => { try { c.destroy(); } catch (e) {} }); charts = []; }
  function chart(el, opts) { if (!el || !window.ApexCharts) return; const c = new ApexCharts(el, opts); c.render(); charts.push(c); }
  async function cashSeries() {
    if (!files) { try { files = (await api("/api/close/files")).files; } catch (e) { files = []; } }
    const out = {};
    for (const ref of ["1000", "1010"]) {
      let pts = [];
      for (const m of ["2026-08", "2026-09"]) {
        const ctl = (files.find((f) => f.name === `statement_${ref}_control_${m}.json`) || { rows: [{}] }).rows[0];
        const lines = (files.find((f) => f.name === `statement_${ref}_lines_${m}.csv`) || { rows: [] }).rows;
        let bal = Number(ctl.opening_cents || 0);
        if (!pts.length) pts.push([new Date(m + "-01").getTime(), +(fromCents(bal)).toFixed(2)]);
        for (const l of lines) { bal += Number(l.amount_cents); pts.push([new Date(l.date).getTime(), +(fromCents(bal)).toFixed(2)]); }
      }
      out[ref] = pts;
    }
    return out;
  }
  function countUp(el, to, fmt) { if (!el || !isFinite(to)) return; tween(900, (k) => (el.textContent = fmt(to * k))); }

  // ------------------------------------------------------------------ the indicators: what each one is and how it is drawn
  const IND = {
    R1: { name: "Income quality", group: "fund", watch: "loans paying in kind or on non-accrual, as a share of fund NAV", kind: "meter", dir: "max", fmt: pct,
          value: (f) => f.ratio_of_nav, limit: (t) => t.pik_nonaccrual_watch, scale: 0.3, limitLabel: "LP watch limit",
          sliders: [{ key: "limit", label: "LP watch limit", min: 0.02, max: 0.3, step: 0.01, fmt: (v) => pct(v, 0) }] },
    R2: { name: "Tenant concentration", group: "tenants", watch: "the largest tenant's share of fund loans, looked through every loan", kind: "meter", dir: "max", fmt: pct,
          value: (f) => f.share_of_loans, limit: (t) => t.single_tenant_cap, scale: 0.6, limitLabel: "LP single-tenant cap",
          sliders: [{ key: "limit", label: "LP single-tenant cap", min: 0.1, max: 0.6, step: 0.01, fmt: (v) => pct(v, 0) }] },
    R3: { name: "Tenant credit drift", group: "tenants", watch: "rating actions, outlooks and low ratings on tenant proxies", kind: "ladder",
          sliders: [{ key: "window", label: "Action window (days)", min: 30, max: 365, step: 5, fmt: (v) => v + " days" }] },
    R4: { name: "Tenant / project event", group: "tenants", watch: "force majeure, lease amendments, delays, financing stress", kind: "event" },
    R5: { name: "GPU collateral value", group: "borrowers", watch: "loan-to-value re-estimated from GPU rental rates", kind: "meter", dir: "max", fmt: pct,
          value: (f) => f.ltv, limit: (t) => t.ltv_at_origination, scale: 1.2, limitLabel: "LTV at origination",
          sliders: [{ key: "rate", label: "H100 rental rate now ($/hr)", min: 0.5, max: 10, step: 0.05, fmt: (v) => "$" + v.toFixed(2) + "/hr" },
                    { key: "limit", label: "LTV threshold", min: 0.5, max: 1, step: 0.01, fmt: (v) => pct(v, 0) }],
          recompute: (f, w) => f.drawn_usd_m / (f.appraisal_usd_m * (w.rate ?? f.rate_now_mid_usd_hr) / f.rate_at_appraisal_usd_hr) },
    R6: { name: "Contract cover", group: "borrowers", watch: "loan term left uncovered after the borrower's contracts end", kind: "none", needs: "backlog / contracted revenue KPIs" },
    R7: { name: "Refinancing wall", group: "borrowers", watch: "stressed borrowers whose loans mature soon", kind: "timeline",
          sliders: [{ key: "window", label: "Maturity window (months)", min: 3, max: 36, step: 1, fmt: (v) => v + " months" }] },
    R8: { name: "Power / construction", group: "borrowers", watch: "power shortfalls and permit or pipeline delays on construction loans", kind: "none", needs: "451 facility and power-proximity data" },
    R9: { name: "Market supply", group: "borrowers", watch: "data-center pipeline against existing capacity in the collateral markets", kind: "none", needs: "451 data-center market data" },
    R10: { name: "Valuation gap", group: "borrowers", watch: "public comparables moving while the GP's mark stays", kind: "none", needs: "price history (not pulled)" },
    R11: { name: "Rating divergence", group: "borrowers", watch: "external ratings worsening while the GP's internal grade stays 'performing'", kind: "divergence" },
    R12: { name: "LP liquidity", group: "fund", watch: "net capital calls over the next 12 months against the LP's liquidity floor", kind: "meter", dir: "max", fmt: (v) => fmtM(v, 1),
           value: (f) => f.net_calls_12m_usd_m, limit: (t) => t.liquidity_floor_usd_m, scale: 100, limitLabel: "LP liquidity floor",
           sliders: [{ key: "callrate", label: "Share of unfunded called in 12 months", min: 0, max: 1, step: 0.05, fmt: (v) => pct(v, 0) },
                     { key: "limit", label: "LP liquidity floor", min: 10, max: 100, step: 1, fmt: (v) => fmtM(v, 0) }],
           recompute: (f, w) => f.unfunded_usd_m * (w.callrate ?? f.calls_12m_usd_m / f.unfunded_usd_m) - f.distributions_12m_usd_m },
    R13: { name: "Fund leverage headroom", group: "fund", watch: "room left under the facility's borrowing base", kind: "meter", dir: "min", fmt: pct,
           value: (f) => f.headroom, limit: (t) => t.headroom_min, scale: 0.5, limitLabel: "headroom floor",
           sliders: [{ key: "drawn", label: "Facility drawn", min: 400, max: 780, step: 5, fmt: (v) => fmtM(v, 0) },
                     { key: "limit", label: "Headroom floor", min: 0.05, max: 0.4, step: 0.01, fmt: (v) => pct(v, 0) }],
           recompute: (f, w) => (f.borrowing_base_usd_m - (w.drawn ?? f.drawn_usd_m)) / f.borrowing_base_usd_m },
    R14: { name: "Covenant headroom", group: "borrowers", watch: "room left under each loan's covenant tests", kind: "meter", dir: "min", fmt: pct,
           value: (f) => f.headroom, limit: (t) => t.headroom_min, scale: 0.5, limitLabel: "headroom floor",
           sliders: [{ key: "ebitda", label: "Borrower EBITDA change", min: -0.3, max: 0.3, step: 0.01, fmt: (v) => (v > 0 ? "+" : "") + pct(v, 0) },
                     { key: "limit", label: "Headroom floor", min: 0.02, max: 0.3, step: 0.01, fmt: (v) => pct(v, 0) }],
           recompute: (f, w) => (f.limit_x - f.actual_x / (1 + (w.ebitda ?? 0))) / f.limit_x },
  };
  const GROUPS = [["tenants", "Tenants", "Who pays the borrowers: the hyperscalers behind the leases"], ["borrowers", "Borrowers & collateral", "The loans themselves: leverage, maturities, ratings, collateral"], ["fund", "Fund & LP", "The fund's income, leverage and the LP's own limits"]];
  const chipFor = (s) => ({ fired: '<span class="chip warn">fired</span>', clear: '<span class="chip ok">clear</span>', held: '<span class="chip violet">held</span>', not_evaluated: '<span class="chip plain">not evaluated</span>' }[s] || '<span class="chip plain">pending</span>');

  function evaluateWhatIf(r) {
    /* The same formula as rules.py on the rule's own figures, with the sliders applied. Returns {value, limit, fires, changed}. */
    const d = IND[r.id], w = whatif[r.id] || {}, f = r.figures, t = r.threshold;
    if (d.kind !== "meter") return null;
    const limit = w.limit ?? d.limit(t);
    const value = d.recompute && Object.keys(w).some((k) => k !== "limit") ? d.recompute(f, w) : d.value(f);
    const fires = d.dir === "max" ? value > limit : value < limit;
    return { value, limit, fires, changed: Object.keys(w).length > 0 };
  }

  // tile meter: a small bar with the threshold mark, filled by animation
  function tileMeter(r) {
    const d = IND[r.id];
    if (!r || r.status === "pending" || !["fired", "clear", "held"].includes(r.status) || d.kind === "none") return `<div class="tm"><div class="tm-bar dashed"></div><span class="k">${r && r.status === "not_evaluated" ? "needs " + esc(d.needs || "data not pulled") : r && r.status === "held" ? "inputs not yet verified" : "waiting for the rules"}</span></div>`;
    if (d.kind === "meter") {
      const v = d.value(r.figures), lim = d.limit(r.threshold), sc = d.scale;
      if (v == null || lim == null) return `<div class="tm"><div class="tm-bar dashed"></div><span class="k">inputs not yet verified</span></div>`;
      return `<div class="tm"><div class="tm-bar"><i class="fill ${r.status}" data-w="${Math.min(100, (v / sc) * 100).toFixed(1)}"></i><b class="mark" style="left:${Math.min(100, (lim / sc) * 100).toFixed(1)}%"></b></div><span class="k"><span class="v">${d.fmt(v)}</span> vs ${d.fmt(lim)} ${d.dir === "max" ? "cap" : "floor"}</span></div>`;
    }
    if (d.kind === "ladder") { const h = r.figures.hits && r.figures.hits[0]; return `<div class="tm"><div class="tm-dots">${["AAA", "AA", "A", "BBB", "BB", "B"].map((b) => `<span class="${h && h.rating.startsWith(b) ? "hit" : ""}">${b}</span>`).join("")}</div><span class="k">${h ? `${h.proxy} ${h.rating} · ${h.action} ${h.action_date}` : "no tenant drift"}</span></div>`; }
    if (d.kind === "timeline") { const hits = r.figures.loans.filter((x) => x.fires); return `<div class="tm"><div class="tm-dots">${r.figures.loans.map((x) => `<span class="${x.fires ? "hit" : x.stress.length ? "warm" : ""}">${x.loan}</span>`).join("")}</div><span class="k">${hits.length ? hits.map((x) => `${x.loan} in ${x.months_to_maturity} mo`).join(" · ") : "nothing maturing under stress"}</span></div>`; }
    if (d.kind === "divergence") return `<div class="tm"><div class="tm-dots">${r.figures.divergent.map((x) => `<span class="hit">${x.loan}</span>`).join("") || '<span>none</span>'}</div><span class="k">${r.figures.count} loan(s) · ${fmtM(r.figures.exposure_usd_m)}</span></div>`;
    if (d.kind === "event") { const e = r.figures.events && r.figures.events[0]; return `<div class="tm"><div class="tm-dots"><span class="${e ? "hit" : ""}">${e ? e.date : "—"}</span></div><span class="k">${e ? esc(e.category + " · " + e.headline) : "no watched event"}</span></div>`; }
    return "";
  }
  function animateMeters() { requestAnimationFrame(() => document.querySelectorAll("i.fill[data-w]").forEach((el) => (el.style.width = el.dataset.w + "%"))); }

  // ------------------------------------------------------------------ the detail visuals (inline SVG)
  function svgMeter(r, wi) {
    const d = IND[r.id], v = wi.value, lim = wi.limit, sc = Math.max(d.scale, v * 1.15, lim * 1.15);
    const W = 640, H = 136, x0 = 20, x1 = W - 20, y = 62;
    const px = (q) => x0 + (Math.min(q, sc) / sc) * (x1 - x0);
    const zone = d.dir === "max" ? `<rect x="${px(lim)}" y="${y - 14}" width="${x1 - px(lim)}" height="28" rx="6" fill="rgba(255,181,71,.12)"/>` : `<rect x="${x0}" y="${y - 14}" width="${px(lim) - x0}" height="28" rx="6" fill="rgba(255,181,71,.12)"/>`;
    const ticks = [0, .25, .5, .75, 1].map((k) => `<text x="${x0 + k * (x1 - x0)}" y="${y + 40}" fill="#718096" font-size="11" text-anchor="middle">${d.fmt(sc * k)}</text>`).join("");
    return `<svg viewBox="0 0 ${W} ${H}" class="viz">${zone}
      <rect x="${x0}" y="${y - 6}" width="${x1 - x0}" height="12" rx="6" fill="#1a1f37"/>
      <rect id="vz-fill" x="${x0}" y="${y - 6}" width="0" height="12" rx="6" fill="${wi.fires ? "#ffb547" : "#0075ff"}" data-to="${px(v) - x0}"/>
      <line x1="${px(lim)}" x2="${px(lim)}" y1="${y - 24}" y2="${y + 24}" stroke="#fff" stroke-width="2" stroke-dasharray="4 3"/>
      <text x="${px(lim)}" y="${y - 30}" fill="#fff" font-size="11" text-anchor="middle">${esc(d.limitLabel)} ${d.fmt(lim)}</text>
      <circle id="vz-dot" cx="${x0}" cy="${y}" r="9" fill="${wi.fires ? "#ffb547" : "#2cd9ff"}" data-to="${px(v)}"><animate attributeName="r" values="9;11;9" dur="1.8s" repeatCount="indefinite"/></circle>
      <text id="vz-val" x="${x0}" y="${y + 24}" fill="#fff" font-size="13" font-weight="700" text-anchor="middle" data-to="${px(v)}">${d.fmt(v)}</text>${ticks}
      <text x="${x1}" y="${y + 62}" fill="#a0aec0" font-size="11" text-anchor="end">fires when ${d.dir === "max" ? "above" : "below"} the ${d.dir === "max" ? "cap" : "floor"}</text></svg>`;
  }
  const RATINGS = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-", "B+", "B", "B-", "CCC", "NR"];
  function tenantRows() {
    /* every tenant proxy with its rating and look-through exposure: R2's by-tenant shares and R3's hits */
    const r2 = rule("R2"), r3 = rule("R3"), fund = S.fund;
    const by = (r2 && r2.figures.by_tenant) || {};
    const hitBy = Object.fromEntries(((r3 && r3.figures.hits) || []).map((h) => [h.proxy, h]));
    const known = { MSFT: "AAA", AMZN: "AA", META: "AA-", GOOGL: "AA+", ORCL: "BBB-" };   // display only, from the same snapshot
    return Object.keys(by).filter((p) => /^[A-Z]{2,5}$/.test(p)).map((p) => { const h = hitBy[p]; return { proxy: p, rating: h ? h.rating : known[p] || "NR", action: h ? h.action : "", days: h ? h.days_since_action : 9999, outlook: h ? h.outlook : "Stable", exposure: by[p] * (fund ? fund.loans_total_usd_m : 0) }; });
  }
  function svgLadder(r, w) {
    const win = w.window ?? r.threshold.window_days, hits = r.figures.hits || [];
    const W = 640, H = 240, x0 = 56, x1 = W - 40, y = 84, step = (x1 - x0) / (RATINGS.length - 1);
    const px = (rt) => x0 + Math.max(0, RATINGS.indexOf(rt)) * step;
    const floorX = px(r.threshold.rating_floor);
    const all = tenantRows();
    const fires = (t) => (t.action === "Downgrade" && t.days <= win) || t.outlook === "Negative" || RATINGS.indexOf(t.rating) >= RATINGS.indexOf(r.threshold.rating_floor);
    const nodes = all.map((t, i) => { const f = fires(t), row = f ? 0 : 1 + (i % 4), lx = Math.max(x0 + 10, Math.min(x1 - 10, px(t.rating))); return `<g class="pop" style="animation-delay:${i * 90}ms"><line x1="${px(t.rating)}" x2="${px(t.rating)}" y1="${y}" y2="${y + 30 + row * 20}" stroke="${f ? "#ffb547" : "#56577a"}" stroke-width="1"/><circle cx="${px(t.rating)}" cy="${y}" r="${f ? 9 : 6}" fill="${f ? "#ffb547" : "#0075ff"}"/><text x="${lx}" y="${y + 44 + row * 20}" fill="${f ? "#ffd166" : "#a0aec0"}" font-size="11" text-anchor="middle">${t.proxy} ${fmtM(t.exposure, 0)}</text></g>`; }).join("");
    return `<svg viewBox="0 0 ${W} ${H}" class="viz">
      <rect x="${floorX - step / 2}" y="${y - 28}" width="${x1 - floorX + step / 2 + 10}" height="56" rx="8" fill="rgba(255,181,71,.10)"/>
      <text x="${floorX}" y="${y - 36}" fill="#ffb547" font-size="11" text-anchor="middle">rated ${r.threshold.rating_floor} or lower fires</text>
      <line x1="${x0}" x2="${x1}" y1="${y}" y2="${y}" stroke="#56577a" stroke-width="2"/>
      ${RATINGS.map((rt) => `<text x="${px(rt)}" y="${y - 14}" fill="#718096" font-size="9" text-anchor="middle">${rt}</text>`).join("")}
      ${nodes}
      <text x="${x0 - 36}" y="${H - 8}" fill="#a0aec0" font-size="11">S&amp;P ratings via Capital IQ Pro, as of 2026-10-16 · a downgrade within ${win} days fires${hits.length ? ` (${hits[0].proxy}: ${hits[0].action} ${hits[0].action_date}, ${hits[0].days_since_action} days ago)` : ""}</text></svg>`;
  }
  function svgTimeline(r, w) {
    const win = w.window ?? r.threshold.maturity_months, loans = (S.fund || {}).loans || [], rows = r.figures.loans || [];
    const W = 640, H = 240, x0 = 40, x1 = W - 20, base = 150, span = 62;
    const asOf = new Date("2026-10-16");
    const mo = (d) => (new Date(d) - asOf) / (1000 * 3600 * 24 * 30.4375);
    const px = (m) => x0 + Math.min(1, Math.max(0, m / span)) * (x1 - x0);
    const maxP = Math.max(...loans.map((l) => l.principal_usd_m));
    const bars = loans.map((l, i) => { const row = rows.find((x) => x.loan === l.loan); const m = mo(l.maturity); const stressed = row && row.stress.length; const fires = stressed && m <= win; const h = 20 + (l.principal_usd_m / maxP) * 90;
      return `<g class="pop" style="animation-delay:${i * 100}ms"><rect x="${px(m) - 14}" y="${base - h}" width="28" height="${h}" rx="6" fill="${fires ? "#ffb547" : stressed ? "rgba(255,181,71,.45)" : "#0075ff"}"/><text x="${px(m)}" y="${base - h - 8}" fill="#fff" font-size="11" text-anchor="middle">${l.loan} ${fmtM(l.principal_usd_m, 0)}</text><text x="${px(m)}" y="${base + 16}" fill="#a0aec0" font-size="10" text-anchor="middle">${l.maturity.slice(0, 7)}</text>${row && row.stress.length ? `<text x="${px(m)}" y="${base + 30 + (i % 2) * 12}" fill="${fires ? "#ffd166" : "#a0aec0"}" font-size="9" text-anchor="middle">${esc(row.proxy)}: ${esc(row.stress[0].replace(/net debt\/EBITDA/, "lev.").replace(/EBITDA\/interest/, "cov.").replace("negative LTM EBITDA", "EBITDA < 0"))}</text>` : ""}</g>`; }).join("");
    return `<svg viewBox="0 0 ${W} ${H}" class="viz">
      <rect x="${x0}" y="20" width="${px(win) - x0}" height="${base - 20}" rx="8" fill="rgba(255,181,71,.10)"/>
      <text x="${px(win)}" y="14" fill="#ffb547" font-size="11" text-anchor="middle">within ${win} months</text>
      <line x1="${x0}" x2="${x1}" y1="${base}" y2="${base}" stroke="#56577a" stroke-width="2"/>
      ${[0, 12, 24, 36, 48, 60].map((m) => `<text x="${px(m)}" y="${base + 58}" fill="#718096" font-size="10" text-anchor="middle">${m ? "+" + m + " mo" : "today"}</text>`).join("")}
      ${bars}
      <text x="${x0}" y="${H - 6}" fill="#a0aec0" font-size="11">amber: a stressed borrower proxy (leverage, coverage, unrated or negative EBITDA) maturing inside the window</text></svg>`;
  }
  function svgDivergence(r) {
    const loans = (S.fund || {}).loans || [], div = Object.fromEntries((r.figures.divergent || []).map((d) => [d.loan, d]));
    const cap = Object.fromEntries((rule("R7") ? rule("R7").figures.loans : []).map((x) => [x.loan, x.rating]));
    const W = 640, H = 40 + loans.length * 30, xl = 180, xr = 460;
    const rows = loans.map((l, i) => { const y = 36 + i * 30, d = div[l.loan], ext = d ? d.external : cap[l.loan] || (l.proxy ? "—" : "n/a");
      return `<g class="pop" style="animation-delay:${i * 80}ms"><text x="${xl - 10}" y="${y + 4}" fill="#fff" font-size="12" text-anchor="end">${l.loan} · ${esc(l.borrower.split(" ")[0])}${l.proxy ? " (" + l.proxy + ")" : ""}</text>
        <rect x="${xl}" y="${y - 10}" width="60" height="20" rx="6" fill="${d ? "#ffb547" : "#1a1f37"}"/><text x="${xl + 30}" y="${y + 4}" fill="${d ? "#1a0d00" : "#fff"}" font-size="11" text-anchor="middle" font-weight="700">${esc(ext)}</text>
        <line x1="${xl + 62}" x2="${xr - 2}" y1="${y}" y2="${y}" stroke="${d ? "#ffb547" : "#56577a"}" stroke-width="${d ? 2 : 1}" stroke-dasharray="${d ? "6 4" : "0"}" class="${d ? "flow" : ""}"/>
        <rect x="${xr}" y="${y - 10}" width="80" height="20" rx="6" fill="#1a1f37"/><text x="${xr + 40}" y="${y + 4}" fill="#fff" font-size="11" text-anchor="middle">${esc(l.gp_grade)}</text></g>`; }).join("");
    return `<svg viewBox="0 0 ${W} ${H}" class="viz"><text x="${xl + 30}" y="14" fill="#a0aec0" font-size="11" text-anchor="middle">S&amp;P rating (proxy)</text><text x="${xr + 40}" y="14" fill="#a0aec0" font-size="11" text-anchor="middle">GP internal grade</text>${rows}</svg>`;
  }
  function svgEvent(r) {
    const e = (r.figures.events || [])[0];
    if (!e) return `<div class="note">No watched event.</div>`;
    const W = 640, H = 120, x0 = 30, x1 = W - 30, y = 60;
    const days = ["2026-07-01", "2026-08-01", "2026-09-01", "2026-10-01", "2026-10-16"];
    const px = (d) => x0 + ((new Date(d) - new Date(days[0])) / (new Date(days[4]) - new Date(days[0]))) * (x1 - x0);
    return `<svg viewBox="0 0 ${W} ${H}" class="viz"><line x1="${x0}" x2="${x1}" y1="${y}" y2="${y}" stroke="#56577a" stroke-width="2"/>
      ${days.map((d) => `<text x="${px(d)}" y="${y + 26}" fill="#718096" font-size="10" text-anchor="middle">${d.slice(5)}</text>`).join("")}
      <g class="pop"><circle cx="${px(e.date)}" cy="${y}" r="10" fill="#ffb547"><animate attributeName="r" values="10;13;10" dur="1.8s" repeatCount="indefinite"/></circle>
      <text x="${px(e.date)}" y="${y - 22}" fill="#fff" font-size="12" font-weight="700" text-anchor="middle">${esc(e.headline)}</text>
      <text x="${px(e.date)}" y="${y + 46}" fill="#ffd166" font-size="11" text-anchor="middle">${esc(e.category)} · exposure ${fmtM(e.exposure_usd_m)} across ${e.loans.join(", ")}</text></g></svg>`;
  }
  function exposureFlow(r) {
    /* which loans this indicator touches: the company (L2) and the stand-ins */
    const loans = (S.fund || {}).loans || [];
    if (!loans.length) return "";
    const hit = new Set(r.loans || []);
    return `<div class="flow-row">${loans.map((l) => `<div class="fl ${hit.has(l.loan) ? "hit" : ""} ${l.closed_by_rama ? "rama" : ""}"><b>${l.loan}</b><span>${esc(l.borrower.split(" ")[0])}</span>${l.closed_by_rama ? '<small>closed by RAMA</small>' : ""}</div>`).join("")}</div>`;
  }

  function sliders(r) {
    const d = IND[r.id], w = whatif[r.id] || {};
    if (!d.sliders || !["fired", "clear"].includes(r.status)) return "";
    const init = (s) => { if (s.key === "limit") return d.limit(r.threshold); if (s.key === "window") return r.threshold.window_days ?? r.threshold.maturity_months; if (s.key === "rate") return r.figures.rate_now_mid_usd_hr; if (s.key === "callrate") return r.figures.calls_12m_usd_m / r.figures.unfunded_usd_m; if (s.key === "drawn") return r.figures.drawn_usd_m; return 0; };
    return `<div class="wi"><div class="wi-h"><b>What if</b><span class="note">drag to see when this indicator would fire · scenario values, not rule outputs</span>${Object.keys(w).length ? `<button class="btn ghost" style="padding:6px 10px" onclick="RAMA.wiReset('${r.id}')">Reset</button>` : ""}</div>
      ${d.sliders.map((s) => { const v = w[s.key] ?? init(s); return `<label class="sl"><span>${esc(s.label)}</span><input type="range" min="${s.min}" max="${s.max}" step="${s.step}" value="${v}" oninput="RAMA.wi('${r.id}','${s.key}',this.value)"><b>${s.fmt(+v)}</b></label>`; }).join("")}</div>`;
  }

  function detailHtml(r) {
    const d = IND[r.id], w = whatif[r.id] || {};
    let viz = "", verdict = "";
    if (r.status === "not_evaluated" || d.kind === "none") viz = `<div class="viz-empty"><b>Not evaluated</b><span>${esc(d.watch)}.</span><span>Needs: ${esc(d.needs || (r.missing || []).join("; ") || "data not pulled")}. Missing inputs are logged, never estimated.</span></div>`;
    else if (r.status === "held") viz = `<div class="viz-empty"><b>Held</b><span>${esc(d.watch)}.</span><span>${esc(r.detail || "Its inputs come from the close and aren't verified yet.")} Decide the close's open items, then rebuild.</span></div>`;
    else if (d.kind === "meter") { const wi = evaluateWhatIf(r); viz = svgMeter(r, wi); verdict = `<span class="chip ${wi.fires ? "warn" : "ok"}">${wi.changed ? "what-if: " : ""}${wi.fires ? "fires" : "clear"}</span>`; }
    else if (d.kind === "ladder") viz = svgLadder(r, w);
    else if (d.kind === "timeline") viz = svgTimeline(r, w);
    else if (d.kind === "divergence") viz = svgDivergence(r);
    else if (d.kind === "event") viz = svgEvent(r);
    const figs = Object.entries(r.figures).filter(([, v]) => !(v && typeof v === "object"));
    const card = (S.cards || []).find((c) => c.rule_id === r.id);
    return `<div class="glass card" id="detail"><div class="card-h"><div><h3>${esc(d.name)}</h3><div class="sub">${esc(d.watch)} · ${chipFor(r.status)} ${verdict}</div></div><button class="btn ghost" onclick="RAMA.rule(null)">Close</button></div>
      <div class="detail-grid">
        <div>${viz}${exposureFlow(r)}${sliders(r)}</div>
        <div class="side">
          <h5>Figures (rule outputs)</h5><div class="kv">${figs.map(([k, v]) => `<span class="k">${esc(k.replace(/_/g, " "))}</span><b class="mono">${esc(typeof v === "number" ? (k.includes("usd_m") ? fmtM(v, 1) : /share|headroom|ltv|vs_accrued/.test(k) ? pct(v) : /_x$/.test(k) ? xx(v) : v) : v)}</b>`).join("") || '<span class="note">none</span>'}</div>
          <h5>Threshold</h5><div class="kv">${Object.entries(r.threshold).map(([k, v]) => `<span class="k">${esc(k.replace(/_/g, " "))}</span><b>${esc(typeof v === "number" && v < 1 && !/x$/.test(k) ? pct(v, 0) : v)}</b>`).join("") || '<span class="note">—</span>'}</div>
          <h5>Sources</h5>${(r.inputs || []).map((i) => `<div class="src"><b>${esc(i.label)}</b><span>${esc(i.source)} · as of ${esc(i.as_of)}</span></div>`).join("") || '<span class="note">—</span>'}
          ${r.detail && r.status !== "held" ? `<p class="note">${esc(r.detail)}</p>` : ""}
          <h5>Execution</h5><div class="note" id="exec-line">${traceLine(r)}</div>
          ${card ? `<h5>Card</h5><p class="note">${card.title ? `<a href="#review" style="color:var(--blue-2)">${esc(card.title)}</a> · guardrails ${esc(card.compliance.status)}` : "blocked by the guardrails"}</p>` : ""}
        </div></div></div>`;
  }
  function traceLine(r) {
    const run = (S.runs || []).find((x) => x.kind === "intelligence");
    if (!run) return "Not computed yet.";
    const st = intelRun && intelRun.run_id === run.run_id ? intelRun.steps.find((s) => s.label === `rule ${r.id} ${r.name}`) : null;
    return `Computed by <code>rules.py</code> in run <a onclick="RAMA.run('${run.run_id}')" style="color:var(--blue-2);cursor:pointer">${esc(run.run_id)}</a>${st ? ` · step "${esc(st.label)}" · ${st.duration_ms} ms · ${st.status}` : ""} · traced to PRISM session <b>${esc(S.session)}</b> via the Agent Frameworks card.`;
  }
  async function loadIntelRun() {
    const run = (S.runs || []).find((x) => x.kind === "intelligence");
    if (run && (!intelRun || intelRun.run_id !== run.run_id)) { try { intelRun = await api("/api/runs/" + run.run_id); } catch (e) { intelRun = null; } }
  }
  function drawDetail() {
    const r = rule(selRule); if (!r) return;
    const host = $("#detail"); if (!host) return;
    host.outerHTML = detailHtml(r);
    animateViz();
  }
  function animateViz() {
    requestAnimationFrame(() => {
      const f = $("#vz-fill"), dot = $("#vz-dot"), val = $("#vz-val");
      if (f) tween(1100, (k) => { f.setAttribute("width", (+f.dataset.to) * k); if (dot) dot.setAttribute("cx", 20 + (+dot.dataset.to - 20) * k); if (val) val.setAttribute("x", 20 + (+val.dataset.to - 20) * k); });
    });
  }

  // ------------------------------------------------------------------ screens
  const H = {};
  function stageStrip() {
    const c = S.close, b = blockers().length;
    const st = [
      ["Close", !c ? "pending" : b ? "needs you" : "tied", !c ? "Run the month" : b ? `${b} decision(s)` : "every account ties", "#close"],
      ["Intelligence", !S.rules ? (c ? "ready" : "pending") : "built", S.rules ? `${S.rules.filter((r) => r.status === "fired").length} of 14 fired` : "rules R1–R14", "#intelligence"],
      ["Review", !S.cards || !S.cards.length ? "pending" : S.package.status === "approved" ? "approved" : "needs you", S.cards && S.cards.length ? `${S.cards.filter((x) => x.review.status === "approved").length} / ${S.cards.filter((x) => x.publishable).length} approved` : "cards + guardrails", "#review"],
      ["Destination", S.stage === "published" ? "released" : "pending", S.stage === "published" ? `${S.destination.published.length} notes in the LP view` : "Chronograph (demo)", "#chronograph"],
    ];
    return `<div class="stages">${st.map(([n, s, d, h], i) => `<a href="${h}" class="stage ${s === "needs you" ? "need" : s === "pending" || s === "ready" ? "" : "done"}"><span class="n">${i + 1}</span><div><b>${n}</b><span>${esc(d)}</span></div><em>${esc(s)}</em></a>`).join("")}</div>`;
  }
  H.dashboard = async () => {
    const fund = S.fund, c = S.close, fired = (S.rules || []).filter((r) => r.status === "fired");
    const ebitda = metric("ebitda_run_rate");
    const approved = (S.cards || []).filter((x) => x.review.status === "approved").length, pub = (S.cards || []).filter((x) => x.publishable).length;
    const next = !c ? ["Run the close", "RAMA.runClose()"] : blockers().length ? ["Review the close", "location.hash='#close'"] : !S.rules ? ["Build the indicators", "RAMA.runIntel()"] : S.stage !== "published" ? ["Review & release", "location.hash='#review'"] : ["Open the destination", "location.hash='#chronograph'"];
    const loans = fund ? fund.loans : [];
    $("#view").innerHTML = `
      <div class="glass card" style="margin-bottom:24px"><div class="card-h"><div><h3>${esc(S.company.name)} · September 2026 → RAMA Credit Fund I</h3><div class="sub">Synthetic borrower · public proxy ${S.company.proxy} · loan ${S.company.loan}</div></div><button class="btn" onclick="${next[1]}" ${S.busy ? "disabled" : ""}>${S.busy ? '<span class="spin"></span> Working' : next[0]}</button></div>${stageStrip()}</div>
      <div class="row r4">
        ${statTile("Fund loans (L1–L6)", fund ? fmtM(fund.loans_total_usd_m) : "—", fund ? `<small class="up">6 loans</small>` : "", "wallet", fund && fund.loans_total_usd_m)}
        ${statTile("Borrower EBITDA run-rate", ebitda ? fmtM(ebitda.value) : "—", ebitda ? `<small class="${ebitda.verified ? "up" : "amber"}">${ebitda.verified ? "verified" : "held"}</small>` : "", "globe", ebitda && ebitda.value)}
        ${statTile("Indicators fired", S.rules ? fired.length + " / 14" : "—", S.rules ? `<small class="amber">${S.rules.filter((r) => r.status === "not_evaluated").length} not evaluated</small>` : "", "pulse")}
        ${statTile("Cards released", pub ? approved + " / " + pub : "—", S.stage === "published" ? `<small class="up">in the LP view</small>` : "", "cart")}
      </div>
      <div class="row r-charts">
        <div class="glass card"><h3>Cash overview</h3><div class="sub">${c ? `<b class="up">Tied</b> to the bank statements · Aug–Sep 2026` : "Run the close to tie the bank statements"}</div><div id="area" class="chart"></div></div>
        <div class="glass card"><h3>Indicators</h3><div class="sub">${S.rules ? `${fired.length} fired · click one to explore` : "Built after the close"}</div>
          <div class="list" style="margin-top:12px">${(S.rules || []).filter((r) => r.status === "fired").slice(0, 6).map((r) => `<a href="#intelligence" onclick="selRuleSet('${r.id}')" class="ind-mini"><b>${esc(IND[r.id].name)}</b>${tileMeter(r)}</a>`).join("") || '<div class="note">Indicator meters appear here once the rules run.</div>'}</div></div>
      </div>
      <div class="row r-bottom">
        <div class="glass card"><div class="card-h"><div><h3>Portfolio loans</h3><div class="sub"><b class="up">${loans.filter((l) => l.closed_by_rama).length || 0} closed by RAMA</b> this month · ${loans.length ? loans.length - 1 : 5} synthetic stand-ins</div></div></div>${loansTable(loans)}</div>
        <div class="glass card"><h3>Activity</h3><div class="sub">${(S.events || []).length} events this session</div><div class="tl" style="margin-top:20px">${(S.events || []).slice(0, 6).map(evItem).join("") || '<div class="note">Reset or run the month to begin.</div>'}</div></div>
      </div>`;
    const series = c ? await cashSeries() : { "1000": [], "1010": [] };
    chart($("#area"), {
      chart: { type: "area", height: 280, toolbar: { show: false }, background: "transparent", fontFamily: "Plus Jakarta Sans" },
      series: [{ name: "Operating account ($M)", data: series["1000"] }, { name: "Debt service reserve ($M)", data: series["1010"] }],
      colors: ["#2cd9ff", "#0075ff"], stroke: { curve: "smooth", width: 2 }, dataLabels: { enabled: false }, legend: { show: false },
      fill: { type: "gradient", gradient: { shade: "dark", type: "vertical", shadeIntensity: 0, opacityFrom: 0.8, opacityTo: 0, stops: [0, 90, 100] } },
      xaxis: { type: "datetime", labels: { style: { colors: "#c8cfca", fontSize: "10px" } }, axisBorder: { show: false }, axisTicks: { show: false } },
      yaxis: { labels: { style: { colors: "#c8cfca", fontSize: "10px" }, formatter: (v) => "$" + v.toFixed(0) + "M" } },
      grid: { strokeDashArray: 5, borderColor: "#56577A" }, tooltip: { theme: "dark", x: { format: "dd MMM yyyy" } }, noData: { text: "Run the close", style: { color: "#a0aec0" } },
    });
    animateMeters();
  };
  window.selRuleSet = (id) => { selRule = id; };
  function statTile(l, v, extra, icon, num) { const id = "st" + Math.random().toString(36).slice(2, 7); const html = `<div class="glass stat"><div><div class="l">${esc(l)}</div><div class="v"><span id="${id}">${v}</span>${extra}</div></div><div class="ibox">${I[icon]}</div></div>`; if (num) setTimeout(() => countUp(document.getElementById(id), num, (x) => fmtM(x)), 0); return html; }
  function evItem(e) {
    const ic = { close: "ledger", fix: "check", review: "check", intelligence: "pulse", package: "shield", publish: "flame", guardrail: "shield", error: "bell", reset: "doc", stale: "bell" }[e.kind] || "doc";
    const color = { error: "var(--red)", publish: "var(--amber)", guardrail: "var(--violet)", fix: "var(--green)" }[e.kind] || "var(--blue)";
    return `<div class="it"><span class="ic" style="color:${color}">${I[ic]}</span><div><b>${esc(e.text.length > 90 ? e.text.slice(0, 90) + "…" : e.text)}</b><span>${new Date(e.at).toLocaleString("en-US", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }).toUpperCase()}</span></div></div>`;
  }
  const logoColors = { L1: "#4318ff", L2: "#ff6a00", L3: "#01b574", L4: "#2cd9ff", L5: "#7551ff", L6: "#e31a1a" };
  function loansTable(loans) {
    if (!loans.length) return `<div class="note">The fund view is built from the closed books.</div>`;
    const head = rule("R14");
    return `<table class="t"><thead><tr><th>Loan / borrower</th><th>Tenants</th><th class="num">Principal</th><th>Covenant headroom</th></tr></thead><tbody>${loans.map((l) => {
      const t = head ? (head.figures.tests || []).find((x) => x.loan === l.loan) : null;
      const h = t ? Math.max(0, t.headroom) : null;
      return `<tr><td><div class="co"><span class="logo" style="background:${logoColors[l.loan]}">${l.loan}</span><div>${esc(l.borrower)}<div class="k">${l.proxy ? "proxy " + l.proxy + " · " : ""}${l.closed_by_rama ? '<span class="up">closed by RAMA</span>' : "stand-in"}</div></div></div></td>
        <td><div class="avatars">${l.tenants.map((x) => `<span title="${esc(x.tenant)}">${esc((x.proxy || "EC").slice(0, 4))}</span>`).join("")}</div></td>
        <td class="num"><b>${fmtM(l.principal_usd_m)}</b></td>
        <td><div class="prog"><small style="color:${h != null && h < 0.1 ? "var(--amber)" : "var(--blue-2)"}">${h == null ? "—" : pct(h)}</small><div class="bar"><i class="fill" data-w="${h == null ? 0 : Math.min(100, h * 250)}" style="background:${h != null && h < 0.1 ? "var(--amber)" : "var(--blue)"}"></i></div></div></td></tr>`;
    }).join("")}</tbody></table>`;
  }

  // close
  H.close = async () => {
    const c = S.close, comp = S.company;
    const steps = [
      ["Source package", S.source_files ? `${S.source_files.length} files: bank, reserve and lender statements` : "Loaded on reset", !!S.source_files],
      ["Read the books", c ? "Ledger snapshot, Aug–Sep 2026" : "waiting", !!c],
      ["Tie & check", c ? `${c.final.recons.filter((r) => r.difference === 0).length}/${c.final.recons.length} bank accounts tie` : "waiting", !!c],
      ["Record what's supported", c ? `${c.applied.length} entry recorded with citations` : "waiting", !!(c && c.applied.length)],
      ["Workpapers", c ? `${c.final.workpapers.filter((w) => w.status === "tied").length} of ${c.final.workpapers.length} tied` : "waiting", !!c],
    ];
    $("#view").innerHTML = `
      <div class="glass card" style="margin-bottom:24px">
        <div class="card-h"><div><h3>${esc(comp.name)} · September 2026 close</h3><div class="sub">Synthetic borrower · public proxy ${comp.proxy} · loan ${comp.loan} from RAMA Credit Fund I</div></div>
        <button class="btn" onclick="RAMA.runClose()" ${S.busy ? "disabled" : ""}>${S.busy && S.busy.task !== "intelligence" ? '<span class="spin"></span> Closing' : (c ? "Close again" : "Run the close")}</button></div>
        <div class="steps">${steps.map((s, i) => `<div class="stepc ${s[2] ? "on" : ""}"><div class="n">STEP ${i + 1}</div><b>${s[0]}</b><span>${esc(s[1])}</span></div>`).join("")}</div>
        ${c ? `<div class="note" style="margin-top:14px">${esc(c.summary)} ${c.model_called ? "The classifier was asked about unexplained lines through Nicrron; nothing was posted on its guess." : ""}</div>` : ""}
      </div>
      ${c ? `
      <div class="row r2">
        <div class="glass card"><h3>Needs your decision</h3><div class="sub">${blockers().length ? blockers().length + " blocker(s) · the agents never post without support" : '<b class="up">Nothing blocking</b> · every account the indicators use ties'}</div>
          <div class="list" style="margin-top:14px">${c.final.findings.map(excItem).join("") || '<div class="note">No open items.</div>'}</div></div>
        <div class="glass card"><h3>Verified figures</h3><div class="sub">Only evidence that tied feeds the indicators</div>
          <table class="t" style="margin-top:8px"><tbody>${((S.metrics || {}).metrics || []).map((m) => `<tr><td>${esc(m.label)}</td><td class="num"><b>${m.unit === "USD m" ? fmtM(m.value, 2) : m.unit === "x" ? xx(m.value) : m.unit === "ratio" ? pct(m.value) : m.value}</b></td><td>${m.verified ? '<span class="chip ok">verified</span>' : `<span class="chip warn" title="${esc(m.held_because || "")}">held</span>`}</td></tr>`).join("")}</tbody></table>
          ${c.applied.length ? `<h5 style="margin-top:16px">Recorded by the agents</h5><div class="list">${c.applied.map((a) => `<div class="exc"><div><b>${esc(a.line ? a.line.description : a.kind)} → ${esc(a.to || "")}</b><span class="note">${fmtC(a.line ? a.line.amount : 0)} on ${a.line ? a.line.date : ""} · cites ${a.citations.map((x) => `<span class="chip info">${esc(x)}</span>`).join(" ")}</span></div><span class="chip ok">recorded</span></div>`).join("")}</div>` : ""}</div>
      </div>
      <div class="row r2">
        <div class="glass card"><h3>Reconciliations</h3><div class="sub">Bank and lender statements against the books, 30 Sep 2026</div>
          <table class="t"><thead><tr><th>Account</th><th class="num">Statement</th><th class="num">Books</th><th class="num">Difference</th><th></th></tr></thead><tbody>
          ${c.final.recons.map((r) => `<tr><td>${esc(r.account)}</td><td class="num mono">${fmtC(r.statement_closing)}</td><td class="num mono">${fmtC(r.ledger_balance)}</td><td class="num mono">${fmtC(r.difference)}</td><td>${r.difference === 0 ? '<span class="chip ok">tied</span>' : '<span class="chip bad">break</span>'}</td></tr>`).join("")}
          ${(c.lenders || []).map((l) => { const w = c.final.workpapers.find((p) => p.account.includes(l.loan)); return `<tr><td>Lender statement ${esc(l.loan)}</td><td class="num mono">${fmtC(l.closing_principal)}</td><td class="num mono">${w ? fmtC(-w.closing) : "—"}</td><td class="num mono">${w ? fmtC(-w.closing - l.closing_principal) : "—"}</td><td>${w && -w.closing === l.closing_principal ? '<span class="chip ok">tied</span>' : '<span class="chip bad">break</span>'}</td></tr>`; }).join("")}
          </tbody></table></div>
        <div class="glass card"><h3>Workpapers</h3><div class="sub">Opening + activity = closing, with support · click to open the evidence</div>
          <table class="t"><thead><tr><th>Account</th><th class="num">Closing</th><th>Status</th></tr></thead><tbody>
          ${c.final.workpapers.map((w) => `<tr style="cursor:pointer" onclick="RAMA.paper(${esc(JSON.stringify(w.account)).replace(/"/g, "&quot;")})"><td>${esc(w.account)}</td><td class="num mono">${fmtC(w.closing)}</td><td>${statusChip(w.status)}</td></tr>`).join("")}
          </tbody></table></div>
      </div>
      <div class="glass card"><div class="card-h"><div><h3>Statements</h3><div class="sub">From the books after the close</div></div><button class="btn ghost" onclick="RAMA.toggle('stmts')">Show / hide</button></div>
        <div class="explain" id="stmts"><div class="row r2" style="margin:0">${statementCard("Profit and loss · September", c.statements.profit_and_loss)}${bsCard(c.statements.balance_sheet)}</div></div></div>` : ""}`;
  };
  function statusChip(s) { return { tied: '<span class="chip ok">tied</span>', exception: '<span class="chip bad">exception</span>', unsupported: '<span class="chip warn">unsupported</span>', info: '<span class="chip">info</span>', excused: '<span class="chip">excused</span>' }[s] || `<span class="chip">${esc(s)}</span>`; }
  function excItem(f) {
    let acts = "";
    if (f.check === "pik_split") acts = `<button class="btn green" onclick="RAMA.resolve('${esc(f.key)}','accept_pik_split')">Accept correction</button>`;
    else if (f.check === "lender_difference") acts = `<button class="btn green" onclick="RAMA.resolve('${esc(f.key)}','post_lender_entry')">Post entry per lender statement</button>`;
    else if (f.check === "unrecorded" && f.fix) acts = `<select data-acct="${esc(f.key)}"><option value="">Choose account…</option>${["Data Center Deposits", "GPU Equipment", "Power & Cooling", "Colocation Rent", "Network & Software", "Bank Fees"].map((a) => `<option>${a}</option>`).join("")}</select><input type="text" data-note="${esc(f.key)}" placeholder="Support (invoice, contract)…" style="width:150px"><button class="btn" onclick="RAMA.resolve('${esc(f.key)}','book_line')">Book line</button><button class="btn ghost" title="No support: keep it as an exception; RAMA won't force it to balance" onclick="RAMA.resolve('${esc(f.key)}','leave_open')">Leave open</button>`;
    else acts = `<span class="chip">${f.who === "client" ? "asked the client" : "for follow-up"}</span>`;
    const open = (S.accepted || []).includes(f.key);
    if (open) acts = `<span class="chip warn">left open · no support</span>`;
    const sev = f.severity === "blocker" ? '<span class="chip bad">blocker</span>' : f.severity === "review" ? '<span class="chip warn">review</span>' : '<span class="chip">info</span>';
    const cites = (f.refs || []).length ? `<div class="meta" style="margin-top:6px">${f.refs.map((x) => `<span class="chip info">${esc(x)}</span>`).join("")}</div>` : "";
    return `<div class="exc"><div><b>${sev} ${esc(f.title)}</b><span class="note">${esc(f.detail || "")}</span>${cites}</div><div class="acts">${acts}</div></div>`;
  }
  function statementCard(title, pl) {
    const row = (r) => `<tr><td>${esc(r.account)}</td><td class="num mono">${fmtC(r.month)}</td></tr>`;
    return `<div><h5>${title}</h5><table class="t"><tbody><tr><td class="k">INCOME</td><td></td></tr>${pl.income.map(row).join("")}<tr><td class="k">EXPENSES</td><td></td></tr>${pl.expenses.map(row).join("")}<tr><td><b>Net income (month)</b></td><td class="num mono"><b>${fmtC(pl.net_month)}</b></td></tr></tbody></table></div>`;
  }
  function bsCard(bs) {
    const row = (r) => `<tr><td>${esc(r.account)}</td><td class="num mono">${fmtC(r.amount)}</td></tr>`;
    return `<div><h5>Balance sheet · 30 Sep 2026 ${bs.total_assets === bs.total_liabilities + bs.total_equity ? '<span class="chip ok">balances</span>' : '<span class="chip bad">out of balance</span>'}</h5><table class="t"><tbody>${bs.assets.map(row).join("")}<tr><td><b>Total assets</b></td><td class="num mono"><b>${fmtC(bs.total_assets)}</b></td></tr>${bs.liabilities.map(row).join("")}${bs.equity.map(row).join("")}<tr><td><b>Total liabilities and equity</b></td><td class="num mono"><b>${fmtC(bs.total_liabilities + bs.total_equity)}</b></td></tr></tbody></table></div>`;
  }
  async function openPaper(acct) {
    const w = S.close.final.workpapers.find((x) => x.account === acct);
    if (!files) { try { files = (await api("/api/close/files")).files; } catch (e) { files = []; } }
    const ref = Object.entries({ "1000": "Operating Account", "1010": "Debt Service Reserve" }).find(([, a]) => a === acct);
    const loan = acct.includes("L2") ? "L2" : acct.includes("VF1") ? "VF1" : null;
    let src = "";
    if (ref) {
      const lines = (files.find((f) => f.name === `statement_${ref[0]}_lines_2026-09.csv`) || { rows: [] }).rows;
      const ctl = (files.find((f) => f.name === `statement_${ref[0]}_control_2026-09.json`) || { rows: [{}] }).rows[0];
      const cited = new Set((S.close.applied || []).map((a) => a.line && a.line.line_id));
      src = `<div class="k">statement_${ref[0]}_lines_2026-09.csv · closing ${fmtC(ctl.closing_cents)}</div><table class="t"><tbody>${lines.map((l) => `<tr class="${cited.has(l.line_id) ? "hl" : ""}"><td class="k">${l.line_id}</td><td>${l.date}</td><td>${esc(l.description)}</td><td class="num mono">${fmtC(+l.amount_cents)}</td></tr>`).join("")}</tbody></table>`;
    } else if (loan) {
      const l = (S.close.lenders || []).find((x) => x.loan === loan);
      src = l ? `<div class="k">${esc(l.file)} · lender's statement</div><div class="kv" style="margin-top:10px"><span class="k">Opening principal</span><b class="mono">${fmtC(l.opening_principal)}</b><span class="k">Cash interest paid</span><b class="mono">${fmtC(l.interest)}</b><span class="k">PIK capitalized</span><b class="mono hl">${fmtC(l.pik)}</b><span class="k">Closing principal</span><b class="mono">${fmtC(l.closing_principal)}</b></div>` : "No lender statement.";
    } else src = `<div class="note">${esc((w.support || {}).text || "Support: schedule or none on file.")}</div>`;
    const result = acct.includes("L2") || acct.includes("VF1") ? metric("debt") : ref ? metric("cash") : null;
    $("#drawer").innerHTML = `<div class="card-h"><div><h3>${esc(acct)}</h3><div class="sub">Workpaper · September 2026 · ${statusChip(w.status)}</div></div><button class="btn ghost" onclick="RAMA.closeDrawer()">Close</button></div>
      <div class="evid">
        <div class="pane"><h5>Financial result</h5>${result ? `<div class="k">${esc(result.label)}</div><div class="big-num">${fmtM(result.value, 2)}</div>${result.verified ? '<span class="chip ok">verified</span>' : '<span class="chip warn">held</span>'}<p class="note">Feeds the leading indicators only when verified.</p>` : '<div class="note">This account isn\'t an indicator input.</div>'}
          <div class="kv" style="margin-top:16px"><span class="k">Opening</span><b class="mono">${fmtC(w.opening)}</b><span class="k">Activity</span><b class="mono">${fmtC(w.moved)}</b><span class="k">Closing</span><b class="mono">${fmtC(w.closing)}</b></div></div>
        <div class="pane"><h5>Workpaper activity</h5><table class="t"><tbody>${(w.rows || []).slice(0, 18).map((r) => `<tr><td class="k">${r.date}</td><td>${esc(r.what)}</td><td class="num mono">${fmtC(r.cents)}</td></tr>`).join("")}</tbody></table></div>
        <div class="pane"><h5>Supporting statement</h5>${src}</div>
      </div>`;
    $("#drawer").classList.add("open"); $("#drawer-bg").classList.add("open");
  }

  // intelligence
  H.intelligence = async () => {
    const rules = S.rules || [], cap = S.capiq, b = blockers().length;
    await loadIntelRun();
    const byId = Object.fromEntries(rules.map((r) => [r.id, r]));
    const m = (k) => metric(k);
    const srcChip = (ok, label, sub) => `<div class="srcbox ${ok ? "ok" : ""}"><b>${esc(label)}</b><span>${esc(sub)}</span></div>`;
    const verified = ((S.metrics || {}).metrics || []).filter((x) => x.verified).length, total = ((S.metrics || {}).metrics || []).length;
    $("#view").innerHTML = `
      <div class="glass card" style="margin-bottom:24px"><div class="card-h"><div><h3>Leading indicators</h3><div class="sub">Verified accounting meets dated market evidence. Fixed rules compute; the model only words; guardrails check.</div></div>
        <button class="btn" onclick="RAMA.runIntel()" ${!S.close || S.busy ? "disabled" : ""}>${S.busy && S.busy.task === "intelligence" ? '<span class="spin"></span> Working' : rules.length ? "Rebuild indicators" : "Build indicators"}</button></div>
        <div class="srcflow">
          ${srcChip(total && verified === total, `Helios Compute · verified books`, total ? `${verified} of ${total} figures verified · EBITDA run-rate ${m("ebitda_run_rate") ? fmtM(m("ebitda_run_rate").value, 0) : "—"} · leverage ${m("net_debt_ebitda_x") ? xx(m("net_debt_ebitda_x").value) : "—"}` : "close the month first")}
          <span class="arrow ${rules.length ? "live" : ""}"></span>
          ${srcChip(cap.present, "S&P Capital IQ Pro snapshot", cap.present ? `12 companies · ratings, leverage, coverage · as of ${cap.as_of}` : "data/capiq/ not found")}
          <span class="arrow ${rules.length ? "live" : ""}"></span>
          ${srcChip(!!S.fund, "RAMA Credit Fund I · LP policy", S.fund ? `6 loans · ${fmtM(S.fund.loans_total_usd_m, 0)} · ${S.fund.lp.name.split(" (")[0]}` : "loan tape, facility, LP limits")}
        </div>
        ${!S.close ? `<div class="note" style="margin-top:12px">Run the close first: the indicators read the closed books.</div>` : b ? `<div class="note" style="margin-top:12px"><span class="chip warn">${b} open in the close</span> You can build now: figures from unverified evidence are <b>held</b> and their indicators don't fire. <a href="#close" style="color:var(--blue-2)">Decide them on the Close screen</a>, then rebuild.</div>` : ""}
      </div>
      ${GROUPS.map(([g, title, sub]) => `<div class="glass card" style="margin-bottom:24px"><h3>${title}</h3><div class="sub">${sub}</div>
        <div class="ind-grid">${Object.entries(IND).filter(([, d]) => d.group === g).map(([id, d]) => { const r = byId[id] || { id, status: "pending", figures: {}, threshold: {} }; return `<div class="ind ${r.status} ${id === selRule ? "sel" : ""}" onclick="RAMA.rule('${id}')"><div class="ind-h"><b>${esc(d.name)}</b>${chipFor(r.status)}</div><span class="note">${esc(d.watch)}</span>${tileMeter(r)}</div>`; }).join("")}</div></div>`).join("")}
      ${selRule && byId[selRule] ? detailHtml(byId[selRule]) : ""}
      <div class="note" style="margin-top:8px">Not evaluated = the data wasn't pulled (${cap.missing.length} gaps logged); nothing is estimated. Non-S&P inputs are labelled: the H100 rental index (Spheron, citing SemiAnalysis) and one cited event.</div>`;
    animateMeters();
    animateViz();
  };

  // review & release
  H.review = async () => {
    const cards = S.cards || [];
    const pending = cards.filter((c) => c.publishable && c.review.status === "pending").length, approved = cards.filter((c) => c.review.status === "approved").length;
    $("#view").innerHTML = `
      <div class="glass card" style="margin-bottom:24px"><div class="pkg">
        <div><h3>Release package · RAMA Credit Fund I · as of 2026-10-16</h3><div class="sub">${cards.length ? `${approved} approved · ${pending} pending · ${cards.filter((c) => c.review.status === "rejected").length} rejected · ${cards.filter((c) => !c.publishable).length} blocked by guardrails` : "Build the indicators to get cards."}${S.package.status === "approved" ? ` · <b class="up">package approved ${new Date(S.package.at).toLocaleTimeString()}</b>` : ""}</div></div>
        <div style="display:flex;gap:10px;align-items:center"><span class="label-strip">${I.flame.replace("<svg", '<svg width="14" height="14"')} Destination: Chronograph (demonstration)</span>
        <button class="btn fire" onclick="RAMA.approvePackage(this)" ${!cards.length || S.busy ? "disabled" : ""}>${I.check} Approve package &amp; release</button></div>
      </div><div class="disclosure">${esc(S.disclosure)}</div></div>
      <div class="cards">${cards.map(cardHtml).join("") || '<div class="glass card note">No cards yet.</div>'}</div>
      <div class="glass card" style="margin-top:24px"><div class="card-h"><div><h3>Guardrail test</h3><div class="sub">The same checks every card passes. An advisory sentence is blocked and logged to PRISM.</div></div></div>
        <div style="display:flex;gap:12px;align-items:flex-start"><textarea id="guard-text">Oracle exposure is above your cap, so you should reduce your commitment and rebalance into safer funds.</textarea><button class="btn red" onclick="RAMA.guard()" ${!S.rules || S.busy ? "disabled" : ""}>Run test</button></div>
        <div class="list" style="margin-top:12px">${(S.guardrail_tests || []).slice(0, 3).map((g) => `<div class="exc"><div><b>${g.blocked ? '<span class="chip bad">blocked</span>' : '<span class="chip ok">passed</span>'} ${esc(g.text)}</b><span class="note">${g.checks.map((c) => `${c.passed ? "✔" : "✖"} ${esc(c.check)}: ${esc(c.detail)}`).join(" · ")}</span></div></div>`).join("")}</div>
      </div>`;
  };
  function cardHtml(c) {
    const st = c.review.status, cls = !c.publishable ? "blocked" : st, comp = c.compliance.status;
    return `<div class="icard ${cls}">
      <div class="meta"><span class="chip warn">${esc(IND[c.rule_id] ? IND[c.rule_id].name : c.rule_name)}</span>${comp === "passed" ? '<span class="chip ok">guardrails passed</span>' : comp === "rewritten" ? '<span class="chip violet">rewritten once</span>' : `<span class="chip bad">${comp}</span>`}${c.loans && c.loans.length ? `<span class="chip info">${c.loans.join(", ")}</span>` : ""}</div>
      <h4>${esc(c.title || "Blocked card (not published)")}</h4>
      <p>${esc(c.body || c.compliance.checks.filter((x) => !x.passed).map((x) => x.detail).join("; "))}</p>
      <button class="btn ghost" style="align-self:flex-start;padding:8px 12px" onclick="RAMA.toggle('ex-${c.id}')">Explain</button>
      <div class="explain" id="ex-${c.id}">
        <div class="kv">${c.facts.map((f) => `<span class="k">${esc(f.label)}</span><b class="mono">${esc(f.value)}</b>`).join("")}</div>
        <p class="note"><b>Threshold:</b> ${esc(Object.entries(c.threshold).map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`).join(" · "))}</p>
        <p class="note"><b>Sources:</b><br>${c.sources.map((s) => `${esc(s.label)} — ${esc(s.source)} (as of ${esc(s.as_of)})`).join("<br>")}</p>
        <p class="note"><b>Checks:</b> ${c.compliance.checks.map((x) => `${x.passed ? "✔" : "✖"} ${esc(x.check)}`).join(" · ")} · model ${esc(c.model)} via Nicrron · <a href="#intelligence" onclick="selRuleSet('${c.rule_id}')" style="color:var(--blue-2)">open the indicator</a></p>
      </div>
      <div class="row-b"><span class="note">${st === "approved" ? `<span class="up">Approved</span> by ${esc(c.review.by)}` : st === "rejected" ? `<span class="down">Rejected</span>: ${esc(c.review.note || "")}` : c.publishable ? "Awaiting review" : "Dropped by guardrails"}</span>
        <div style="display:flex;gap:8px">${c.publishable && st !== "approved" ? `<button class="btn green" onclick="RAMA.review('${c.id}','approve')">Approve</button>` : ""}${c.publishable && st !== "rejected" ? `<button class="btn ghost" onclick="RAMA.review('${c.id}','reject')">Reject</button>` : ""}${st !== "pending" ? `<button class="btn ghost" onclick="RAMA.review('${c.id}','reset')">Undo</button>` : ""}</div></div>
    </div>`;
  }

  // destination
  H.chronograph = async () => {
    const d = S.destination || {}, f = d.fund || {}, pub = d.published || [];
    $("#view").innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px"><span class="label-strip">${esc(d.label || "Demonstration destination — no live Chronograph connection.")}</span><span class="note">${d.at ? "Received " + new Date(d.at).toLocaleString() : "Nothing released yet"}</span></div>
      <div class="dest">
        <div class="dh"><div class="logo">chrono<span>graph</span>-style · LP portfolio monitoring</div><div style="font-size:12px;color:#6b7a90">${esc(d.lp || "Hudson State Teachers' Pension (synthetic LP)")} · Q3 2026</div></div>
        <div class="db">
          <div class="kp"><div><span>Fund</span><b style="font-size:15px">${esc(f.name || "RAMA Credit Fund I")}</b></div><div><span>Loans</span><b>${f.loans_total_usd_m ? fmtM(f.loans_total_usd_m, 0) : "—"}</b></div><div><span>NAV (est.)</span><b>${f.nav_usd_m ? fmtM(f.nav_usd_m, 0) : "—"}</b></div><div><span>Risk notes from RAMA</span><b>${pub.length}</b></div></div>
          <table><thead><tr><th>Holding</th><th>Borrower</th><th>Proxy</th><th>Principal</th><th>Maturity</th><th>Data</th></tr></thead><tbody>
          ${(f.loans || []).map((l) => `<tr><td>${l.loan}</td><td>${esc(l.borrower)}</td><td>${l.proxy || "—"}</td><td>${fmtM(l.principal_usd_m)}</td><td>${l.maturity}</td><td>${l.closed_by_rama ? "RAMA close, Sep 2026" : "Loan tape (stand-in)"}</td></tr>`).join("") || '<tr><td colspan="6" style="color:#6b7a90">Awaiting the first release.</td></tr>'}</tbody></table>
          <h4 style="margin:22px 0 4px;color:#0b3b5c">Risk notes · approved in RAMA</h4>
          <div class="notes">${pub.map((c) => `<div class="rn"><h6>${esc(c.title)}</h6><p>${esc(c.body)}</p><small>${esc(IND[c.rule_id] ? IND[c.rule_id].name : c.rule_id)} · ${esc(c.sources.map((s) => s.source + " (" + s.as_of + ")").join("; "))}</small><a href="#intelligence" onclick="selRuleSet('${c.rule_id}')" style="display:inline-block;margin-top:8px;font-size:12px;color:#18a0a6;font-weight:600">Trace back to the books →</a></div>`).join("") || '<div class="empty">No approved notes yet. Approve the package in RAMA to release them here.</div>'}</div>
          <div style="margin-top:18px;display:flex;gap:10px;align-items:center"><button onclick="RAMA.ask()" style="border:1px solid #cfd7e6;background:#fff;border-radius:8px;padding:8px 12px;cursor:pointer;color:#0b3b5c;font-weight:600">What should I do?</button><span id="ask-out" class="hidden" style="font-size:13px;color:#3b4a63"></span></div>
          <div class="disc">${esc(d.disclosure || S.disclosure)}</div>
        </div>
      </div>`;
  };

  // execution evidence
  H.execution = async () => {
    await loadPrism();
    const d = (prism || {}).doctor || {};
    $("#view").innerHTML = `
      <div class="row r4">
        ${statTile("PRISM", d.live_connected ? "Live connected" : "Not live", `<small class="${d.app_connected ? "up" : "amber"}">${d.app_connected ? "app" : ""}</small>`, "bolt")}
        ${statTile("Traces received", d.live_trace_count != null ? String(d.live_trace_count) : "—", "", "pulse")}
        ${statTile("Session", esc(S.session), "", "doc")}
        ${statTile("Model route", "Nicrron", `<small class="up">all calls</small>`, "globe")}
      </div>
      <div class="row r-bottom">
        <div class="glass card"><h3>Runs in this session</h3><div class="sub">Integration: ${esc((prism || {}).integration || "Agent Frameworks: OpenAI Agents SDK")} · every step is a span in PRISM</div>
          <table class="t"><thead><tr><th>Run</th><th>Kind</th><th>Steps</th><th>Summary</th></tr></thead><tbody>${(S.runs || []).map((r) => `<tr style="cursor:pointer" onclick="RAMA.run('${r.run_id}')"><td class="k">${esc(r.run_id)}</td><td><span class="chip info">${esc(r.kind)}</span></td><td>${r.steps}</td><td class="note">${esc(r.summary.slice(0, 120))}</td></tr>`).join("") || '<tr><td class="note" colspan="4">No runs yet.</td></tr>'}</tbody></table></div>
        <div class="glass card"><h3>Setup doctor</h3><div class="sub">PRISM's own answer for the project</div>
          <div class="kv" style="margin-top:14px">${Object.entries(d).filter(([k]) => k !== "host").map(([k, v]) => `<span class="k">${esc(k.replace(/_/g, " "))}</span><b>${esc(String(v))}</b>`).join("")}</div>
          <p class="note" style="margin-top:14px">Open PRISM at <a href="https://prism.blockconvey.com" target="_blank" style="color:var(--blue-2)">prism.blockconvey.com</a> → Agent Runs, session <b>${esc(S.session)}</b>.</p></div>
      </div>`;
  };
  async function openRun(id) {
    const r = await api("/api/runs/" + id);
    $("#drawer").innerHTML = `<div class="card-h"><div><h3>${esc(r.kind)} · ${esc(r.run_id)}</h3><div class="sub">${esc(r.output || "")}</div></div><button class="btn ghost" onclick="RAMA.closeDrawer()">Close</button></div>
      <p class="note">${esc(r.task)} · ${r.latency_ms} ms · models: ${esc((r.models || []).join(", ") || "none")}</p>
      <table class="t"><thead><tr><th>#</th><th>Step</th><th>Type</th><th>Status</th><th class="num">ms</th><th>Output</th></tr></thead><tbody>${r.steps.map((s, i) => `<tr><td class="k">${i + 1}</td><td>${esc(s.label)}</td><td><span class="chip ${s.step_type === "reasoning" ? "violet" : "info"}">${esc(s.step_type)}</span></td><td>${s.status === "success" ? '<span class="chip ok">ok</span>' : '<span class="chip bad">error</span>'}</td><td class="num">${s.duration_ms}</td><td class="note">${esc((s.output_summary || "").slice(0, 140))}</td></tr>`).join("")}</tbody></table>`;
    $("#drawer").classList.add("open"); $("#drawer-bg").classList.add("open");
  }

  // ------------------------------------------------------------------ router
  const TITLES = { dashboard: "Dashboard", close: "Close", intelligence: "Intelligence", review: "Review & release", chronograph: "Chronograph", execution: "Execution · PRISM" };
  let rendering = false, again = false;
  async function render() {
    if (rendering) { again = true; return; }
    rendering = true;
    try {
      const keepOpen = [...document.querySelectorAll(".explain.open")].map((e) => e.id);
      const y = scrollY;
      route = (location.hash || "#dashboard").slice(1);
      if (!H[route]) route = "dashboard";
      document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.r === route));
      $("#crumb").textContent = TITLES[route]; $("#title").textContent = TITLES[route];
      killCharts();
      await H[route]();
      keepOpen.forEach((id) => { const e = document.getElementById(id); if (e) e.classList.add("open"); });
      icons();
      scrollTo(0, y);
    } finally { rendering = false; if (again) { again = false; render(); } }
  }
  addEventListener("hashchange", () => { scrollTo(0, 0); render(); });
  icons();
  loadPrism();
  setInterval(loadPrism, 30000);
  refresh().catch((e) => toast(e.message, true));
})();
