import type { Metrics } from "../types";
import { formatPaise, percent } from "../lib/format";
import { Caption } from "./Caption";

export function MetricStrip({ metrics }: { metrics: Metrics | null }) {
  const coverageValue =
    metrics && metrics.denominators.seeded_structures === 0
      ? "—"
      : metrics
        ? percent(metrics.multiparty_coverage)
        : "—";
  const coverageCaption =
    "Confirmed rings this system actually caught" +
    (coverageValue === "—" ? " (none confirmed yet this session)" : "");

  const cells = [
    {
      label: "Prevented",
      value: metrics ? formatPaise(metrics.prevented_loss_paise) : "—",
      caption: "Money held or cancelled on flagged payments",
    },
    {
      label: "Lead time",
      value: metrics ? `${Math.round(metrics.median_lead_time_ms / 1000)} s` : "—",
      caption: "How long before the payment would have settled",
    },
    {
      label: "False chal",
      value: metrics ? percent(metrics.false_challenge_rate) : "—",
      caption: "Ordinary payments this system got wrong",
    },
    {
      label: "Compreh.",
      value: metrics ? percent(metrics.comprehension_rate) : "—",
      caption: "How often a payer correctly explained the warning",
    },
    {
      label: "Coverage",
      value: coverageValue,
      caption: coverageCaption,
    },
  ];
  return (
    <div className="metrics">
      {cells.map((cell) => (
        <div className="metric" key={cell.label}>
          <div className="value">{cell.value}</div>
          <div className="label">{cell.label}</div>
          <Caption>{cell.caption}</Caption>
        </div>
      ))}
    </div>
  );
}
