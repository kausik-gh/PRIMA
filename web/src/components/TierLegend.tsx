import { tierColor } from "./Chrome";

const TIERS: Array<{ tier: number; label: string }> = [
  { tier: 0, label: "nothing unusual" },
  { tier: 1, label: "watch" },
  { tier: 2, label: "ask why" },
  { tier: 3, label: "pace it" },
  { tier: 4, label: "second person" },
];

/**
 * Colour-to-meaning key for the Interrupt Ladder tiers. Uses the same
 * `tierColor()` swatches the decision rail and graph use — no new colours.
 */
export function TierLegend() {
  return (
    <div className="tier-legend">
      {TIERS.map(({ tier, label }) => (
        <span className="tier-legend-item" key={tier}>
          <span
            className="tier-legend-dot"
            style={{ background: tierColor(tier) }}
            aria-hidden
          />
          <span className="tier-legend-num">{tier}</span> {label}
        </span>
      ))}
    </div>
  );
}
