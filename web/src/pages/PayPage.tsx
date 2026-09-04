import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { DemoChip } from "../components/Chrome";
import { Money } from "../components/Money";
import {
  ComprehensionProbe,
  HoldBanner,
  LadderAction,
  VerdictCard,
  payButtonLabel,
} from "../components/PayerBits";
import { api, ApiError } from "../lib/api";
import { formatPaise, remainingLabel, rupeesToPaise } from "../lib/format";
import { useTopicSocket } from "../lib/ws";
import type { AccountView, QuoteResponse } from "../types";

function contactCopy(quote: QuoteResponse, breaker?: string): string | null {
  if (quote.action.kind !== "scoped_hold_plus_circuit_breaker") {
    return null;
  }
  if (breaker === "no_trusted_contact") {
    return "No trusted contact is nominated for this account.";
  }
  const name = quote.action.trusted_contact_name;
  if (name) {
    return `We've let ${name} know. They can approve this or ask us to keep holding.`;
  }
  return "We've let your trusted contact know.";
}

export function PayPage() {
  const [params] = useSearchParams();
  const asParam = params.get("as");
  const [handleInput, setHandleInput] = useState(asParam || "");
  const handle = (asParam || handleInput).trim();
  const [account, setAccount] = useState<AccountView | null>(null);
  const [payee, setPayee] = useState("grocery@prima");
  const [rupees, setRupees] = useState("450");
  const [note, setNote] = useState("");
  const [purpose, setPurpose] = useState("");
  const [probeChoice, setProbeChoice] = useState<number | null>(null);
  const [quote, setQuote] = useState<QuoteResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [degraded, setDegraded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<string | null>(null);
  const [releasesAt, setReleasesAt] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [contactLine, setContactLine] = useState<string | null>(null);
  const [payMissing, setPayMissing] = useState(false);
  const [lookout, setLookout] = useState<string | null>(null);
  const committed = useRef(false);

  const loadAccount = useCallback(async () => {
    if (!handle) {
      setAccount(null);
      return;
    }
    try {
      const row = await api.account(handle);
      setAccount(row);
      setError(null);
      setPayMissing(false);
    } catch (err) {
      setAccount(null);
      if (err instanceof ApiError && err.code === "unknown_handle") {
        setError("No account with that handle in the demo ledger.");
      } else {
        setError(err instanceof Error ? err.message : "Could not load this account.");
      }
    }
  }, [handle]);

  useEffect(() => {
    void loadAccount();
  }, [loadAccount]);

  // Lookout: factual pre-amount check. Silent unless RingWatch is above the
  // tier-0 boundary. Never a positive "this payee is fine" label.
  useEffect(() => {
    const target = payee.trim();
    if (!target) {
      setLookout(null);
      return;
    }
    const id = window.setTimeout(() => {
      void api
        .beneficiaryCheck(target)
        .then((row) => {
          setLookout(row.flag === "watch" && row.user_reason ? row.user_reason : null);
        })
        .catch(() => setLookout(null));
    }, 400);
    return () => window.clearTimeout(id);
  }, [payee]);

  useEffect(() => {
    const id = window.setInterval(() => setTick((n) => n + 1), 1000);
    return () => window.clearInterval(id);
  }, []);

  const payPath = account?.account_id ? `/ws/pay/${account.account_id}` : null;
  useTopicSocket(
    payPath,
    (event) => {
      if (event.type === "snapshot") {
        const data = event.data as {
          balance_paise?: number;
          available_paise?: number;
          active_holds?: AccountView["active_holds"];
        };
        setAccount((prev) =>
          prev
            ? {
                ...prev,
                balance_paise: data.balance_paise ?? prev.balance_paise,
                available_paise: data.available_paise ?? prev.available_paise,
                active_holds: data.active_holds ?? prev.active_holds,
              }
            : prev,
        );
      }
      if (event.type === "hold.opened" || event.type === "hold.extended") {
        const data = event.data as { releases_at?: string };
        if (data.releases_at) {
          setReleasesAt(data.releases_at);
        }
        void loadAccount();
      }
      if (event.type === "hold.released") {
        const data = event.data as { outcome?: string };
        setContactLine(
          data.outcome === "cancelled_by_user"
            ? "This payment was cancelled."
            : "The wait ended and the remainder was sent.",
        );
        void loadAccount();
      }
      if (event.type === "circuit_breaker.acked") {
        const data = event.data as { ack_action?: string; contact_name?: string };
        const name = data.contact_name || "Your trusted contact";
        if (data.ack_action === "approved") {
          setContactLine(`${name} approved this.`);
        } else if (data.ack_action === "hold") {
          setContactLine(`${name} asked us to keep holding.`);
        }
        void loadAccount();
      }
    },
    undefined,
    { onDead: () => setPayMissing(true) },
  );

  useEffect(() => {
    if (!releasesAt || !quote) {
      return;
    }
    if (new Date(releasesAt).getTime() - Date.now() > 0) {
      return;
    }
    void loadAccount();
  }, [tick, releasesAt, quote, loadAccount]);

  const amountPaise = useMemo(() => rupeesToPaise(rupees), [rupees]);
  const kind = quote?.action.kind;

  const onQuote = async (event: FormEvent) => {
    event.preventDefault();
    setFieldError(null);
    setDegraded(false);
    setOutcome(null);
    committed.current = false;
    if (!handle) {
      setFieldError("Enter a sender handle.");
      return;
    }
    if (amountPaise == null || amountPaise <= 0) {
      setFieldError("Enter an amount in rupees.");
      return;
    }
    if (account && amountPaise > account.available_paise) {
      setFieldError(
        `Available balance is ${formatPaise(account.available_paise)}. Holds don't reduce your balance, only what you can spend right now.`,
      );
      return;
    }
    setBusy(true);
    try {
      if (lookout && account?.account_id) {
        await api.beneficiaryDismiss(account.account_id, payee.trim());
      }
      const result = await api.quote({
        sender_handle: handle,
        beneficiary_handle: payee.trim(),
        amount_paise: amountPaise,
        note: note.trim() || undefined,
      });
      setQuote(result);
      setContactLine(contactCopy(result));
    } catch (err) {
      if (err instanceof ApiError && err.code === "unknown_handle") {
        setFieldError("No account with that handle in the demo ledger.");
        setQuote(null);
      } else if (err instanceof ApiError && err.code === "insufficient_available") {
        setFieldError(
          `Available balance is ${formatPaise(account?.available_paise || 0)}. Holds don't reduce your balance, only what you can spend right now.`,
        );
      } else if (err instanceof ApiError && err.code === "bad_amount") {
        setFieldError(err.message);
      } else {
        setDegraded(true);
        setQuote(null);
      }
    } finally {
      setBusy(false);
    }
  };

  const canCommit = () => {
    if (!quote || degraded) {
      return false;
    }
    if (kind === "purpose_challenge") {
      return purpose.trim().length >= 3 && probeChoice !== null;
    }
    return true;
  };

  const onProbe = async (index: number) => {
    setProbeChoice(index);
    if (!quote?.probe) {
      return;
    }
    try {
      await api.probe(quote.probe.probe_id, index);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Probe failed.");
    }
  };

  const onCommit = async () => {
    if (!quote || committed.current) {
      return;
    }
    committed.current = true;
    setBusy(true);
    try {
      const result = await api.commit({
        decision_id: quote.decision_id,
        purpose_text: kind === "purpose_challenge" ? purpose.trim() : undefined,
      });
      setOutcome(result.outcome);
      if (result.releases_at) {
        setReleasesAt(result.releases_at);
      }
      if ("circuit_breaker" in result) {
        setContactLine(contactCopy(quote, result.circuit_breaker));
      }
      void loadAccount();
    } catch (err) {
      committed.current = false;
      if (err instanceof ApiError && err.code === "already_committed") {
        setOutcome("settled");
      } else {
        setError(err instanceof Error ? err.message : "Commit failed.");
      }
    } finally {
      setBusy(false);
    }
  };

  const onCancel = async () => {
    if (!quote) {
      return;
    }
    setBusy(true);
    try {
      await api.cancel(quote.decision_id);
      setOutcome("cancelled_by_user");
      void loadAccount();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Cancel failed.");
    } finally {
      setBusy(false);
    }
  };

  const hold = account?.active_holds[0];
  const slotMargin = quote ? Math.min(quote.tier, 4) * 28 : 0;
  const holdKinds =
    kind === "scoped_hold_cooling" || kind === "scoped_hold_plus_circuit_breaker";

  return (
    <div className="pay-shell">
      <header className="chrome">
        <DemoChip />
      </header>
      {payMissing ? <div className="degrade">Account not found.</div> : null}
      {hold ? (
        <HoldBanner
          reasonRef={hold.reason_ref}
          heldPaise={hold.held_paise}
          releasesAt={hold.releases_at}
          onCancel={quote && holdKinds ? onCancel : undefined}
        />
      ) : null}
      <div className="pay-body">
        {error ? <p className="field-error">{error}</p> : null}
        <div className="balance-block">
          <span>Balance</span>
          <Money paise={account?.balance_paise ?? 0} />
          <span>Available</span>
          <Money paise={account?.available_paise ?? 0} />
        </div>

        {asParam && !quote ? (
          <p className="pay-context">
            This works like a real payment — the balance and holds are genuine, just on a
            demo ledger, not a bank.
          </p>
        ) : null}

        {!quote ? (
          <form onSubmit={onQuote}>
            {!asParam ? (
              <div className="field">
                <label htmlFor="sender">Paying as</label>
                <input
                  id="sender"
                  className="mono"
                  value={handleInput}
                  onChange={(e) => setHandleInput(e.target.value)}
                  placeholder="ramesh@prima"
                  autoComplete="off"
                />
              </div>
            ) : null}
            <div className="field">
              <label htmlFor="payee">Pay to</label>
              <input
                id="payee"
                className="mono"
                value={payee}
                onChange={(e) => setPayee(e.target.value)}
                autoComplete="off"
              />
              {lookout ? <p className="lookout-note">{lookout}</p> : null}
              {fieldError ? <div className="field-error">{fieldError}</div> : null}
            </div>
            <div className="field">
              <label htmlFor="amount">Amount</label>
              <input
                id="amount"
                className="mono"
                value={rupees}
                onChange={(e) => setRupees(e.target.value)}
                inputMode="decimal"
              />
            </div>
            <div className="field">
              <label htmlFor="note">What's this for? (optional)</label>
              <textarea id="note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
            </div>
            {degraded ? (
              <div className="degrade">
                Checks unavailable — this payment was not scored.
                <button
                  className="btn"
                  type="submit"
                  disabled={busy}
                  style={{ marginTop: 8 }}
                >
                  Try again
                </button>
              </div>
            ) : (
              <button className="btn" type="submit" disabled={busy}>
                Check and pay
              </button>
            )}
          </form>
        ) : (
          <div>
            <VerdictCard quote={quote} />
            {kind !== "pass_silent" && quote.counterfactual ? (
              <p className="counterfactual">{quote.counterfactual}</p>
            ) : null}
            {kind === "purpose_challenge" ? (
              <div className="field">
                <label htmlFor="purpose">Who is this person to you?</label>
                <input
                  id="purpose"
                  value={purpose}
                  onChange={(e) => setPurpose(e.target.value)}
                />
              </div>
            ) : null}
            {quote.probe ? (
              <ComprehensionProbe
                question={quote.probe.question}
                options={quote.probe.options}
                chosen={probeChoice}
                onChoose={(index) => void onProbe(index)}
              />
            ) : null}
            <LadderAction
              quote={quote}
              remaining={releasesAt ? remainingLabel(releasesAt) : undefined}
              contactLine={contactLine}
            />
            {outcome ? (
              <div className="outcome">
                {outcome === "settled" ? "Sent." : null}
                {outcome === "held"
                  ? `Waiting. ${releasesAt ? remainingLabel(releasesAt) : ""}`
                  : null}
                {outcome === "cancelled_by_user"
                  ? "Cancelled. The remainder was not sent."
                  : null}
                {outcome === "held" ? (
                  <button
                    className="btn btn-ghost"
                    type="button"
                    onClick={onCancel}
                    style={{ marginTop: 12 }}
                  >
                    Cancel
                  </button>
                ) : null}
              </div>
            ) : (
              <div className="confirm-slot" style={{ marginTop: slotMargin }}>
                <button
                  className="btn"
                  type="button"
                  disabled={busy || !canCommit()}
                  onClick={() => void onCommit()}
                >
                  {payButtonLabel(quote, amountPaise || 0)}
                </button>
                {holdKinds ? (
                  <button
                    className="btn btn-ghost"
                    type="button"
                    onClick={onCancel}
                    style={{ marginTop: 8 }}
                  >
                    Cancel
                  </button>
                ) : null}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
