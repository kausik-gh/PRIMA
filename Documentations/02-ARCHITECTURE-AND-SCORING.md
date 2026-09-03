# 02 — Architecture and Scoring

## 1. Request flow — the only path that matters

```
        PAYER (phone, /pay)
             │  1. POST /api/payer/quote  { from, to_handle, amount }
             ▼
    ┌─────────────────────────────────────────────────────────┐
    │  DecisionService.evaluate(sender, beneficiary, amount)   │
    │                                                          │
    │   ┌──────────┐  ┌───────────┐  ┌─────────────┐          │
    │   │RingWatch │  │TrailScore │  │ ContextFlag │          │
    │   │ network  │  │ sequence  │  │  context    │          │
    │   │ 0..1     │  │  0..1     │  │   0..1      │          │
    │   └────┬─────┘  └─────┬─────┘  └──────┬──────┘          │
    │        └──────────────┼───────────────┘                 │
    │                       ▼                                  │
    │                  fusion.fuse()  → fused 0..1             │
    │                       ▼                                  │
    │                  ladder.tier()  → 0..4                   │
    │                       ▼                                  │
    │                  ReasonLine     → user / bank / reg      │
    │                       ▼                                  │
    │            persist RiskDecision  (immutable)             │
    └───────────────────────┬─────────────────────────────────┘
                            │
        ┌───────────────────┼────────────────────┬──────────────┐
        ▼                   ▼                    ▼              ▼
   payer verdict     WS → console log     tier≥3 ScopedHold  tier 4
   card + facts      + graph node paint   on the amount      CircuitBreaker
                                                              → /watch WS
```

Two calls, always in this order:

1. `POST /api/payer/quote` — scores and returns the verdict. **Nothing moves.** This is
   the pre-commitment moment. `decision_id` is returned.
2. `POST /api/payer/commit` — takes `decision_id`, applies the ladder outcome, and either
   settles into the ledger, opens a challenge, or opens a ScopedHold.

The gap between those two calls is the **detection lead time** we report. Record
`quote_at` and `commit_at` on the decision row.

---

## 2. Module responsibilities

### `graph/pathgraph.py` — one graph, two edge types
Extends the existing `build_transaction_graph`.

- **Money edges**: from `transactions`. Attributes `amount`, `channel`, `ts`, `taint`.
- **Event edges**: from `events`, connecting an account to a device / payee / session
  node. This is what lets TrailScore and RingWatch read the same structure.

Node types: `account`, `device`, `payee_handle`. Edge types: `money`, `used_device`,
`added_payee`.

Rebuild incrementally, not from scratch, on every transaction. Keep a `networkx.DiGraph`
in memory, persist the source rows.

### `scoring/ringwatch.py` — the network score
Direct port of the existing rule table plus a GNN term.

```python
RULES = {                      # from the mule detection.py table, unchanged
  "fan_in":       ("in_degree >= 2",                       2),
  "fan_out":      ("out_degree >= 2",                      2),
  "pass_through": ("retention_ratio < 0.2 and has_inflow", 2),
  "shared_device":("device_cluster_size > 2",              3),
  "channel_burst":("unique_channels > 2",                  2),
  "high_velocity":("transaction_count >= 3",               1),
  "dormant_wake": ("gap_days > 30 and amount > 2*baseline",2),
  "fresh_fan_in": ("account_age_days < 7 and in_degree>=3",3),   # NEW — the mule signature
}
```

`fresh_fan_in` is new and it is the single most important rule in the system. It is the
rule a negative registry structurally cannot have.

**Fusion inside RingWatch:**

```
rule_score  = min(sum(points_fired) / 12.0, 1.0)
gnn_score   = gnn_predict(G, features_df)  →  0..1   (FraudGAT, cpu)
taint_gate  = 1.0 if taint_ratio >= 0.15 else 0.35   (caps unproven inflow)

ringwatch = clamp( (0.55 * rule_score + 0.45 * gnn_score) * taint_gate , 0, 1 )
```

The GNN is **inductive** — it scores a node from its features and neighbourhood, not
from an identity it has seen in training. That is why it produces a non-zero score on an
account created six days ago. Make this point when a judge asks how you beat a blocklist.

If `gnn_model.pth` is missing, `gnn_predict` already degrades to zeros gracefully. Keep
that behaviour, and surface it in the console as a "GNN offline" chip rather than
failing silently.

### `scoring/trailscore.py` — the sequence score (NEW)

For the **sender**, look at `events` in the last `window_minutes` (default 15).

```yaml
trailscore_chain:
  login_new_device:    0.20
  credential_changed:  0.22
  payee_added:         0.15
  limit_raised:        0.20
  full_balance_amount: 0.20        # derived at scoring time, not an event
  screen_share_active: 0.25        # remote-access app in foreground
  window_minutes:      15
  ordered_bonus:       0.25        # if ≥4 steps appear in canonical order
  unordered_bonus:     0.10        # if ≥4 steps appear in any order
```

```
raw   = Σ weights of steps present in window
bonus = ordered_bonus if canonical order else unordered_bonus if ≥4 steps else 0
trailscore = min(raw + bonus, 1.0)
```

Canonical order: `login_new_device → credential_changed → payee_added → limit_raised →
transfer_attempted`. **The chain is worth more than the sum of its steps** — that is the
whole thesis of the PS, expressed as one line of arithmetic. Put that line on a slide.

### `scoring/contextflag.py` — the context score (NEW)

Reads (a) the payment note field, (b) in demo, a scripted call-context text injected by
the operator console.

Categories and weights — **the trigger phrases themselves live only in
`backend/context/lexicon.py` and appear in no document and on no screen**:

| Category | Weight | What it captures |
|---|---|---|
| `urgency` | 0.25 | time pressure |
| `secrecy` | 0.30 | isolation from other people |
| `fear` | 0.30 | authority / consequence framing |
| `greed` | 0.15 | return / reward framing |
| `bypass_approval` | 0.30 | routing around a normal check |

```
contextflag = min(Σ weights of matched categories, 1.0)
```

Implementation: normalised token matching + a small set of regex patterns. Multi-lingual
handling is out of scope; note it as a limitation rather than faking it.

**`secrecy` is the highest-value signal in the system** and the reason CircuitBreaker
exists. Isolation is the shared mechanism behind digital-arrest, investment, task,
romance and boss-impersonation scams. One signature, one countermeasure, five fraud
types. That consolidation is the argument that separates a system design from a
checklist.

### `scoring/fusion.py`

```yaml
fusion:
  ringwatch_weight:  0.40
  trailscore_weight: 0.35
  contextflag_weight: 0.25

  cross_term:                      # the quadrant that registries miss
    enabled: true
    condition: "trailscore >= 0.45 and ringwatch < 0.30"
    bonus: 0.15
    reason_code: "SENDER_STATE_ANOMALOUS_FRESH_PAYEE"
```

```
base  = 0.40*ringwatch + 0.35*trailscore + 0.25*contextflag
fused = min(base + cross_term_bonus, 1.0)
```

The `cross_term` encodes §2 of `docs/01`: sender in a compromised state paying a payee
with no bad history. Without it, a fresh mule plus a hijacked sender averages down to a
mid score and passes. With it, it clears tier 3. This is a five-line rule that makes the
architecture argument concrete — do not drop it under time pressure.

### `scoring/ladder.py` — the Interrupt Ladder

```yaml
ladder:
  - {tier: 0, max: 0.15, action: pass_silent}
  - {tier: 1, max: 0.40, action: inline_reason}
  - {tier: 2, max: 0.60, action: purpose_challenge}
  - {tier: 3, max: 0.80, action: scoped_hold_cooling}
  - {tier: 4, max: 1.01, action: scoped_hold_plus_circuit_breaker}
```

| Tier | What the payer experiences | What the bank sees | Reversible by user? |
|---|---|---|---|
| 0 | Nothing. Payment goes through. | Log entry only | n/a |
| 1 | The verdict card shows three facts inline. Confirm button unchanged. | Log entry, node tinted | n/a |
| 2 | Must type the purpose of the payment in their own words, plus a one-tap comprehension probe. | Challenge recorded with the typed text | Yes, on answer |
| 3 | ₹1 sends now. The remainder is held for 30 minutes with a visible countdown and a Cancel button. | ScopedHold row, hold amount only | Yes, cancel or wait out |
| 4 | Everything in tier 3, plus a named trusted contact is alerted immediately. | CircuitBreaker log row + ack status | Yes, contact can ack-approve |

Tier 3's split send is the concrete answer to "blocking is not an acceptable default":
the payment is not refused, it is **paced**. The recipient gets something immediately,
the payer keeps control, and the scam's time pressure is broken.

### `action/reasonline.py` — one decision, three renderings

```python
def user(decision) -> UserReason:
    """
    Exactly three facts, each independently checkable by the payer against
    their own knowledge. Ranked by contribution. Plus one counterfactual.
    Never uses: fraud, mule, criminal, scam, illegal.
    """
```

Fact templates (fill from real values, never generic):
- `"This account was opened {n} days ago."`
- `"{n} different people have sent it money today."`
- `"You have never paid this account before."`
- `"Money that arrives here usually leaves within {n} minutes."`
- `"Your transfer limit was raised {n} minutes ago."`
- `"A new device signed in to your account {n} minutes ago."`

**Counterfactual line** — the differentiator, one sentence:
`"This would not have been flagged if you had paid this account before."`
Judges have not seen a counterfactual on a fraud warning. It is cheap to compute (drop
each fired rule, re-score, report the single rule whose removal drops the tier) and it is
the most direct possible answer to "user comprehension of warnings."

```python
def bank(decision) -> BankReason:
    """ Per-scorer contribution bars + every fired rule with its points,
        reusing the SHAP category-bar visual language from the mule build. """

def regulator(decision) -> dict:
    """ Immutable signed record. Written once, never updated.
        { decision_id, fused, sub_scores, rules_fired[], config_version,
          model_sha256{rf, gnn}, quote_at, commit_at, sha256_of_payload } """
```

The regulator record answers the PS's "opaque scores cannot be acted upon" clause
directly, and it is the thing nobody else in the room will build.

### `action/scoped_hold.py`

```
hold(transaction_id, amount_paise, reason_ref)
  → debit nothing from the account balance
  → mark amount_paise as held on that transaction
  → account.available_balance = balance - Σ(active holds)
  → the rest of the account stays fully operational
```

Hard rule, in a comment at the top of the file:
```python
# Inbound money is NEVER held. Only outbound. A hold is scoped to an amount on a
# transaction, never to an account. Freezing an account is not an available operation
# in this system — there is deliberately no function that does it.
```

That last sentence is worth saying on stage: the capability to freeze an account does not
exist in the codebase.

### `action/circuit_breaker.py`

Fires only at tier 4, only if `trusted_contacts` has a row for the account.

```json
{
  "type": "circuit_breaker",
  "account_holder": "Ramesh K.",
  "amount": "₹4,00,000",
  "payee_age_days": 6,
  "headline": "Ramesh is about to send ₹4,00,000 to an account opened 6 days ago.",
  "facts": ["14 people sent money to this account today",
            "Ramesh has never paid it before",
            "His transfer limit was raised 8 minutes ago"],
  "actions": ["This is fine", "Something is wrong — hold it"]
}
```

Delivered over the `/ws/watch/{token}` channel. The trusted contact's response writes
`ack` and can extend or release the hold. **Build and test this path in isolation
first**, before it is integrated — it is the highest-risk live moment.

### `memory/pattern_memory.py` and `memory/adaptcal.py` (P1)
Near-direct ports. `extract_cluster_signature` gains `trail_shape` (the ordered event
chain) and `context_categories`. `compare_signature` keeps the `exp(-normalised_diff)`
similarity unchanged. AdaptCal tunes ladder thresholds against **false-challenge rate vs
catch rate**, not precision vs recall — the metric the PS actually asks for.

---

## 3. What is ported vs what is new — say this breakdown out loud

| Status | Modules |
|---|---|
| **New, and not found in any published system** | ContextFlag at commit-time, CircuitBreaker, TrailScore, the counterfactual reason line, the comprehension probe |
| **A design alternative, not a novelty claim** | Mesh (federated hashed signals vs a centralised registry) |
| **Engineering answer to a stated legal gap** | ScopedHold — amount-scoped rather than account-level |
| **Ported from the prior mule build** | RingWatch rules, TaintTrace, FraudGAT, PatternMemory, AdaptCal, the attack generators |

Claiming all of it is original is the fastest way to lose a panel. Claiming this split is
the fastest way to look like you have shipped something before.

---

## 4. Performance targets

| Path | Target | How |
|---|---|---|
| `POST /api/payer/quote` p95 | < 400 ms | Incremental graph, cached node features, GNN on a 2-hop subgraph only |
| WS event → console render | < 250 ms | Typed diff events, no full snapshots |
| Graph render | 60 fps at 500 nodes | `react-force-graph-2d` with `cooldownTicks` capped; freeze layout after settle |
| CircuitBreaker fire → second device buzz | < 2 s | Direct WS push, no polling |

At 500 accounts and a 500-transaction window these are comfortable. Do not optimise
further; spend the time on rehearsal.
