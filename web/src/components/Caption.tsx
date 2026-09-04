import type { ReactNode } from "react";

/** Always-visible one-line explanation. Never a hover-only tooltip. */
export function Caption({ children }: { children: ReactNode }) {
  return <p className="caption">{children}</p>;
}
