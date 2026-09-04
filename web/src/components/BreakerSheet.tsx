import { FactList } from "./PayerBits";

export function BreakerSheet({
  headline,
  amount,
  facts,
  busy,
  onHold,
  onApprove,
}: {
  headline: string;
  amount: string;
  facts: string[];
  busy: boolean;
  onHold: () => void;
  onApprove: () => void;
}) {
  return (
    <div className="breaker-sheet">
      <div className="demo-chip">
        <strong>PRIMA</strong>
        <em>Demo ledger</em>
      </div>
      <h1>
        {headline}
        <div className="amount money">{amount}</div>
      </h1>
      <FactList facts={facts} />
      <div style={{ display: "grid", gap: 8, marginTop: 24 }}>
        <button className="btn btn-t4" type="button" disabled={busy} onClick={onHold}>
          Something's wrong — hold it
        </button>
        <button className="btn btn-ghost" type="button" disabled={busy} onClick={onApprove}>
          This is fine
        </button>
      </div>
    </div>
  );
}
