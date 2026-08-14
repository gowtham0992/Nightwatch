# Nightwatch Ledger — frontend implementation handoff

Implement the production web UI for Nightwatch from the reference design in this
directory. The deliverable is a real frontend in `web/`, not a copy of the
reference files.

## Reference files

- `ledger.dc.html` — the approved design, as a self-describing HTML file. All
  markup, inline styles, copy, and interaction logic (a small React-style
  component at the bottom of the file) are the source of truth for look,
  spacing, and behavior.
- `ledger-preview.html` + `support.js` — the same design wrapped so it renders
  standalone. Open `ledger-preview.html` in a browser (needs internet for React
  CDN + Google Fonts) to see the target result. Match it.

## What to build

A single-page app in `web/` (Vite + React, or vanilla if simpler — no other
frameworks, no CSS frameworks, no component libraries). One screen, no routing:

1. **Status band** (64px): wordmark, watching status with pulsing amber dot,
   last verdict, live UTC clock, "DEVELOPMENT EVIDENCE" chip.
2. **Orientation strip**: dismissible one-sentence explainer (amber paper tint).
3. **Evidence log** (left): chronological entries — time, agent pill, one-line
   summary, truncated hash, chevron. Click selects; selected row gets ink left
   marker + shaded background. The newest entry (the gate verdict) renders as a
   framed card with red left border containing the invariant table and the
   rotated REFUSED stamp.
4. **Evidence detail** (right, 460px): badge, title, verbatim raw block,
   optional expected/predicted rows, key-value table, plain-language note,
   footer line. Content switches with the selected entry.

## Data contract (important)

Do NOT hardcode the entry content. Build a data adapter with two modes:

- **Fixture mode (now):** load `web/fixtures/mission-04.json`, shaped as the
  journal schema below. Seed it by transcribing the `data()` array from
  `ledger.dc.html` — that copy is approved.
- **Firestore mode (later):** same schema, streamed from a Firestore collection
  (`missions/{missionId}/entries`, ordered by timestamp). Leave a clean
  interface: `subscribe(missionId, onEntry)`.

Entry schema (mirrors the backend journal):

```json
{
  "cycle_id": "mission-04",
  "stage": "created | diagnosed | curriculum_ready | trained | evaluated | rejected | promoted",
  "timestamp": "ISO-8601",
  "agent": "scheduler | evaluator | diagnostician | curriculum-architect | trainer | gate",
  "entry_hash": "sha256, display first4…last3",
  "summary": "one sentence",
  "exhibit": {
    "badge": "string", "tone": "red | amber | neutral",
    "title": "string", "rawLabel": "string", "raw": ["lines"],
    "labels": {"expected": "page_now", "predicted": "investigate"},
    "kv": [["key", "value"]], "note": "plain-language sentence"
  },
  "verdict": {
    "present_only_on_gate_entries": true,
    "rows": [{"name": "regression", "value": "83.75%", "threshold": "≥ 80%", "result": "PASS | FAIL"}],
    "decision": "REFUSED | PROMOTED",
    "policyLine": "eval sha256 c33011c4…5b0edf · policy immutable",
    "ghosts": "always-page REFUSED · always-investigate REFUSED · always-defer REFUSED"
  }
}
```

## Design tokens (extract into CSS variables)

- Fonts: Roboto (UI), Roboto Mono (ALL measured things: numbers, hashes,
  labels, timestamps, verdict rows). Never mix these roles.
- Paper: page `#F7F6F1`, panel `#FCFBF7`, code block `#F1EFE8`,
  selected `#EFEDE5`; hairlines `#E3E1D8` / `#E9E7DE`, strong `#D6D3C8`.
- Ink: `#22231E` primary, `#55564E` secondary, `#8A8B80` tertiary,
  `#B0B1A6` faint.
- Semantic (used nowhere else): amber `#D99A3D` dot / `#A66A12` text;
  red `#C2392F` (stamp, FAIL) with tints `#FBEFED` / `#FDF9F7` / `#E8CFC9`;
  green `#256E43` reserved for PROMOTED only.
- Stamp: 2.5px red border, 1px offset outline, `rotate(-1.5deg)`,
  letter-spacing 0.26em.

## Behavior

- Entry click → exhibit updates. Default selection: the newest (gate) entry.
- Live clock ticks every second (UTC, HH:MM:SS).
- Amber dots pulse (2.8s ease opacity keyframes). This is the ONLY idle motion.
- Hover: rows shade to `#F1F0EA`; nothing else animates.
- PROMOTED verdicts (future data) render the same card with green decision
  styling; do not invent extra celebration effects.

## Hard bans

Dark theme, gradients, glassmorphism, shadows on cards, icons/emoji/avatars,
chat UI, spinners or "thinking" shimmer, any number not sourced from the data
adapter, any component library. If a value isn't in the fixture, it does not
appear on screen.

## Acceptance

Side-by-side with `ledger-preview.html` at 1440×900: same layout, same
hierarchy, same copy, working selection/dismiss/clock, and `npm run build`
producing a static bundle servable by any static host (final target: Cloud Run).
