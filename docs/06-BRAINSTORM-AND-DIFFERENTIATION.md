# 06 — Brainstorm and Differentiation

## 1. What "ordinary" looks like, so you can avoid it

The base idea — a GNN that scores beneficiaries, a notification before you pay, a bank
dashboard with a live graph and a log panel — is a good product. It is also, on its own,
**the shape every strong team will arrive at.** A graph with coloured nodes and a
scrolling risk log is the default image of "fraud detection." If two teams show that
side by side, the panel remembers neither.

Here is the honest audit of the base idea:

| Base feature | Verdict | Why |
|---|---|---|
| GNN scoring accounts | Necessary, not distinctive | Everyone will have a model. The GNN earns its place for exactly one reason: it is **inductive**, so it scores a six-day-old account that no registry has. Lead with that property, not with the acronym. |
| "Beneficiary is suspicious" notification | Distinctive **only if the copy is specific** | "This account is suspicious" is a popup people tap through. "Opened 6 days ago, 14 people paid it today, you never have" is a warning people stop for. The category is table stakes; the three checkable facts are the product. |
| Live graph console | Necessary, not distinctive | It is how you explain the system on stage. It is not why you win. |
| Live log side panel | Necessary, not distinctive | Same. |
| Flag the network as mule | **Actively risky** | The PS says the cost of response lands on innocent parties. A button that flags a whole network is the freeze-first-sort-later behaviour the brief criticises. Reframe: the console proposes, ScopedHold disposes, and it disposes on an amount. |

So: build all of the above, and then win on the five things below.

---

## 2. The five that actually differentiate

### 2.1 The quadrant nobody else will name
Two independent risk axes — **beneficiary history** and **sender current state** — and
the argument that the interesting cell is *high sender risk, low beneficiary risk*.

That is a fresh mule account paying-side, plus a person mid-takeover or mid-call.
A negative registry has structurally zero coverage there. A beneficiary-only score has
zero coverage there. It is a five-line `cross_term` rule in `fusion.py` and a 40-line
component in the console, and it is the entire architectural argument made visible.

If you build only one thing from this document, build this.

### 2.2 The counterfactual line
> *"This would not have been flagged if you had paid this account before."*

Computed by dropping each fired rule, re-scoring, and reporting the one whose removal
lowers the tier. Cheap. And it is the most direct possible answer to the PS's
*user comprehension of warnings* metric — a warning that explains its own boundary is
one a person can reason about instead of dismissing.

Nobody in that room will have a counterfactual on a fraud warning.

### 2.3 The comprehension probe as a measured number
The PS lists "user comprehension of warnings" as a success metric. Everyone will read
that sentence. Almost nobody will *instrument* it.

Three options, one tap, right there in the tier-2 flow. It costs a legitimate user two
seconds and it produces the one number on your final slide that is about a human being
rather than a model. When you say "86% comprehension" and the next team says "0.94
F1", you have answered a different and better question.

### 2.4 CircuitBreaker — attacking the mechanism, not the symptom
Digital arrest, fake investment, task scams, romance long-cons and boss impersonation are
**one mechanism in five costumes**: isolate the target, apply urgency, pre-script them to
ignore warnings.

You cannot out-warn a pre-scripted victim. So don't. Break the isolation instead. One
countermeasure answers five fraud families, and that consolidation — *"we don't have
eleven detectors, we have one architecture that generalises"* — is what separates a
system design from a checklist.

### 2.5 The absence of a freeze function
There is no code path in PRIMA that freezes an account. Not disabled, not gated —
absent. ScopedHold takes an amount and a transaction id, and there is no overload that
takes an account id.

Saying *"we deliberately did not write that function"* is a stronger claim than any
feature, because it is a claim about judgement.

---

## 3. Ideas worth stealing into the build (cheap, high payoff)

**Beneficiary Passport.** Freeze the verdict into a shareable, hash-verified snapshot:
*"as of 15:41:02, this account was 6 days old, had 14 unique senders today, retention
0.04."* The payer can screenshot it. The bank logs it. If a dispute arises in six months,
what was known at the moment is reconstructible. Two hours of work; it turns a warning
into evidence.

**Lead-time meter, made physical.** Don't report lead time as a table cell. Put a small
counter on the payer screen during the quote: *"checked 0.3 s before you pay."* The PS
asks for detection lead time ahead of commitment — show it at the moment it happens, not
just in aggregate.

**The silent-majority counter.** A live figure on the console: *"98.1% of payments today
passed with no friction."* Fraud demos always show the catches. Showing the non-catches
is what convinces a bank that this is deployable, and it is the same denominator as the
false-challenge rate you already compute.

**Reason stability across audiences.** The user sentence, the bank bars and the regulator
JSON all carry the same `rules_fired` array and the same payload hash. Demonstrate on
stage that the three renderings are provably the same decision. That is the auditability
clause of the PS, answered literally.

**Dormant fan-in as a pre-mule signal.** An account with near-zero history that starts
receiving small credits before any outflow is a mule *being recruited*, not yet a mule
operating. Scoring the precursor rather than the act is exactly the "before commitment"
posture the brief is asking for, applied one layer earlier.

**Direction mismatch check.** For collect-type requests, the highest-value warning in
Indian UPI fraud is one factual sentence: *"This sends ₹500 from your account. It does
not receive it."* It is not machine learning; it is the literal fact the person is about
to get wrong, shown at the moment they'd get it wrong. Cheap, and it belongs on the
roadmap slide even if you don't build the collect flow.

**Trusted-contact reciprocity.** Two accounts nominate each other. This makes the
CircuitBreaker demo self-contained with two judges and no extra setup, and it makes a
better product story than a one-way guardian relationship, which reads paternalistic.

---

## 4. Ideas to explicitly reject, and say why

| Idea | Reject because |
|---|---|
| Real payment gateway / sandbox | Already decided. Zero real rupees either way, and it implies otherwise. |
| A "block" button on the console | Contradicts the brief's central constraint. Its absence is the argument. |
| Network-wide "flag as mule" action | Freeze-first-sort-later. This is the failure the brief names. |
| Real NLP / an LLM for ContextFlag | You cannot defend latency, cost or determinism in 24 hours. A lexicon you can explain beats a model you can't. Put it on the roadmap. |
| Voice-call analysis | Enormous privacy surface, no time, and the panel will ask about consent. |
| Blockchain for the audit record | A signed append-only table plus a hash chain gives you the same property with none of the questions. |
| Training on "real fraud data" claims | You don't have any. Say so. |
| A mobile app | Web on a scanned QR is faster to demo and installs nothing. |

---

## 5. Three sentences to have memorised

> **On the moment:** "Every other system tells you what happened. We are the only thing
> in the stack that speaks in the four seconds while the outcome can still change."

> **On the response:** "There is no function in our codebase that freezes an account.
> We hold ₹8,000 of ₹1,40,000 and give you a reference number, because the alternative
> is the thing courts are currently striking down."

> **On the last tier:** "The top tier isn't a louder warning. It's a second person.
> Every one of these scams needs the victim alone — so we stop trying to out-argue the
> scammer and just end the isolation."

---

## 6. What to cut first when you run out of time

In this order, without debate:

1. 3D graph toggle
2. Mesh (three-bank federated view)
3. AdaptCal live tuning chart
4. PatternMemory similarity
5. The quadrant panel *visualisation* — but **keep the `cross_term` rule in fusion.py**,
   because the argument survives without the chart and the score does not survive
   without the rule

Never cut: the three facts, the counterfactual, the comprehension probe, ScopedHold,
CircuitBreaker. Those five are the reason this isn't ordinary.
