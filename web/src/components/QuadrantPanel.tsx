import { useMemo } from "react";
import type { DecisionItem } from "../types";
import { Caption } from "./Caption";
import { tierColor } from "./Chrome";

export function QuadrantPanel({ items }: { items: DecisionItem[] }) {
  const dots = useMemo(
    () =>
      items.slice(0, 80).map((item) => ({
        id: item.decision_id,
        x: Math.min(1, item.fused_score),
        y: item.tier >= 3 ? 0.75 : item.tier / 4,
        tier: item.tier,
      })),
    [items],
  );
  return (
    <section className="quadrant">
      <Caption>
        Where risk actually lives: a clean-looking payee paired with a compromised
        sender is the case a blocklist can't catch — that's the highlighted corner.
      </Caption>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "var(--graphite)" }}>
        <span>Sender state risk</span>
        <span>Compromised sender, clean-looking payee — registries miss this</span>
        <span>Beneficiary history risk</span>
      </div>
      <svg className="plot" viewBox="0 0 400 110" role="img" aria-label="Risk quadrant">
        <line x1="200" y1="8" x2="200" y2="102" stroke="var(--hairline)" />
        <line x1="8" y1="55" x2="392" y2="55" stroke="var(--hairline)" />
        <rect x="8" y="8" width="192" height="47" fill="var(--t4-bg)" opacity="0.7" />
        {dots.map((dot) => (
          <circle
            key={dot.id}
            cx={8 + dot.x * 384}
            cy={102 - dot.y * 94}
            r="3.5"
            fill={tierColor(dot.tier)}
          />
        ))}
      </svg>
    </section>
  );
}
