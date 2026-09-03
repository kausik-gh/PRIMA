# 04 — UI Specification

Everything here is buildable from this document alone. No screen is left to interpretation.

---

## 1. Design position

PRIMA is bank infrastructure, not a security product. So it deliberately avoids the
dark-HUD, neon-graph, glowing-threat look that every fraud demo reaches for. It is a
**light, dense, quiet interface where colour is reserved entirely for risk tier** — if
something is coloured, it means something. That constraint is the design.

One bold idea, spent in one place: on the payer surface, **the confirm button moves
further down the screen as the tier rises.** Friction is expressed as physical distance,
not as a modal. At tier 0 the button is under your thumb. At tier 4 you have to travel
past three facts, a counterfactual and a countdown to reach it. Nothing else in the
interface is allowed to be showy.

---

## 2. Tokens — `web/src/styles/tokens.css`

```css
:root {
  /* Base — cool, institutional, not cream */
  --ledger:    #E8EBEF;   /* app background */
  --surface:   #FFFFFF;   /* cards, panels */
  --surface-2: #F3F5F8;   /* inset areas, table stripes */
  --hairline:  #D2D8DF;   /* 1px rules */
  --ink:       #16202B;   /* primary text */
  --graphite:  #5A6875;   /* secondary text */
  --steel:     #1F5C8C;   /* the ONLY interactive accent */

  /* Risk tiers — the ramp breaks at tier 4 on purpose */
  --t0: #3E7C5A;  --t0-bg: #E7F1EC;
  --t1: #A8781F;  --t1-bg: #F7EFDD;
  --t2: #C0552B;  --t2-bg: #FAEAE2;
  --t3: #97232B;  --t3-bg: #F8E4E5;
  --t4: #5A3596;  --t4-bg: #EEE8F7;   /* violet: a different KIND of action,
                                          not merely a hotter red */

  /* Type */
  --font-ui:   "IBM Plex Sans", system-ui, sans-serif;
  --font-data: "IBM Plex Mono", ui-monospace, monospace;

  --t-display: 2.25rem/1.15  600;   /* payer verdict headline only */
  --t-h1:      1.375rem/1.3  600;
  --t-h2:      1.0625rem/1.35 600;
  --t-body:    0.9375rem/1.55 400;
  --t-small:   0.8125rem/1.45 400;
  --t-data:    0.8125rem/1.4  500;  /* --font-data */

  /* Space — 4px base */
  --s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px;
  --s5: 24px; --s6: 32px; --s7: 48px; --s8: 72px;

  --r-sm: 4px; --r-md: 8px; --r-lg: 14px;
}
```

**Mono is used for exactly three things:** account handles, money amounts, and reference
numbers. Nowhere else. It is there for column alignment, not atmosphere.

**Rules of the palette**
- No gradients anywhere.
- No shadows except one: `0 1px 2px rgba(22,32,43,.08)` on floating elements only
  (the investigation drawer, the circuit-breaker sheet).
- Tier colour appears on: node fill, log row left edge, verdict card border, tier chip.
  It never appears on background washes or headers.

**Dark mode:** required, because the artifact viewer may be in either theme. Redefine the
same tokens under `@media (prefers-color-scheme: dark)` and `:root[data-theme="dark"]`,
keeping tier hues but lifting lightness ~15%.

---

## 3. Surface A — Payer (`/pay`, mobile-first, max-width 440px)

### 3.1 Compose step
```
┌──────────────────────────────────┐
│  PRIMA   ·  Demo ledger          │  ← persistent honesty chip, always visible
├──────────────────────────────────┤
│  Balance      ₹5,00,000          │  mono
│  Available    ₹5,00,000          │  mono; differs when a hold is active
├──────────────────────────────────┤
│  Pay to                          │
│  ┌────────────────────────────┐  │
│  │ quickcash@prima            │  │  mono input
│  └────────────────────────────┘  │
│  Amount                          │
│  ┌────────────────────────────┐  │
│  │ ₹ 4,00,000                 │  │  mono input
│  └────────────────────────────┘  │
│  What's this for? (optional)     │
│  ┌────────────────────────────┐  │
│  │                            │  │  ← ContextFlag reads this
│  └────────────────────────────┘  │
│                                  │
│  [        Check and pay        ] │  full-width, --steel
└──────────────────────────────────┘
```
"Check and pay" — not "Continue". The button names what happens: we check, then you pay.

### 3.2 Verdict step — the pre-commitment moment

Fires on `POST /api/payer/quote`. **The result must appear in under 400 ms or the moment
is lost.** Show a 1-line skeleton, never a spinner overlay.

**Tier 0** — the verdict card is a single quiet line. Do not celebrate a pass.
```
│  ✓ Nothing unusual about this account.        │  --t0, --t0-bg, 1px --t0 left edge
│  [           Pay ₹4,000            ]          │  ← button stays high on screen
```

**Tier 1**
```
┌──────────────────────────────────────────────┐
│ ▌ This account is new to the network.        │  --t1
│                                              │
│   Opened 6 days ago                          │
│   3 people have sent it money today          │
│   You have never paid it before              │
└──────────────────────────────────────────────┘
   This would not have been flagged if the     ← counterfactual, --graphite, --t-small
   account were older than 30 days.
   [            Pay ₹4,000            ]
```

**Tier 2** — challenge. The confirm button is disabled until both are answered.
```
┌──────────────────────────────────────────────┐
│ ▌ This account is behaving like a            │  --t2
│   collection point.                          │
│   … three facts …                            │
├──────────────────────────────────────────────┤
│  Who is this person to you?                  │
│  ┌────────────────────────────────────────┐  │
│  │                                        │  │  free text, min 3 chars,
│  └────────────────────────────────────────┘  │  NOT a dropdown — a scammer
├──────────────────────────────────────────────┤  can't script an answer they
│  What did we tell you about this account?    │  don't know
│  ( ) It was opened recently and many people  │
│      are paying it                           │  ← comprehension probe
│  ( ) Your bank is closed for maintenance     │
│  ( ) The amount is above your daily limit    │
└──────────────────────────────────────────────┘
   [         Pay ₹4,00,000          ]   disabled until answered
```
The free-text question is the anti-script mechanism: a person following instructions from
a stranger cannot answer "who is this to you" in their own words. Say this on stage.

**Tier 3** — paced, not blocked.
```
┌──────────────────────────────────────────────┐
│ ▌ Money sent here usually leaves within      │  --t3
│   minutes.                                   │
│   … three facts …                            │
├──────────────────────────────────────────────┤
│  We'll send ₹1 now.                          │
│  ₹3,99,999 goes in 30 minutes.               │  mono
│  You can cancel any time before then.        │
│                                              │
│  ┌──────────────────────────────────────┐    │
│  │  29:47 remaining      [ Cancel ]     │    │  live countdown from WS
│  └──────────────────────────────────────┘    │
└──────────────────────────────────────────────┘
   [        Send ₹1 and start the wait       ]  ← button now ~60% down the screen
```
Copy discipline: never "blocked", never "declined", never "suspended". The words are
*paced*, *waiting*, *cancel any time*. The payment is not refused; it is slowed.

**Tier 4** — everything in tier 3, plus one added line above the button:
```
│  We've let Priya know. She can approve this  │  --t4
│  or ask us to keep holding.                  │
│  ⌛ Waiting for Priya · 0:42                  │  mono
```
When the trusted contact acks, this line updates in place over `/ws/pay/{account_id}`.
Approved → the hold releases and the line becomes `Priya approved this at 3:41 pm.`

### 3.3 States to build
| State | Treatment |
|---|---|
| Payee handle not found | Inline under the field: "No account with that handle in the demo ledger." |
| Amount over available balance | Inline: "Available balance is ₹X. Holds don't reduce your balance, only what you can spend right now." |
| Scoring failed | Fail **open** with a visible degradation chip: "Checks unavailable — this payment was not scored." Never silently pass as safe. |
| Hold active on the account | Persistent banner at top with reason ref, held amount, release time, and a contest link |

---

## 4. Surface B — Bank console (`/console`, desktop ≥ 1280px)

```
┌────┬───────────────────────────────────────────────┬──────────────────────────┐
│    │  Prevented  Lead time  False chal  Compreh.   │  Live decisions          │
│ P  │  ₹8.4L      47 s       2.1%        86%        │  ┌────────────────────┐  │
│ R  ├───────────────────────────────────────────────┤  │▌4 quickcash@prima  │  │
│ I  │                                               │  │ ₹4,00,000  0.83    │  │
│ M  │            [ live force graph ]               │  │ fresh_fan_in       │  │
│ A  │                                               │  │ 15:41:02           │  │
│    │        nodes = accounts                       │  ├────────────────────┤  │
│ ●  │        edges = transactions                   │  │▌2 rentals@prima    │  │
│ ○  │        fill  = tier colour                    │  │ ₹18,000    0.52    │  │
│ ○  │        ring  = scoped hold active             │  │ fan_in             │  │
│    │                                               │  ├────────────────────┤  │
│ ── │                                               │  │▌0 kirana@prima     │  │
│ A  │  [2D|3D]  [All banks ▾]  [Pause]  [Fit]       │  │ ₹450       0.04    │  │
│ B  ├───────────────────────────────────────────────┤  └────────────────────┘  │
│ C  │  Sender state ↕ / Beneficiary history ↔       │  Filter: [All ▾][Tier≥2] │
└────┴───────────────────────────────────────────────┴──────────────────────────┘
```

### 4.1 Left spine (64px)
System mark, then: Live, Decisions, Holds, Patterns, Metrics. Below a rule: bank
switcher A / B / C for the Mesh demo. Icon + tooltip only, no labels — the spine never
competes with the graph.

### 4.2 Metric strip (top, 72px)
The five PS3 metrics from `/api/metrics/ps3`. Value in `--font-data` at 1.5rem, label
below in `--t-small` `--graphite`. Each cell shows its denominator on hover. No sparkline
unless the value is genuinely time-series (lead time is; comprehension rate is not).

### 4.3 Graph stage
- `react-force-graph-2d`. Node radius scales with `log(transaction_count)`, clamped 4–14px.
- Node fill = tier colour. Node stroke = 2px `--t3` ring when a ScopedHold is active.
- Guest (judge) accounts get a 3px `--steel` outer ring so they are findable instantly on
  stage. This matters more than it sounds — you will need to point at a judge's node.
- Edge width scales with `log(amount)`. Edge colour `--hairline` normally,
  tier colour when the edge carries taint > 0.15.
- New edges animate once on arrival (a 600 ms travelling dot) and then go static. This is
  the only non-user-triggered motion in the product.
- Freeze layout after `cooldownTicks: 120`. A permanently jiggling graph reads as unstable.
- 3D toggle swaps to `react-force-graph-3d` with the identical data shape. P1.
- **Pause** button. Essential: you cannot explain a moving graph on stage.

### 4.4 Live decision rail (right, 380px, fixed)
One row per decision, newest at top, capped at 200 in the DOM.

```
▌  tier chip   handle (mono)          amount (mono, right aligned)
   top fired rule code                fused score (mono)
   hh:mm:ss                           verdict word
```
Left edge is 3px of tier colour — this is the only place the eye needs to go. Click a row
→ opens the investigation drawer and centres that node in the graph.

New rows slide in from the top over 180 ms. When paused, they queue and a chip shows
"12 new".

### 4.5 Investigation drawer (right-side overlay, 560px)
Opens over the graph, not beside it.

```
  ramesh@prima                                    tier 4 · 0.83
  Opened 6 days ago · BANKA · device d_44a1

  Contribution
  RingWatch   ████████████░░░░  0.71 × 0.40 = 0.284
  TrailScore  ██████████████░░  0.82 × 0.35 = 0.287
  ContextFlag ████████░░░░░░░░  0.55 × 0.25 = 0.138
  Cross-term                            + 0.150
                                        ───────
                                          0.859

  Rules fired
  fresh_fan_in     3   account 6 days old, in-degree 14
  pass_through     2   retention ratio 0.04
  shared_device    3   4 accounts on device d_44a1

  Sequence (last 15 min)
  15:26  new device signed in
  15:31  credentials changed
  15:34  payee quickcash@prima added
  15:38  transfer limit raised ₹50k → ₹5L
  15:41  transfer attempted ₹4,00,000

  Context
  secrecy 0.30 · fear 0.30                ← categories only, never the matched text

  Pattern match      89% · sequence_takeover        (P1)

  [ Open scoped hold ]  [ Mark reviewed ]  [ Download regulator record ]
```

The three contribution bars reuse the SHAP category-bar visual language from the prior
build — same shape, different inputs. Reusing a familiar chart is a feature: it makes the
"we ported this, we didn't rebuild it" story visible.

**The context row shows categories and weights only.** Never the matched phrase. This is
a hard rule (`CLAUDE.md` §3.6) and it is also a good line on stage: "we don't print the
trigger words, because this screen gets shared."

### 4.6 The quadrant panel (bottom strip, collapsible)
The 2×2 from `docs/01` §2, plotted live: x = beneficiary history risk (RingWatch),
y = sender state risk (TrailScore). Four labelled cells:

```
 sender     │  Compromised sender,     │  Both sides bad
 state      │  clean-looking payee     │  (classic mule ring)
 risk       │  ◀ REGISTRIES MISS THIS  │
    ▲       ├──────────────────────────┼─────────────────────────
    │       │  Ordinary                │  Known-bad payee,
    │       │                          │  normal sender
    └───────┴──────────────────────────┴──────────────────────▶
              beneficiary history risk
```

Every scored decision is a dot. The top-left cell is highlighted with `--t4` and labelled.
This one panel is the whole architectural argument, and it is a 40-line component.

---

## 5. Surface C — Trusted contact (`/watch/{token}`, mobile)

Idle state is deliberately almost empty:
```
┌──────────────────────────────┐
│  PRIMA  ·  Demo ledger       │
│                              │
│  You're watching for Ramesh. │
│  Nothing needs you right now.│
│                              │
│  ● connected                 │  --t0 dot, small
└──────────────────────────────┘
```
An empty screen here is correct — the whole value is that it stays empty until it doesn't.

On `circuit_breaker.fired`, a full-height sheet slides up over 240 ms, `--t4-bg`,
plus `navigator.vibrate([200,100,200])` where supported.
```
┌──────────────────────────────────────┐
│                                      │
│  Ramesh is about to send             │  --t-display
│  ₹4,00,000                           │  mono, largest element on the screen
│  to an account opened 6 days ago.    │
│                                      │
│  14 people sent money to that        │
│  account today                       │
│  Ramesh has never paid it before     │
│  His transfer limit was raised       │
│  8 minutes ago                       │
│                                      │
│  [   Something's wrong — hold it   ] │  --t4 filled, listed FIRST
│  [        This is fine             ] │  outline, second
└──────────────────────────────────────┘
```
The protective action is listed first and is the filled button. A person woken by an
alert taps the prominent thing; the prominent thing should be the safe thing.

---

## 6. Surface D — Operator console (`/ops`)

Must look unmistakably like a control panel, not a product: `--surface-2` background,
mono labels throughout, no rounded corners. Nobody should ever confuse a screenshot of
this with the deliverable.

Contents: guest provisioning with a rendered QR per judge, one button per demo act, an
event-injection form, a scripted-context textarea, an attack-pattern dropdown, a
`/api/ops/health` readout, and a red Reset.

Every act button has a **manual twin** directly beneath it that performs the same state
change without the scripted animation. That twin is the fallback when something hangs on
stage.

---

## 7. Component inventory (build in this order)

| # | Component | Used by | Phase |
|---|---|---|---|
| 1 | `TierChip` | everywhere | 5 |
| 2 | `Money` (paise → ₹ formatted, mono, tabular-nums) | everywhere | 5 |
| 3 | `VerdictCard` | payer | 5 |
| 4 | `FactList` | payer, watch | 5 |
| 5 | `LadderAction` (5 tier variants, incl. countdown) | payer | 5 |
| 6 | `ComprehensionProbe` | payer | 5 |
| 7 | `MetricStrip` | console | 6 |
| 8 | `RiskGraph` (2D, 3D toggle) | console | 6 |
| 9 | `DecisionRail` | console | 6 |
| 10 | `ContributionBars` | console drawer | 6 |
| 11 | `EventTimeline` | console drawer | 6 |
| 12 | `InvestigationDrawer` | console | 6 |
| 13 | `QuadrantPanel` | console | 6 |
| 14 | `BreakerSheet` | watch | 7 |
| 15 | `HoldBanner` | payer | 7 |
| 16 | `OpsPanel` | ops | 8 |

---

## 8. Copy rules

1. Sentence case everywhere. No all-caps labels.
2. On the payer and watch surfaces, these words are banned: **fraud, mule, scam,
   criminal, illegal, blocked, declined, suspended, frozen.** Describe behaviour, not
   character. Legal exposure and comprehension both improve.
3. Buttons name their outcome. "Send ₹1 and start the wait", not "Continue".
4. Every number on a payer screen is checkable by the payer against their own knowledge.
   If a fact cannot be checked by the person reading it, it does not belong on that screen.
5. Empty states give direction, not mood. "Nothing needs you right now." not "All clear!"
6. Errors say what happened and what to do. They do not apologise.

## 9. Accessibility floor

Contrast ≥ 4.5:1 for all text on its background (all tier colours above are checked
against their `-bg` pairs). Visible `--steel` focus ring, 2px offset. Full keyboard path
through the payer flow. `prefers-reduced-motion` disables the edge animation, the rail
slide and the breaker sheet transition — the breaker sheet still appears, instantly.
Tier is never carried by colour alone: every tier surface also shows the tier number in
the chip.
