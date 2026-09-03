# 03 — Data Model and API Contract

Backend: FastAPI + SQLModel + SQLite (`prima.db`). Every table below is a SQLModel class
in `backend/core/models.py`. IDs are UUID strings. Money is **integer paise**, never float.

---

## 1. Schema

```sql
-- ─── Ledger ──────────────────────────────────────────────────────────────

create table accounts (
  id                 text primary key,
  handle             text unique not null,       -- 'ramesh@prima', the UPI-like handle
  display_name       text not null,
  bank_code          text not null default 'BANKA',   -- BANKA|BANKB|BANKC for Mesh
  device_id          text not null,
  created_at         timestamp not null,
  balance_paise      integer not null default 0,
  is_demo_guest      boolean not null default 0,      -- judge-provisioned accounts
  ground_truth_role  text                             -- 'legit'|'mule'|'victim'|null
                                                      -- SEEDED DATA ONLY, never shown in
                                                      -- product surfaces, used for metrics
);
create index ix_accounts_handle on accounts(handle);

create table transactions (
  id              text primary key,
  sender_id       text not null references accounts(id),
  receiver_id     text not null references accounts(id),
  amount_paise    integer not null,
  channel         text not null,                 -- 'upi'|'imps'|'neft'|'card'
  note            text,                          -- ContextFlag reads this
  status          text not null,                 -- 'quoted'|'settled'|'held'|'cancelled'|'challenged'
                                                 -- tier 3/4 commit -> held; contact approved or cooling
                                                 -- timeout -> settled; payer cancel -> cancelled
  attempted_at    timestamp not null,
  settled_at      timestamp,
  taint_ratio     real not null default 0.0,
  is_seeded_attack boolean not null default 0
);
create index ix_tx_sender on transactions(sender_id, attempted_at);
create index ix_tx_receiver on transactions(receiver_id, attempted_at);

-- ─── Sequence: the raw material for TrailScore ──────────────────────────

create table events (
  id            text primary key,
  account_id    text not null references accounts(id),
  event_type    text not null,
  -- login_new_device | credential_changed | payee_added | limit_raised
  -- | screen_share_active | note_entered | call_context | transfer_attempted
  payload       json,        -- {device_id, payee_handle, old_limit, new_limit, text}
  ts            timestamp not null,
  ingest_source text not null default 'manual'   -- 'live'|'seed'|'operator'
);
create index ix_events_acct_ts on events(account_id, ts);

-- ─── Decisions: the immutable core ──────────────────────────────────────

create table risk_decisions (
  id                text primary key,
  transaction_id    text references transactions(id),
  sender_id         text not null,
  beneficiary_id    text not null,
  amount_paise      integer not null,

  ringwatch_score   real not null,
  trailscore_score  real not null,
  contextflag_score real not null,
  cross_term_bonus  real not null default 0.0,
  fused_score       real not null,
  tier              integer not null,            -- 0..4
  verdict           text not null,               -- known|no_history|watch|suspicious|high_risk

  rules_fired       json not null,               -- [{code, points, detail}]
  user_reason       json not null,               -- {headline, facts[3], counterfactual}
  bank_reason       json not null,               -- {contributions{}, rules[]}
  regulator_record  json not null,               -- signed, see below
  payload_sha256    text not null,

  config_version    text not null,
  quote_at          timestamp not null,
  commit_at         timestamp,                   -- null until committed
  lead_time_ms      integer                      -- commit_at - quote_at
);
-- risk_decisions is APPEND ONLY. No UPDATE except setting commit_at/lead_time_ms once.

-- ─── Context ────────────────────────────────────────────────────────────

create table context_flags (
  id             text primary key,
  decision_id    text references risk_decisions(id),
  event_id       text references events(id),
  category       text not null,     -- urgency|secrecy|fear|greed|bypass_approval
  weight         real not null,
  matched_span   text               -- stored for the ops view only, never returned to /pay
);

-- ─── Response ───────────────────────────────────────────────────────────

create table scoped_holds (
  id               text primary key,
  transaction_id   text not null references transactions(id),
  account_id       text not null references accounts(id),
  held_paise       integer not null,
  reason_ref       text not null,       -- 'PRIMA-2026-000418', shown to the payee
  opened_at        timestamp not null,
  releases_at      timestamp,           -- cooling window end
  released_at      timestamp,
  outcome          text                 -- 'released'|'cancelled_by_user'|'escalated'
                                        -- released = remainder settled (approve or timeout)
                                        -- cancelled_by_user = payer cancel, no remainder debit
                                        -- null while still held (including contact extend)
                                        -- escalated = bank/ops only, not contact "hold it"
);

create table trusted_contacts (
  id              text primary key,
  account_id      text not null references accounts(id),
  contact_name    text not null,
  watch_token     text unique not null,    -- the /watch/{token} URL segment
  nominated_at    timestamp not null
);

create table circuit_breaker_log (
  id              text primary key,
  decision_id     text not null references risk_decisions(id),
  contact_id      text not null references trusted_contacts(id),
  fired_at        timestamp not null,
  payload         json not null,
  ack             boolean not null default 0,
  ack_action      text,                     -- 'approved'|'hold'
  ack_at          timestamp
);

-- ─── Comprehension: the PS metric nobody else will measure ──────────────

create table comprehension_probes (
  id            text primary key,
  decision_id   text not null references risk_decisions(id),
  question      text not null,
  options       json not null,       -- 3 strings
  correct_index integer not null,
  chosen_index  integer,
  shown_at      timestamp not null,
  answered_at   timestamp
);

-- ─── P1 ─────────────────────────────────────────────────────────────────

create table pattern_signatures (
  id           text primary key,
  label        text,                 -- 'fan_in_ring'|'sequence_takeover'|'isolation_pressure'
  signature    json not null,        -- node_count, avg_in/out_degree, avg_retention,
                                     -- density, trail_shape[], context_categories[]
  created_at   timestamp not null
);

create table bank_mesh_signals (
  id                 text primary key,
  hashed_account_ref text not null,        -- sha256(handle + salt), safe to share
  origin_bank        text not null,
  risk_score         real not null,
  reason_codes       json not null,
  shared_at          timestamp not null
);
```

**Ground truth handling.** `ground_truth_role` and `is_seeded_attack` exist only so
`/api/metrics/ps3` can compute prevented loss and false-challenge rate. They must never
be read by any scorer and never returned by `/api/payer/*`. Add an assertion test.

---

## 2. API contract

Base path `/api`. All responses JSON. Errors: `{ "error": {"code", "message"} }`.

### Payer surface

```http
POST /api/payer/quote
{ "sender_handle": "judge3@prima", "beneficiary_handle": "quickcash@prima",
  "amount_paise": 40000000, "note": "optional free text" }

200 {
  "decision_id": "d_9f2…",
  "verdict": "high_risk",
  "tier": 4,
  "headline": "Money sent here usually leaves within minutes.",
  "facts": [
    "This account was opened 6 days ago.",
    "14 different people have sent it money today.",
    "You have never paid this account before."
  ],
  "counterfactual": "This would not have been flagged if you had paid this account before.",
  "action": {
    "kind": "scoped_hold_plus_circuit_breaker",
    "immediate_paise": 100,
    "held_paise": 39999900,
    "cooling_minutes": 30,
    "trusted_contact_name": "Priya"
  },
  "probe": {
    "probe_id": "p_31a…",
    "question": "What did we tell you about this account?",
    "options": ["It was opened recently and many people are paying it",
                "Your bank is closed for maintenance",
                "The amount is above your daily limit"]
  },
  "lead_time_started_at": "2026-09-03T15:41:02.118Z"
}
```

`quote` **never moves money** and never mutates the ledger. It writes one
`risk_decisions` row and one `transactions` row with `status='quoted'`.

```http
POST /api/payer/commit
{ "decision_id": "d_9f2…", "purpose_text": "optional, required at tier 2" }
→ 200 { "outcome": "held" | "settled" | "challenged",
        "reason_ref": "PRIMA-2026-000418", "releases_at": "…" }

POST /api/payer/probe/{probe_id}     { "chosen_index": 0 }
→ 200 { "correct": true }

POST /api/payer/cancel               { "decision_id": "…" }
→ 200 { "outcome": "cancelled_by_user" }     # tier 3/4 escape hatch, always available

GET  /api/payer/account/{handle}
→ 200 { balance_paise, available_paise, active_holds:[{reason_ref, held_paise, releases_at}] }
```

CircuitBreaker ack on `/ws/watch/{token}` (`ack_action` `approved` | `hold`):

| Path | hold.outcome | transactions.status | Ledger |
|---|---|---|---|
| contact `approved` | `released` | `settled` | Debit sender `held_paise`, credit receiver, then clear the hold. Immediate ₹1 already moved at commit. |
| contact `hold` (extend) | stay `null` | stay `held` | No ledger change. Push `releases_at`. Emit `hold.extended` on `/ws/pay/{account_id}`. |
| payer cancel | `cancelled_by_user` | `cancelled` | Clear hold only. Do not debit the remainder. |
| cooling timeout | `released` | `settled` | Same money movement as `approved`. |

Isolation `release_hold` that only restores availability is the **cancel** path, not approve. Approve is not "un-hold and leave the remainder unsent."
Do not use `escalated` for contact "hold it".

### Console surface

```http
GET  /api/console/graph?window=500&bank=ALL
→ { nodes:[{id, handle, label, bank, tier, risk, age_days, is_held}],
    links:[{source, target, amount_paise, ts, taint, decision_id}] }

GET  /api/console/decisions?limit=100&since=…
→ { items:[{decision_id, ts, sender, receiver, amount_paise, tier, fused_score,
            top_rule, verdict}] }

GET  /api/console/investigate/{account_id}
→ { account, sub_scores:{ringwatch, trailscore, contextflag},
    contributions:[{scorer, weight, value, contribution}],
    rules_fired:[{code, points, detail}],
    event_timeline:[{ts, type, summary}],
    neighbours:[{id, handle, direction, amount_paise, ts}],
    pattern_match:{similarity, label} | null,
    available_actions:["open_scoped_hold","mark_reviewed","export_regulator_record"] }

GET  /api/console/decision/{id}/regulator
→ the signed immutable record (this is the download-as-JSON button)

GET  /api/metrics/ps3
→ { prevented_loss_paise, median_lead_time_ms, false_challenge_rate,
    comprehension_rate, multiparty_coverage,
    denominators:{legit_tx, probes_shown, seeded_structures} }
```

`/api/metrics/ps3` returns denominators alongside every rate. A rate without its
denominator is the kind of number a judge will ask about, and you want the answer on
screen already.

### Operator (demo control — not a product surface)

```http
POST /api/ops/seed                   { "accounts": 500, "days": 21 }
POST /api/ops/guest                  { "display_name": "Judge 3" }
   → { handle, account_id, pay_url, balance_paise }      # QR encodes pay_url
POST /api/ops/event                  { "account_id", "event_type", "payload" }
POST /api/ops/inject_sequence        { "account_id", "scenario": "takeover_isolation" }
POST /api/ops/context                { "account_id", "text": "scripted call transcript" }
POST /api/ops/attack                 { "pattern": "fan_in" | "ring" | "smurfing" | … }
POST /api/ops/nominate_contact       { "account_id", "contact_name" } → { watch_url }
POST /api/ops/reset
GET  /api/ops/health
   → { db_ok, rf_model_loaded, gnn_model_loaded, ws_clients, last_decision_at }
```

`/api/ops/health` is the pre-demo checklist in one call. Run it on stage before act one.

### WebSocket channels

```
/ws/console          → typed events, console only
/ws/watch/{token}    → circuit-breaker channel for one trusted contact
/ws/pay/{account_id} → payer hold updates: opened, extended, released
```

Event envelope, used on all three:

```json
{ "type": "decision.created" | "decision.committed" | "graph.node_updated"
        | "graph.link_added" | "hold.opened" | "hold.extended" | "hold.released"
        | "circuit_breaker.fired" | "circuit_breaker.acked" | "metrics.updated",
  "ts": "2026-09-03T15:41:02.118Z",
  "data": { … } }
```

**On connect only**, the server sends one `snapshot` event with the current graph and the
last 100 decisions. After that, diffs only. Never re-send the full state on a timer —
that is the defect being fixed from the inherited code.

---

## 3. Config file

Everything tunable lives in `prima_config.yaml`, loaded once at startup, hash recorded as
`config_version` on every decision.

```yaml
version: "1.0.0"

ledger:
  seed_accounts: 500
  seed_days: 21
  default_guest_balance_paise: 50000000     # ₹5,00,000 demo balance

fusion:
  ringwatch_weight: 0.40
  trailscore_weight: 0.35
  contextflag_weight: 0.25
  cross_term: { enabled: true, trail_min: 0.45, ring_max: 0.30, bonus: 0.15 }

ringwatch:
  rule_points: { fan_in: 2, fan_out: 2, pass_through: 2, shared_device: 3,
                 channel_burst: 2, high_velocity: 1, dormant_wake: 2, fresh_fan_in: 3 }
  rule_score_divisor: 12.0
  gnn_weight: 0.45
  taint_gate: { min_ratio: 0.15, below_gate_multiplier: 0.35 }

trailscore:
  window_minutes: 15
  weights: { login_new_device: 0.20, credential_changed: 0.22, payee_added: 0.15,
             limit_raised: 0.20, full_balance_amount: 0.20, screen_share_active: 0.25 }
  ordered_bonus: 0.25
  unordered_bonus: 0.10

contextflag:
  weights: { urgency: 0.25, secrecy: 0.30, fear: 0.30, greed: 0.15, bypass_approval: 0.30 }
  lexicon_module: "backend.context.lexicon"    # phrases live in code only

ladder:
  - { tier: 0, max: 0.15, action: pass_silent }
  - { tier: 1, max: 0.40, action: inline_reason }
  - { tier: 2, max: 0.60, action: purpose_challenge }
  - { tier: 3, max: 0.80, action: scoped_hold_cooling }
  - { tier: 4, max: 1.01, action: scoped_hold_plus_circuit_breaker }

scoped_hold:
  immediate_paise: 100                # the ₹1 that still sends
  cooling_minutes: 30
  reason_ref_prefix: "PRIMA-2026-"

adaptcal:
  enabled: false                      # P1
  step: 0.02
  target: "false_challenge_rate"
```
