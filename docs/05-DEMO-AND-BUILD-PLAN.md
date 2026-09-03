# 05 — Demo Runbook and Build Plan

---

# PART A — The demo

## 1. How judges participate without real money

Real payments are out (`CLAUDE.md` §3). What replaces them is better for the pitch,
because it lets judges hold the thing in their hands.

**Setup, 90 seconds before you start:**
1. Laptop runs the API and serves the console on the projector.
2. Phones join the same Wi-Fi (or the laptop's hotspot — bring one, venue Wi-Fi will
   fail).
3. On `/ops`, hit **Provision guest** once per judge. Each produces a handle, a ₹5,00,000
   demo balance, and a QR code rendering `http://<lan-ip>:8088/pay?as=<handle>`.
4. QR codes go on the projector. Judges scan. They are now accounts **inside the live
   graph** — their nodes appear on screen with a `--steel` ring.

That last point is the whole trick. When a judge sends a payment, a node representing
*them* lights up on the projector two seconds later. Nobody sleeps through that.

Every surface carries a "Demo ledger" chip. When asked about real money, the answer is
prepared: *"We deliberately didn't wire a payment gateway. A sandbox gateway would move
zero real rupees while implying otherwise. Our ledger is honest about being a ledger, and
it let us spend the integration time on the intervention layer instead — which is what
the problem statement actually asks for."*

## 2. Six acts

Total 8 minutes. Rehearse three times. Act 3 gets rehearsed six times.

### Act 1 — Prove we don't annoy anyone (45 s)
Judge 1 pays a known payee ₹450. Tier 0. The verdict card is one quiet green line, the
button never moves, the payment settles.

> "Most payments are ordinary. If the system punished ordinary payments it would be
> uninstalled in a week. That's the false-challenge rate on the top strip: 2.1%."

### Act 2 — The network they can't see individually (75 s)
Five judges each pay `rentals@prima` ₹18,000. Each single payment looks unremarkable —
show one on a judge's phone: tier 0 or 1.

Then click `rentals@prima` on the console. Fan-in fires. But taint is zero, retention is
high — so the score stays capped and the tier stays low.

> "Five people paying one landlord is a fan-in. So is a mule collection point. The
> difference isn't the shape, it's what happens next. We don't flag the shape alone."

That restraint is worth more than a flag would be. It proves the system has judgement.

### Act 3 — The one they'll remember (150 s)
Operator injects a sequence on Judge 2's account: new device → credentials changed →
payee added → limit raised. Then a scripted call-context text carrying isolation and
authority pressure.

Judge 2 is asked to pay `quickcash@prima` their full balance.

On the projector: TrailScore climbs, ContextFlag fires, the cross-term bonus applies,
tier hits 4. On Judge 2's phone: the verdict card, three specific facts, the ₹1-now
pacing, and the line *"We've let Priya know."*

**Then Judge 3's phone buzzes in the room** with the CircuitBreaker sheet.

Have Judge 2 tap through the warning first — deliberately. Then:

> "That's what a real victim does. Three hours into a call, someone has already told
> them a warning would appear and to ignore it. Which is why the last tier isn't a
> louder warning — it's a second person. Every one of these scams depends on isolation.
> So we break the isolation instead of the payment."

Judge 3 taps "Something's wrong — hold it". The hold extends. Judge 2's screen updates.

### Act 4 — Explain yourself (60 s)
Open the investigation drawer on Judge 2's account. Three contribution bars, the fired
rules with their points, the sequence timeline with real timestamps, context categories
without the phrases.

Then click **Download regulator record** and open the JSON on screen.

> "Same decision, three audiences. One sentence for the person. Contributions for the
> bank. A signed record of what was known at 15:41:02 for whoever audits this in eight
> months. The problem statement says an opaque score can't be acted on — this is the
> answer to that clause."

### Act 5 — Proportion (60 s)
Judge 4 reports one of the seeded transactions as fraudulent. TaintTrace propagates three
hops. ScopedHold opens downstream on an *innocent* merchant account.

Show that merchant's payer screen: ₹8,000 held with a reference number, ₹1,32,000 still
available, and the merchant successfully makes a payment on stage.

> "The account is not frozen. ₹8,000 is held, the reference is printable, the rest works.
> There is no function in our codebase that freezes an account — we deliberately didn't
> write one."

### Act 6 — The metrics the brief asked for (45 s)
Full-screen the metric strip.

> "We're not showing precision and recall. These five are the success measures named in
> the problem statement itself. The fourth one — 86% comprehension — is the number
> we're proudest of, because it's the only one that measures whether a human being
> actually understood."

## 3. Fallbacks — for every act

| Failure | Fallback |
|---|---|
| Venue Wi-Fi fails | Phone hotspot; QR codes point at the hotspot IP. Test both before the round. |
| A judge's phone won't scan | Second laptop browser at `/pay?as=<handle>` — same surface, works fine |
| CircuitBreaker doesn't fire | `/ops` → **Fire breaker (manual)** twin button; the sheet is identical |
| WebSocket drops | Console falls back to 2 s polling on `/api/console/decisions`. Build this; do not skip it. |
| GNN model won't load | `gnn_predict` already returns zeros gracefully. Console shows "GNN offline"; rules still score. Say it out loud rather than hiding it. |
| Whole backend dies | Pre-recorded 90 s screen capture of act 3 on the desktop. Have it. Never need it. |

## 4. Questions you will be asked

| Question | Answer |
|---|---|
| "Isn't RBI already building this with DPIP?" | A registry answers *who is already known bad*. Our whole subject is activity that is individually legitimate and payees nobody has listed yet. Our `fresh_fan_in` rule fires on a six-day-old account — a blocklist has zero coverage there. We plug into that layer, we don't replace it. |
| "Why not just block?" | The problem statement says blocking isn't an acceptable default, and the cost of a false block lands on someone legitimate. Our top tier still sends ₹1 and still gives the payer a Cancel button. |
| "What's your accuracy?" | We report the five metrics the brief names, on our own synthetic data with known ground truth. We won't quote an accuracy figure against real fraud, because we haven't been trained on real fraud and saying otherwise would be dishonest. |
| "Is ContextFlag NLP?" | No. It is a lexicon plus pattern matching. Real semantic understanding is on the roadmap slide, not in this build. |
| "Would a bank actually deploy this?" | It runs as a sub-process alongside the existing rules engine. It consumes the same event stream and returns a tier and a reason. It doesn't touch settlement. |
| "What about privacy?" | Mesh exchanges hashed identifiers and reason codes, never raw transactions. Trusted contacts are opt-in and nominated by the account holder. |
| "Does the trusted contact see my balance?" | No — the alert carries the amount, the payee's age, and the facts. Nothing else. Show the payload. |

---

# PART B — Build plan

## 5. Roles

| Person | Owns | Files |
|---|---|---|
| **A** | Schema, config loader, seed generator, ledger service, ops routes | `core/`, `sim/generator.py`, `routes/ops.py` |
| **B** | RingWatch port, GNN inference, TaintTrace, PathGraph | `graph/`, `scoring/ringwatch.py` |
| **C** | TrailScore, ContextFlag, lexicon, fusion, ladder | `scoring/trailscore.py`, `contextflag.py`, `fusion.py`, `ladder.py`, `context/lexicon.py` |
| **D** | Payer surface + console surface (React) | `web/` |
| **E** | ReasonLine, ScopedHold, CircuitBreaker, WebSocket layer, **rehearsal owner** | `action/`, `routes/ws.py` |

E owns rehearsal because E owns the two things most likely to fail live.

## 6. Hour-by-hour

| Hours | Everyone | Acceptance check |
|---|---|---|
| 0–1 | Repo migration: create `docs/`, `requirements.txt`, move `model.py` to `legacy/`, scaffold `web/` with Vite | `pip install -r requirements.txt` succeeds on a machine with no GPU; `uvicorn backend.api:app` starts |
| 1–4 | A: schema + config + seed 500 accounts / 21 days. B: PathGraph + RingWatch rules. C: TrailScore skeleton. D: tokens + `TierChip`/`Money`/`VerdictCard`. **E: CircuitBreaker end-to-end on two devices, in isolation, before anything else.** | `sqlite3 prima.db ".tables"` shows all 11. A phone opens `/watch/test` and buzzes from a curl. |
| 4–8 | B: GNN inference wired, taint gate. C: ContextFlag + lexicon + fusion + ladder. D: full payer compose→verdict flow against mocked JSON. A: ops routes + guest provisioning + QR. | `POST /api/payer/quote` returns a real decision with all three sub-scores non-null |
| 8–12 | E: ReasonLine three renderings + ScopedHold. D: console shell, graph, decision rail. A: `/api/ops/inject_sequence` scenarios. | A tier-4 quote produces user + bank + regulator reasons, and a scoped hold that leaves the balance spendable |
| 12–16 | Integration. WS channels live. Console updates from real decisions. Payer phone → projector graph round trip. | Act 1 and Act 3 both run end to end without operator intervention beyond the injection button |
| 16–19 | D: investigation drawer, quadrant panel, metric strip. E: comprehension probe wiring, `/api/metrics/ps3`. | All five metrics return non-zero with correct denominators |
| 19–21 | P1 only if green: PatternMemory, AdaptCal chart, Mesh, 3D toggle. Otherwise harden P0 and write fallbacks. | Every fallback in §3 tested at least once |
| 21–23 | Freeze code. Rehearse all six acts three times. Rehearse act 3 six times. Charge every device. | Two clean consecutive full runs |
| 23–24 | Buffer. Do not write code in this hour. | — |

**Hour 4 is a hard checkpoint.** If CircuitBreaker has not buzzed a second device by
hour 4, cut Mesh, AdaptCal and 3D immediately and reassign E's P1 time to it.

## 7. Cursor prompt sequence

Give Cursor `CLAUDE.md` plus the relevant spec file each time. One phase per prompt.
Do not ask for two phases in one prompt.

```
P0  Read CLAUDE.md and docs/03. Create backend/core/{db,models,config}.py implementing
    every table in docs/03 §1 as SQLModel classes, plus prima_config.yaml loading with
    a version hash. Create requirements.txt, pinned. Move backend/model.py,
    training.py, controller.py into backend/legacy/ and remove every import of them.
    Do not touch scoring yet. Acceptance: uvicorn starts on a CPU-only machine and
    sqlite3 prima.db ".tables" lists all 11 tables.

P1  Read CLAUDE.md and docs/02 §2. Create backend/graph/pathgraph.py and
    backend/scoring/ringwatch.py. Port the rule table from backend/detection.py
    unchanged, add the fresh_fan_in and dormant_wake rules, and wire gnn_predict from
    backend/gnn.py at device="cpu" with the graceful-degradation path preserved.
    Read all weights from prima_config.yaml. Acceptance: ringwatch_score(account_id)
    returns a float in [0,1] plus a list of fired rules with points, on seeded data.

P2  Read docs/02 §2. Create backend/scoring/trailscore.py and
    backend/scoring/contextflag.py, plus backend/context/lexicon.py. The lexicon module
    is the ONLY place trigger phrases may appear — they must not appear in any docstring,
    comment, log line, API response, or test fixture name. Acceptance: injecting the
    four-event chain within the window produces trailscore ≥ 0.75 with the ordered bonus.

P3  Read docs/02 §2 and docs/03 §2. Create scoring/fusion.py, scoping/ladder.py and the
    DecisionService, plus POST /api/payer/quote and /commit exactly as specified.
    quote must not mutate any balance. Acceptance: the response matches the JSON shape
    in docs/03 §2 field for field.

P4  Read docs/02 §2 and docs/04 §5. Create action/reasonline.py with user(), bank() and
    regulator(). The counterfactual is computed by dropping each fired rule, re-scoring,
    and reporting the single rule whose removal lowers the tier. The regulator record is
    written once and never updated. Acceptance: a tier-4 decision yields exactly 3 facts,
    1 counterfactual, and a sha256 that verifies.

P5  Read docs/04 §2, §3, §7. Build the web/ payer surface: tokens.css and components
    1–6. Mobile-first, max-width 440px, dark mode via the token redefinitions. The
    confirm button's vertical offset increases with tier as specified. No Tailwind, no
    component library. Acceptance: all five tier states render from fixture JSON.

P6  Read docs/04 §4. Build the console: components 7–13. react-force-graph-2d,
    cooldownTicks 120, Pause button, guest nodes with a --steel ring. Decision rail caps
    at 200 DOM rows. Acceptance: 500 nodes render at 60fps and the rail updates from
    /ws/console diffs, never from full snapshots.

P7  Read docs/02 §2 and docs/04 §5. Implement ScopedHold and CircuitBreaker plus the
    three WS channels. ScopedHold reduces available_balance only, never balance, and
    there must be no function anywhere in the codebase that freezes an account.
    Acceptance: two browsers, tier-4 quote on one fires the breaker sheet on the other
    in under 2 seconds.

P8  Read docs/05 §1–§3. Build /ops with guest provisioning + QR, one button per act,
    a manual twin for each, event injection, scripted context, and /api/ops/health.
    Acceptance: every act in §2 is runnable from /ops with no terminal commands.

P9  P1 items only, in this order: /api/metrics/ps3 hardening, PatternMemory, quadrant
    panel, AdaptCal, Mesh, 3D toggle. Stop the moment hour 21 arrives.
```

## 8. Definition of done

- [ ] Fresh clone → `pip install -r requirements.txt` → `uvicorn` → works on a CPU-only laptop
- [ ] `prima.db` regenerates from `/api/ops/seed` in under 30 seconds
- [ ] `POST /api/payer/quote` p95 under 400 ms at 500 accounts
- [ ] No `DEMO_SIM_MODE`-style client-side simulation anywhere in `web/`
- [ ] No trigger phrase appears outside `backend/context/lexicon.py` (grep it in CI)
- [ ] No function anywhere freezes an account (grep for `freeze`, assert none)
- [ ] `ground_truth_role` is never read by a scorer (assertion test)
- [ ] All five `/api/metrics/ps3` values non-zero with denominators
- [ ] Two clean consecutive rehearsals of all six acts
- [ ] Every fallback in §3 exercised at least once
