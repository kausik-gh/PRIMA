export function DemoChip() {
  return (
    <div className="demo-chip">
      <strong>PRIMA</strong>
      <em>Demo ledger</em>
    </div>
  );
}

export const TIER_HEX = ["#3E7C5A", "#A8781F", "#C0552B", "#97232B", "#5A3596"];

export function tierColor(tier: number): string {
  return TIER_HEX[Math.max(0, Math.min(4, tier))] || TIER_HEX[0];
}

export function TierChip({ tier }: { tier: number }) {
  return (
    <span className="tier-chip" style={{ color: tierColor(tier) }}>
      {tier}
    </span>
  );
}
