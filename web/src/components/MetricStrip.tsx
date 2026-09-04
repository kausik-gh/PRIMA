import type { Metrics } from "../types";
import { formatPaise, percent } from "../lib/format";

export function MetricStrip({ metrics }: { metrics: Metrics | null }) {
  const cells = [
    {
      label: "Prevented",
      value: metrics ? formatPaise(metrics.prevented_loss_paise) : "—",
      hint: metrics ? `${metrics.denominators.legit_tx} legit tx` : "",
    },
    {
      label: "Lead time",
      value: metrics ? `${Math.round(metrics.median_lead_time_ms / 1000)} s` : "—",
      hint: "median, committed decisions",
    },
    {
      label: "False chal",
      value: metrics ? percent(metrics.false_challenge_rate) : "—",
      hint: metrics ? `tier ≥ 1 on ${metrics.denominators.legit_tx} legit` : "",
    },
    {
      label: "Compreh.",
      value: metrics ? percent(metrics.comprehension_rate) : "—",
      hint: metrics ? `${metrics.denominators.probes_shown} probes shown` : "",
    },
    {
      label: "Coverage",
      value:
        metrics && metrics.denominators.seeded_structures === 0
          ? "—"
          : metrics
            ? percent(metrics.multiparty_coverage)
            : "—",
      hint: metrics ? `${metrics.denominators.seeded_structures} structures` : "",
    },
  ];
  return (
    <div className="metrics">
      {cells.map((cell) => (
        <div className="metric" key={cell.label} title={cell.hint}>
          <div className="value">{cell.value}</div>
          <div className="label">{cell.label}</div>
        </div>
      ))}
    </div>
  );
}
