# 07 — Team Workflow (4 people, shared repo, Cursor)

Supersedes the 5-person role table in `docs/05` §5–§6. Everything else in `05` (acts,
fallbacks, prompt sequence in §7) still applies — the prompts in §7 are just now shared
across 3 people instead of run by one owner each.

---

## 1. Roles

| Person | Owns | Codes in Cursor? |
|---|---|---|
| **F — Frontend** | `web/` entirely: payer, console, watch, ops surfaces | Yes, solo on `web/`, never touches `backend/` |
| **K — You** | `core/` (schema, config, seed), `graph/` + `scoring/ringwatch.py`, integration/merges, demo rehearsal | Yes |
| **P2** | `scoring/trailscore.py`, `scoring/contextflag.py`, `context/lexicon.py`, `scoring/fusion.py`, `scoring/ladder.py` | Yes |
| **P3** | `action/reasonline.py`, `action/scoped_hold.py`, `action/circuit_breaker.py`, `routes/ws.py`, `routes/payer.py`, `routes/console.py`, `routes/ops.py` | Yes |

Three coders, one repo, `backend/` split by directory so file-level conflicts are rare
by construction — nobody but you touches `core/`, nobody but P2 touches `scoring/`,
nobody but P3 touches `action/` and `routes/`. F never opens `backend/` at all.

**Why you own integration.** You've read the whole spec end to end and the existing
repo; you're the one who can tell whether a merge conflict is real disagreement or just
two people touching the same file. Budget roughly a quarter of your hours for
integration and rehearsal, not new code — say this out loud to the team now, not at
hour 20 when it's a surprise.

---

## 2. Git — trunk-based, short-lived branches

Do not use long-lived feature branches or a full PR-review-and-approve cycle. There
isn't time, and the review step below replaces it.

```
main                        ← always runnable: uvicorn starts, web/ builds
 ├─ core/schema              (K)
 ├─ scoring/ringwatch        (K)
 ├─ scoring/sequence-context (P2)
 ├─ action/response          (P3)
 ├─ web/payer                (F)
 └─ web/console               (F)
```

Rules:
1. **Branch per module, not per person.** If P2 finishes `trailscore.py` and starts
   `contextflag.py`, that's a new branch, not a continuation of the old one. Small,
   mergeable units.
2. **Merge to `main` at least every 2 hours**, even if the module isn't finished —
   behind a flag or a stub return if needed. A branch alive for 4+ hours is the single
   biggest cause of a bad merge at hour 20.
3. **Pull `main` before you start each new branch.** Not optional. Conflicts are cheap
   at branch-start and expensive at merge-end.
4. `prima_config.yaml` and `backend/core/models.py` are **shared files everyone reads
   but only K writes**. If P2 or P3 needs a new config key or a schema change, they say
   so in the shared channel (§4) and K adds it — this avoids three people editing the
   same YAML block in parallel.
5. No merge to `main` without running `pip install -r requirements.txt && uvicorn
   backend.api:app` (backend) or `npm run build` (frontend) locally first. A red `main`
   blocks everyone, not just you.

---

## 3. Cursor — one shared way of prompting and reviewing

All 3 backend coders use the **same prompt sequence** from `docs/05` §7, scoped to their
own module. This matters more than it sounds: if everyone prompts Cursor differently,
you get three different code styles that don't merge cleanly and can't be reviewed fast.

### 3.1 Before prompting, every session starts the same way
Paste `CLAUDE.md` in full, then the one spec section relevant to the task (`docs/02` for
scoring, `docs/03` for API/schema, `docs/04` for UI). Never paste the whole `docs/`
folder — Cursor's context window is better spent on the actual code files it's editing
plus the one spec section.

### 3.2 One prompt = one phase, exactly as scoped in `docs/05` §7
Don't ask Cursor to "also start on the next thing" in the same prompt. A prompt that
does two phases produces code that's harder for someone else to review, because the diff
mixes two concerns.

### 3.3 Review before merge — a 3-point check, not a full read
Because there's no time for a real PR review, each person checks their own Cursor output
against these three things before merging to `main`:

1. **Does it match the acceptance check** in `docs/05` §7 for that prompt? Run it.
2. **Does it violate any hard constraint in `CLAUDE.md` §3?** Grep for the obvious ones:
   `freeze`, the ContextFlag lexicon words, anything that touches a payment gateway.
3. **Did Cursor invent a field, endpoint, or table not in `docs/03`?** Cursor will
   sometimes add a convenience field or rename something slightly. If it drifts from the
   contract, either fix it or flag it in the shared channel before merging — a payer
   endpoint that doesn't match what `web/` expects is a bug nobody will catch until
   integration.

### 3.4 Cross-review, once, at the phase-3/phase-6 checkpoints
At two points — after fusion/ladder lands (`docs/05` phase 3) and after the console
surface lands (phase 6) — stop and have someone who didn't write it read it for ten
minutes. Not a full review, just: does the code match what the other two people's
modules expect to call? This is where "P2's `contextflag_score` is 0–1 but P3's
`fusion.py` expected 0–100" gets caught before it costs an hour at hour 18.

### 3.5 Keep a running log, not a chat scrollback
One shared doc (or a `NOTES.md` in the repo, gitignored from the demo build but kept
locally) with one line per merge: `[K] core/schema merged, all 11 tables, config
loader done`. When someone joins a Cursor session two hours into a phase, they read the
last five lines instead of asking "where are we."

---

## 4. Communication — one channel, three cadences

- **Immediate:** anyone blocked on a shared file (`models.py`, `prima_config.yaml`) or a
  contract mismatch (§3.4) says so the moment they notice it, not at the next sync.
- **Every 2 hours:** a 2-minute check-in against the `docs/05` §6 hour table — on track,
  behind, or need to cut. Decide cuts as a group using `docs/06` §6's priority order, not
  ad hoc.
- **At hour 4 (hard checkpoint, from `docs/05` §6):** confirm CircuitBreaker has buzzed a
  second device. If not, P3 drops everything else onto it and the group cuts P1 scope
  immediately rather than discovering the problem at hour 20.

---

## 5. Revised hour-by-hour for 4 people

The original `docs/05` §6 table assumed 5 people with a dedicated CircuitBreaker/Mesh/
AdaptCal owner. With P3 now owning both the action layer and the routes, P1 items shrink
accordingly — this table replaces `docs/05` §6.

| Hours | F (frontend) | K (you) | P2 | P3 |
|---|---|---|---|---|
| 0–1 | Scaffold `web/` (Vite+React+TS), tokens.css from `docs/04` §2 | Repo migration: `docs/`, `requirements.txt`, `legacy/`, confirm CPU-only startup | Read `docs/02` §2, sketch `trailscore.py` signature against fixture events | **CircuitBreaker in isolation, two devices, before anything else** |
| 1–4 | Payer surface static states (all 5 tiers) from fixture JSON, `docs/04` §3 | Schema + config + seed generator, 500 accounts | `trailscore.py` + `contextflag.py` skeleton + lexicon stub | Finish CircuitBreaker WS path; start `scoped_hold.py` |
| 4–8 | Wire payer surface to `POST /api/payer/quote` (mocked response first, then real) | PathGraph + RingWatch rules ported, GNN wired at `cpu` | Fusion + ladder; lexicon filled with real phrases (never in docs) | `reasonline.py` user() + bank(); `routes/payer.py` |
| 8–12 | Console shell: graph render, decision rail, metric strip skeleton | **Checkpoint (§3.4):** cross-review fusion/ladder output against `routes/payer.py` expectations | Comprehension probe generation logic | `reasonline.py` regulator(); ScopedHold wired to real balances |
| 12–16 | Full integration: console live from `/ws/console`, payer live end to end | Integration pass across all branches; fix contract drift | Support integration; start P1 quadrant panel data feed | `routes/console.py`, `routes/ops.py`, `/api/metrics/ps3` |
| 16–19 | Investigation drawer, quadrant panel visual, watch surface | **Checkpoint:** cross-review console against console spec `docs/04` §4 | Quadrant panel backend support; PatternMemory if ahead | Ops console: guest provisioning + QR, act buttons, health check |
| 19–21 | Polish, dark mode check, responsive check, reduced-motion check | P1 items from `docs/06` §6 priority order if green, else harden P0 | Same | Same |
| 21–23 | — | **Rehearse all six acts three times, act 3 six times, with the whole team** | | |
| 23–24 | Buffer. No new code. | | | |

---

## 6. What changes vs the 5-person plan

- Mesh (three-bank federated view) and AdaptCal move fully into "only if hour 19 is
  green" — with one fewer person there is less slack, and `docs/06` §6 already ranks
  them as the first two cuts.
- PatternMemory stays P1 but is now P2's stretch item, not a dedicated owner's core work.
- The 3D graph toggle is F's stretch item at hour 19, not before.
- Nothing in `docs/01`–`docs/06` P0 scope changes. The cut list in `docs/06` §6 is what
  absorbs the smaller team, not the acceptance checks in `docs/05` §7–§8.
