import type { DecisionItem } from "../types";
import { formatClock, formatPaise } from "../lib/format";
import { TierChip, tierColor } from "./Chrome";

export function DecisionRail({
  items,
  queued,
  onOpen,
}: {
  items: DecisionItem[];
  queued: number;
  onOpen: (item: DecisionItem) => void;
}) {
  return (
    <aside className="rail">
      <div className="rail-head">
        Live decisions
        {queued > 0 ? <span className="muted"> {queued} new</span> : null}
      </div>
      {items.slice(0, 200).map((item) => {
        const known = item.verdict === "known";
        return (
          <button
            key={item.decision_id}
            className="decision-row"
            type="button"
            style={{ borderLeftColor: tierColor(item.tier) }}
            onClick={() => onOpen(item)}
          >
            <TierChip tier={item.tier} />
            <span className="handle">{item.receiver}</span>
            <span className="money">{formatPaise(item.amount_paise)}</span>
            <span className="muted">{item.verdict}</span>
            <span className="muted" style={known ? { opacity: 0.35 } : undefined}>
              {known ? "" : item.top_rule || "—"}
            </span>
            <span className="muted" style={known ? { opacity: 0.35 } : undefined}>
              {known ? "" : item.fused_score.toFixed(2)}
            </span>
            <span className="muted">{formatClock(item.ts)}</span>
          </button>
        );
      })}
    </aside>
  );
}
