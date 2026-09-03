import { formatPaise } from "../lib/format";

export function Money({ paise }: { paise: number }) {
  return <span className="money">{formatPaise(paise)}</span>;
}
