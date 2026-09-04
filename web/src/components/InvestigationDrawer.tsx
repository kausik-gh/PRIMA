import type { InvestigatePayload } from "../types";
import { formatPaise } from "../lib/format";
import { TierChip } from "./Chrome";
import { Money } from "./Money";

export function ContributionBars({
  contributions,
}: {
  contributions: InvestigatePayload["contributions"];
}) {
  const max = Math.max(0.01, ...contributions.map((row) => Math.abs(row.contribution)));
  return (
    <div>
      {contributions.map((row) => (
        <div className="bar" key={row.scorer}>
          <span>{row.scorer}</span>
          <div className="bar-track">
            <div
              className="bar-fill"
              style={{ width: `${Math.min(100, (Math.abs(row.contribution) / max) * 100)}%` }}
            />
          </div>
          <span className="mono">
            {row.weight == null
              ? `+ ${row.contribution.toFixed(3)}`
              : `${row.value.toFixed(2)} × ${row.weight.toFixed(2)} = ${row.contribution.toFixed(3)}`}
          </span>
        </div>
      ))}
    </div>
  );
}

export function EventTimeline({
  events,
}: {
  events: InvestigatePayload["event_timeline"];
}) {
  if (!events.length) {
    return <p className="muted">No events in the recent window.</p>;
  }
  return (
    <ul className="facts">
      {events.map((event) => (
        <li key={`${event.ts}-${event.type}`}>
          <span className="mono">{event.ts.slice(11, 16)}</span> {event.summary}
        </li>
      ))}
    </ul>
  );
}

export function InvestigationDrawer({
  payload,
  onClose,
  onRegulator,
}: {
  payload: InvestigatePayload;
  onClose: () => void;
  onRegulator: () => void;
}) {
  const ctxRules = payload.rules_fired.filter((rule) =>
    ["secrecy", "fear", "urgency", "greed", "bypass_approval"].includes(String(rule.code || "")),
  );
  const toast = (label: string) => {
    window.alert(`${label}: not available in this build`);
  };
  const headerTier = payload.tier ?? 0;
  const headerFused = payload.fused_score;
  return (
    <div className="drawer">
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <div>
          <div className="mono">{payload.account.handle}</div>
          <div className="muted">
            tier {headerTier}
            {headerFused != null ? ` · ${headerFused}` : ""}
            {payload.verdict ? ` · ${payload.verdict}` : ""}
          </div>
          <div className="muted">
            Opened {payload.account.age_days} days ago · {payload.account.bank_code}
          </div>
        </div>
        <button className="btn btn-ghost" type="button" onClick={onClose} style={{ width: "auto" }}>
          Close
        </button>
      </div>
      <p>
        <TierChip tier={headerTier} /> available{" "}
        <Money paise={payload.account.available_paise} />
      </p>
      <h3>Contribution</h3>
      <ContributionBars contributions={payload.contributions} />
      <h3>Rules fired</h3>
      <ul className="facts">
        {payload.rules_fired.map((rule) => (
          <li key={`${rule.code}-${rule.detail}`}>
            <span className="mono">{rule.code || "rule"}</span> {rule.points ?? ""} {rule.detail}
          </li>
        ))}
      </ul>
      <h3>Sequence</h3>
      <EventTimeline events={payload.event_timeline} />
      {ctxRules.length ? (
        <>
          <h3>Context</h3>
          <p className="muted">
            {ctxRules.map((row) => `${row.code} ${row.points ?? ""}`).join(" · ")}
          </p>
        </>
      ) : null}
      {payload.pattern_match ? (
        <p>
          Pattern match {Math.round(payload.pattern_match.similarity * 100)}% ·{" "}
          {payload.pattern_match.label}
        </p>
      ) : null}
      <div style={{ display: "grid", gap: 8, marginTop: 16 }}>
        {payload.available_actions.includes("open_scoped_hold") ? (
          <button className="btn btn-ghost" type="button" onClick={() => toast("Open scoped hold")}>
            Open scoped hold
          </button>
        ) : null}
        {payload.available_actions.includes("mark_reviewed") ? (
          <button className="btn btn-ghost" type="button" onClick={() => toast("Mark reviewed")}>
            Mark reviewed
          </button>
        ) : null}
        <button className="btn btn-ghost" type="button" onClick={onRegulator}>
          Download regulator record
        </button>
        <span className="muted">
          Balance {formatPaise(payload.account.balance_paise)} — inbound is never held.
        </span>
      </div>
    </div>
  );
}
