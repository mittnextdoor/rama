# RAMA demo video: partner production brief

Date: October 17, 2026  
Status: proposed production plan; functionality must be verified before recording.  
Working format: four-minute master and a 60-second cutdown. Confirm the submission time limit before locking the script.

## The story

**RAMA — From books to foresight.**

Follow a number from a borrower's books to an approved LP risk insight. Show why the intelligence is trustworthy: the accounting reconciles, deterministic rules calculate, the model explains, and a person approves publication.

The hero is a synthetic AI-infrastructure borrower whose public proxy is CoreWeave (CRWV), with a loan from our synthetic private debt fund. This is not CoreWeave's actual accounting or a claim about its private borrowing.

This brief reflects the latest agreed scope. Earlier repository plans that begin by closing the fund itself need to be reconciled with this borrower-first workflow.

## Product scope: five stages

### 1. Accounting

RAMA's agents close one portfolio company's month using a general ledger or trial balance export plus bank statements. The output is reconciled financial statements and workpapers linked to their sources. Unsupported items remain explicit exceptions.

### 2. Intelligence

Combine verified accounting with the five files in the Cap IQ fast-pull specification:

- Screener snapshot.
- Probability of default and price on three dates.
- Key developments.
- Debt maturities.
- Default study.

The intended rules are:

| Source group | Rules |
| --- | --- |
| Cap IQ, plus required loan mappings and terms | R3, R4, R7, R10, R11 |
| Fund accounting and required fund/LP records | R1, R2, R12, R13, R14 |
| Public H100 rental index, explicitly labeled non-S&P | R5 |

Verify each rule's complete input requirements before recording. The source groups above describe the intended workflow; they do not establish that the five files contain every required field. Missing inputs produce a visible “not evaluated” state, never invented values.

The borrower's indicators roll up into the fund. Other loans, L1 and L3–L6, are synthetic stand-ins tied to their public proxies. Distinguish borrower accounting from separate fund inputs: borrower books alone cannot establish fund leverage headroom or LP liquidity limits.

### 3. Cards

The model words only what the deterministic rules computed. Every card includes its sources and as-of dates. A language blocklist and classifier block investment advice. The standing disclosure appears on every relevant view.

### 4. Approval and demonstration destination

A reviewer approves indicators individually or as a package. Approved data visibly travels along a fiery line into a Chronograph-style destination, where it appears in an LP reporting context.

Keep this label visible: **“Demonstration destination — no live Chronograph connection.”** Use the approved cards as the destination's data; do not imply an actual API delivery or endorsement.

### 5. Execution evidence

Every model call goes through Nicrron. PRISM uses the Agent Frameworks integration, with the close, rules, and card agent in one session. Verify this in the actual dashboard before showing it as completed.

## Visual direction

Use dark graphite backgrounds, crisp financial tables, amber highlights, and a glowing line that follows the data. The line becomes fiery at approval and release.

Most footage should show the actual application. Use Higgsfield for a short opening and transitions. Keep readable UI, figures, and source citations in real captures or code-rendered overlays so they remain precise.

Three moments carry the film:

1. **Evidence reveal:** open a financial result, its workpaper, and the supporting statement together.
2. **Explanation reveal:** expand a card into its computed metric, threshold, source, and as-of date.
3. **Approval release:** approve the package; the amber line ignites and carries those exact cards into the demonstration destination.

## Four-minute storyboard

| Time | Picture and action | Narration direction |
| --- | --- | --- |
| 0:00–0:15 | Documents, ledger grids, and market signals connect through one amber line. RAMA reveal. | “A borrower's books tell you what happened. Market signals show what is changing. RAMA connects the two.” |
| 0:15–0:35 | Introduce the synthetic borrower and its loan within the six-loan fund. Label “Synthetic borrower · Public proxy: CRWV.” | Establish borrower, fund, and LP perspectives. Explain the proxy's role as market context. |
| 0:35–1:15 | Upload books and bank statements. Run the close. Inspect a discrepancy, its supported resolution, and a workpaper with its source. | Explain reconciliation, supported corrections, and evidence-backed outputs. |
| 1:15–1:55 | Show the five Cap IQ files, verified accounting inputs, and separately labeled H100 index. Run rules and follow borrower indicators into the fund view. | “Verified accounting meets dated market evidence. Fixed rules calculate the indicators and explain which thresholds were crossed.” |
| 1:55–2:30 | Open three representative cards. Expand one to reveal metric, threshold, source, and calculation. Show an advisory sentence blocked in a controlled test. | Explain that the model phrases computed results and guardrails check publication. |
| 2:30–3:00 | Approve individual cards and then the package. Fiery line travels to the labeled Chronograph-style destination. Approved cards appear. | Explain human release and the simulated downstream reporting handoff. |
| 3:00–3:40 | PRISM session: close, rules, card generation, and guardrail result. Show evidence of Nicrron routing. | Explain inspectable execution. Include before/after evaluation only if verified for the demonstrated scope. |
| 3:40–4:00 | Trace a card back to its source, then pull out to the full workflow and RAMA end card. | “From reconciled books to reviewed intelligence. RAMA makes the path visible.” |

Choose the three featured cards after testing the actual dataset. Favor the strongest supported results. Briefly show the full indicator overview without narrating every rule.

The table is a storyboard and narration direction, not the final full-length voiceover. Write and time the complete script after the recording path is stable.

## Production tools

| Tool | Responsibility |
| --- | --- |
| Claude Code | Prepare/reset demo data, automate browser capture, create precise overlays and transitions, assemble the timeline, generate captions, and render exports. Proposed editing approach: a React/Remotion composition, subject to local setup. |
| Higgsfield | Generate two or three short atmospheric shots for the opening, transitions, and closing background. |
| ElevenLabs | Produce one calm, confident narrator in separate scene clips. Use timing information to synchronize captions and screen actions. |

Generate a rough narration track first. Edit screen recordings against it, then generate the final voiceover after the script is stable. Use subtle cues for reconciliation, evidence opening, and approval. Keep music below speech and hold important figures long enough to read.

### Starting Higgsfield prompt

> Cinematic financial technology opening, dark graphite environment, anonymous financial documents and abstract ledger grids, one warm amber light tracing a path through the scene, restrained institutional aesthetic, slow controlled camera push, realistic lighting, no readable text, no logos, no invented interface, 16:9.

Add the RAMA title, figures, and readable text during editing.

Tool references:

- [Higgsfield camera controls](https://higgsfield.ai/camera-controls)
- [ElevenLabs speech with timing](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps/)

## Build and production order

### Step 1: lock the scenario and evidence

- Use one consistent borrower, loan ID, period, balances, and source dates across all screens and traces.
- Build a source-to-rule checklist covering every required field, unit, date, threshold, and source reference.
- Identify how borrower results aggregate into fund indicators and where separate fund/LP data is required.
- Verify synthetic labels, public-proxy labels, the non-S&P index label, and the standing disclosure.

### Step 2: make the recording path repeatable

- Provide one command to reset the synthetic scenario.
- Script the browser journey with deliberate pauses and consistent framing.
- Capture the close, evidence reveal, rules, cards, approval, and destination.
- Verify that only approved cards reach the demonstration destination.
- Distinguish staged conceptual views from functioning application behavior.

### Step 3: capture execution proof

- Verify Nicrron model routing and the PRISM Agent Frameworks connection.
- Capture one session containing accounting tools, rule outputs, model calls, and guardrail results.
- Show alerts or failure clusters only after verifying them in PRISM.
- Keep the existing 72-case close evaluation separate from any new intelligence evaluation.

### Step 4: assemble a rough cut

- Write the complete narration against the recorded journey.
- Generate temporary scene-level narration.
- Assemble the four-minute timeline with real application captures.
- Check pacing and readability before generating cinematic assets.

### Step 5: finish and export

- Generate the selected Higgsfield shots and final ElevenLabs narration.
- Add overlays, the approval animation, captions, and restrained sound design.
- Review every displayed number and claim against its source.
- Export a 16:9, 1080p master, captions, and a local backup.
- Derive the 60-second cutdown from the approved master.

## Suggested ownership

Assign names before starting; these are workstreams, not existing commitments.

| Workstream | Responsibility |
| --- | --- |
| Product/evidence owner | Scenario, accounting outputs, rule inputs, source dates, aggregation, trace verification. |
| Video/creative owner | Storyboard, narration, Higgsfield assets, ElevenLabs voice, pacing, final review. |
| Claude Code support | Reset scripts, browser capture automation, video composition, overlays, captions, rendering. |

## Submission story changes

Update the project answers around the complete borrower-to-LP workflow:

| Section | Revised emphasis |
| --- | --- |
| Inspiration | The disconnect between borrower accounting, market developments, and LP visibility. |
| What it does | The five-stage workflow, human approval, and explicitly simulated downstream destination. |
| How we built it | Deterministic accounting and rules, source-backed cards, advice guardrails, Nicrron, and PRISM. |
| Challenges | Source alignment, proxy interpretation, dated inputs, borrower-to-fund aggregation, and evidence through publication. |
| Accomplishments | Completed and demonstrated functionality. Label the earlier 72-case results as close-engine evaluation. |
| What we learned | Useful intelligence depends on reliable accounting and traceable calculations. |
| What's next | Broader validation, additional borrowers, production ingestion, and a real downstream integration. |

Do not describe planned fund/LP functionality as built until verified. Do not carry earlier close-only evaluation results into claims about intelligence accuracy.

## Delivery checklist

- [ ] Submission duration confirmed.
- [ ] Scenario and source-to-rule checklist complete.
- [ ] End-to-end application journey recorded.
- [ ] PRISM session and Nicrron routing verified.
- [ ] Storyboard and full narration finalized.
- [ ] Higgsfield prompts and selected assets saved.
- [ ] ElevenLabs scene audio generated.
- [ ] Editable composition and capture/reset scripts included.
- [ ] Four-minute master and caption file exported.
- [ ] 60-second cutdown exported.
- [ ] Backup playback checked.
- [ ] Submission answers updated to match the demonstrated scope.
