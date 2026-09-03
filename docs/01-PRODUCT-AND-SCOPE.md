# 01 — Product and Scope

## 1. The reframe that decides everything else

Every other team on this problem statement will build **a better detector**. The problem
statement says, in its own words, that detection after the fact is not the gap:

> *The real problem is not detecting fraud or loss after it has occurred — it is
> surfacing, before the point of irreversible commitment, the risk that exists only in
> the sequence, network or context.*

So PRIMA is judged on three things a detector does not do:

1. **When** it speaks — before confirmation, with measurable lead time.
2. **How** it responds — proportionately, on a ladder, never a binary block.
3. **Whether the person understood** — comprehension is a named success metric in the PS.

A dashboard that shows a graph and a risk score answers none of these. The previous
project was exactly that dashboard. This one is not.

---

## 2. Three harm locations → three scorers → one decision

| PS says harm hides in | Scorer | What it reads | Origin |
|---|---|---|---|
| The **network** | `RingWatch` | Graph topology around both parties: fan-in, fan-out, ring, smurfing, shared device, pass-through retention, plus an inductive GNN score | Ported from the mule repo (`features.py`, `detection.py`, `gnn.py`) |
| The **sequence** | `TrailScore` | The last N minutes of *non-payment* events on the sender's account: new device, payee added, limit raised, credential change | New |
| The **context** | `ContextFlag` | Language in the payment note and, in demo, a scripted call-context feed: urgency, secrecy, fear, greed, approval-bypass | New |

These fuse into one `RiskDecision`, which drives one `Interrupt Ladder` tier, which is
rendered three ways by `ReasonLine`.

**The single most important architectural claim, and the one to say on stage:**

> We score **two sides independently** — the beneficiary's history, and the sender's
> current state — and fuse them. The dangerous case is not "both are bad." It is
> **sender-risk high, beneficiary-risk low** — a fresh mule account nobody has
> blocklisted yet, being paid by someone mid-way through an account takeover or a
> social-engineering call. A negative registry has zero coverage there by construction.
> That quadrant is our product.

Render this as a literal 2×2 in the console. See `docs/04` §7.

---

## 3. Surfaces

Three surfaces, one decision object behind all of them.

### Surface A — Payer (mobile web, route `/pay`)
The person about to press Pay. Judges use this on their own phones via a QR code.

- Enter payee + amount → **beneficiary verdict card** appears before the confirm button
  is live.
- Verdict is one of four categories, derived from the fused score (see §4).
- Below the verdict: **three checkable facts**, never a generic warning.
- Above tier 1, the confirm button changes shape according to the ladder tier.

### Surface B — Bank console (desktop, route `/console`)
Risk-operations view. This is what a bank deploys.

- Live force-directed graph. Nodes = accounts, edges = transactions. 2D by default,
  3D toggle.
- Right-hand **live decision log**: every scored attempt streaming in with amount,
  sender, receiver, tier, fused score, and the top fired rule.
- Click any node → **investigation drawer**: the three sub-scores, contributions,
  event timeline, PatternMemory match, and the actions available.
- Top strip: the five PS3 metrics, live.

### Surface C — Trusted contact (mobile web, route `/watch/{token}`)
A second phone in the room. Silent until a tier-4 CircuitBreaker fires, then it buzzes
with a specific, named alert. This is the moment the panel remembers.

### Surface D (internal) — Operator console (route `/ops`)
Not shown to judges as a product. Used on stage to inject event sequences, advance demo
acts, and act as the fallback for every live moment. Must be visually distinct from the
product surfaces so nobody confuses it with the deliverable.

---

## 4. Beneficiary verdict categories

The user asked for a category, not a number. Four states, mapped from the fused score.
Thresholds live in `prima_config.yaml`; these are the defaults.

| Verdict | Fused score | Payer copy (headline) | Ladder tier |
|---|---|---|---|
| **Known to you** | any, if ≥1 prior successful payment from this sender to this payee | "You've paid this account before." | 0 |
| **No history** | < 0.15 | "Nothing unusual about this account." | 0 |
| **Watch** | 0.15 – 0.40 | "This account is new to the network." | 1 |
| **Suspicious** | 0.40 – 0.70 | "This account is behaving like a collection point." | 2–3 |
| **High risk** | ≥ 0.70 | "Money sent here usually leaves within minutes." | 3–4 |

Copy rules for these headlines:
- One sentence. Present tense. No hedging verbs ("may", "could", "possibly").
- Describes **observed behaviour**, never a legal accusation. We never print "fraud",
  "mule", "criminal" or "scam" on the payer surface. The bank console may use those
  words internally; the payer surface may not. This is a liability decision as much as
  a UX one, and it is worth saying out loud to the panel.

---

## 5. Personas and what each one gets from one decision

| Party | Needs | PRIMA gives | Rendering |
|---|---|---|---|
| Payer | To understand in 3 seconds | Verdict + 3 checkable facts + a counterfactual | `ReasonLine.user()` |
| Bank risk ops | An action they can justify | Fused score, per-scorer contribution bars, fired rules, tier, suggested action | `ReasonLine.bank()` |
| Regulator / auditor | What was known at that moment | Signed, immutable JSON: score, rules, config version, model hashes, timestamp | `ReasonLine.regulator()` |
| Innocent counterparty | Proportionate treatment and a route out | ScopedHold with a reference number, remaining balance live, contest link | ScopedHold record |
| Trusted contact | A reason to pick up the phone | One named alert with the amount and payee age | CircuitBreaker payload |

All five read from **the same `RiskDecision` row**. Never recompute per surface — the
audit trail depends on there being exactly one decision.

---

## 6. In scope / out of scope

### In scope (P0 — must run live)
- Ledger of accounts, balances, transactions (synthetic, no real rails)
- Non-payment event stream (`events` table) and its ingestion
- RingWatch (rules + GNN inference), TrailScore, ContextFlag, fusion
- Interrupt Ladder tiers 0–4
- ReasonLine three renderings
- Payer surface with verdict card and comprehension probe
- Bank console with live graph, live decision log, investigation drawer
- ScopedHold
- CircuitBreaker to a second device
- Operator console with manual override for every act
- `GET /api/metrics/ps3`

### P1 — build only if P0 is done and rehearsed
- PatternMemory similarity ("89% match to a shape we've seen")
- AdaptCal live threshold tuning chart
- Mesh — three toy banks, federated hashed signal view
- 3D graph toggle

### P2 — roadmap slide only, do not write code
- Telecom / SIM-swap cross-institution signal
- Real NLP context understanding beyond lexicon + pattern matching
- Invoice discounting, marketplace order, and trading surfaces named in the PS
- Loan-app permission abuse (explicitly out of scope: it is a consent problem, not a
  payment-moment problem — say this on the scoping slide, judges respect a drawn line)

---

## 7. Non-goals, stated deliberately

1. We do not claim to replace NPCI's transaction-routing scoring or RBI's DPIP. We are a
   layer that consumes similar signals and acts at a different moment.
2. We do not claim ContextFlag is NLP. It is a lexicon plus pattern matching over payment
   notes and a scripted call feed. Calling it NLP would be the thing that loses credibility
   under questioning.
3. We do not claim the GNN is trained on real fraud. It is trained on our synthetic
   generator's labelled attacks. Say so when asked; it is a design demonstration, not a
   deployed model.
4. We do not process real money. See `CLAUDE.md` §3.
