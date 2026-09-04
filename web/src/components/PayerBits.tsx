import type { QuoteAction, QuoteResponse } from "../types";
import { formatPaise, remainingLabel } from "../lib/format";
import { Money } from "./Money";
import { tierColor } from "./Chrome";

export function FactList({ facts }: { facts: string[] }) {
  if (!facts.length) {
    return null;
  }
  return (
    <ul className="facts">
      {facts.map((line) => (
        <li key={line}>{line}</li>
      ))}
    </ul>
  );
}

export function VerdictCard({ quote }: { quote: QuoteResponse }) {
  const quiet = quote.action.kind === "pass_silent";
  return (
    <section
      className={`verdict t${quote.tier}`}
      style={{
        borderLeftColor: tierColor(quote.tier),
        background: `var(--t${quote.tier}-bg)`,
      }}
    >
      <h2>{quote.headline}</h2>
      {!quiet ? <FactList facts={quote.facts.slice(0, 3)} /> : null}
    </section>
  );
}

export function LadderAction({
  quote,
  remaining,
  contactLine,
}: {
  quote: QuoteResponse;
  remaining?: string;
  contactLine?: string | null;
}) {
  const action: QuoteAction = quote.action;
  const heldKind =
    action.kind === "scoped_hold_cooling" ||
    action.kind === "scoped_hold_plus_circuit_breaker";
  if (!heldKind) {
    return null;
  }
  const immediate = action.immediate_paise ?? 100;
  const held = action.held_paise ?? 0;
  const minutes = action.cooling_minutes ?? 30;
  return (
    <div className="ladder-note">
      <div>We'll send {formatPaise(immediate)} now.</div>
      <div>
        {formatPaise(held)} goes in {minutes} minutes.
      </div>
      <div>You can cancel any time before then.</div>
      {remaining ? <div>{remaining} remaining</div> : null}
      {action.kind === "scoped_hold_plus_circuit_breaker" && contactLine ? (
        <div>{contactLine}</div>
      ) : null}
    </div>
  );
}

export function ComprehensionProbe({
  question,
  options,
  chosen,
  onChoose,
}: {
  question: string;
  options: string[];
  chosen: number | null;
  onChoose: (index: number) => void;
}) {
  return (
    <fieldset className="probe" style={{ border: 0, padding: 0, margin: "0 0 16px" }}>
      <legend>{question}</legend>
      {options.map((option, index) => (
        <label key={option}>
          <input
            type="radio"
            name="probe"
            checked={chosen === index}
            onChange={() => onChoose(index)}
          />
          <span>{option}</span>
        </label>
      ))}
    </fieldset>
  );
}

export function HoldBanner({
  reasonRef,
  heldPaise,
  releasesAt,
  onCancel,
}: {
  reasonRef: string;
  heldPaise: number;
  releasesAt: string | null;
  onCancel?: () => void;
}) {
  return (
    <div className="hold-banner">
      <div>
        {reasonRef} holds <Money paise={heldPaise} />
      </div>
      <div>Releases {releasesAt ? remainingLabel(releasesAt) : "—"}</div>
      {onCancel ? (
        <button className="btn btn-ghost" type="button" onClick={onCancel}>
          Cancel
        </button>
      ) : null}
    </div>
  );
}

export function payButtonLabel(quote: QuoteResponse, amountPaise: number): string {
  if (
    quote.action.kind === "scoped_hold_cooling" ||
    quote.action.kind === "scoped_hold_plus_circuit_breaker"
  ) {
    const immediate = quote.action.immediate_paise ?? 100;
    return `Send ${formatPaise(immediate)} and start the wait`;
  }
  return `Pay ${formatPaise(amountPaise)}`;
}
