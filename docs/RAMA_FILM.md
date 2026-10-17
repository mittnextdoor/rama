# RAMA film: how it is made and how to finish it

The storyline is the owner's `RAMA_VIDEO_STORYLINE.md` (2026-10-17), with the app's names (Helios Compute, RAMA Credit
Fund I, Hudson State Teachers' Pension) and the app's own figures. Three layers, never mixed:

| Layer | Made by | Carries |
|---|---|---|
| Cinematic | Higgsfield (FLUX.2 keyframes → Kling 3.0 clips), through the `higgsfield` CLI | mood and motion only; no text, numbers, logos, faces |
| Precision | Remotion overlays (`video/rama/src/ui.tsx`, `scenes.tsx`) | every word and number, from `video/shotlist.json` → `app_values` |
| Proof | Playwright captures of the real app (`video/capture.cjs`) | the close, evidence, indicators, cards, guardrail, approval, destination |

## Files

```
video/shotlist.json          the seven Higgsfield shots, capture slots, app values
video/selection.json         which keyframe variant each shot uses ({"documents": 2}; others v0)
video/narration.json         the narrator's lines per scene (Arthur, ElevenLabs v4 via Higgsfield)
video/higgsfield/            keyframes *_vN.png, clips *_vN.mp4, manifest.json (prompts, job ids)   [not in git]
video/narration/             scene00..12.mp3 + manifest.json                                           [not in git]
video/captures/              CAPTURE_03..12.webm from capture.cjs; CAPTURE_11.webm is the PRISM screen  [not in git]
video/rama/                  the Remotion project (src/, scripts/, out/)
```

## Render

```
cd video/rama
node scripts/media.js                 # index the media and copy it into public/ (placeholders for anything missing)
node scripts/srt.js                   # out/rama_master.srt
npx remotion render src/index.ts Master out/rama_master_3m.mp4 --codec h264
npx remotion render src/index.ts Cutdown out/rama_cut_60s.mp4 --codec h264
npx remotion studio src/index.ts      # to scrub and adjust
```

## Re-record the captures

With the app running on 8810 (`.venv/bin/python -m rama.api --port 8810`):

```
PW=$HOME/Downloads/bookkeeping-practice/web/node_modules/playwright node video/capture.cjs
```

It resets the scenario, runs the close, makes the reviewer's two decisions through the API, builds the indicators,
runs the guardrail test, approves three cards and holds one, releases, and records each slot to `video/captures/`.

**CAPTURE_11 (PRISM) is recorded by hand:** sign in at prism.blockconvey.com, open Agent Runs, filter the session
`helios-2026-09`, scrub the steps (close tools → rules → card model calls via Nicrron → the guardrail block), and save
a 1920×1080 screen recording as `video/captures/CAPTURE_11.webm` (or .mp4; then change the extension in
`scripts/media.js`). Show only what the dashboard shows.

## Regenerate media

```
python3 <scratch>/keyframes.py        # 3 FLUX.2 variants per shot (≈1 credit each)
python3 <scratch>/animate.py <shot…>  # Kling 3.0, 5 s from the chosen keyframe (≈10 credits each)
```

Both scripts live in the session scratchpad; the manifest in `video/higgsfield/manifest.json` records every prompt,
job id and result URL. Higgsfield keeps outputs about seven days; the downloaded files are the record.

## Before the final cut (storyline Part 6)

- Replace every `{{read from the app}}` in `shotlist.json` → `app_values` with the run used for the captures
  (R1 ratio, R5 LTV, Hudson's L2 exposure are in the app's Intelligence screen).
- Check each Higgsfield frame for legible text (the documents shot uses variant 2 for that reason).
- The PRISM capture must be the real dashboard; the 72-case close evaluation is never presented as intelligence accuracy.
- The narration is a rough-cut voice; re-generate after the script is final (`narration.json`, ≈0.5 credit a line).
