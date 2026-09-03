export function formatPaise(paise: number): string {
  const sign = paise < 0 ? "-" : "";
  const abs = Math.abs(Math.trunc(paise));
  const rupees = Math.floor(abs / 100);
  const remainder = abs % 100;
  const grouped = indianGroup(rupees);
  if (remainder) {
    return `${sign}₹${grouped}.${String(remainder).padStart(2, "0")}`;
  }
  return `${sign}₹${grouped}`;
}

function indianGroup(rupees: number): string {
  const digits = String(rupees);
  if (digits.length <= 3) {
    return digits;
  }
  const head = digits.slice(0, -3);
  const tail = digits.slice(-3);
  const parts: string[] = [];
  let rest = head;
  while (rest.length > 0) {
    parts.push(rest.slice(-2));
    rest = rest.slice(0, -2);
  }
  return `${parts.reverse().join(",")},${tail}`;
}

/** Parse a rupee field (450 or 4,00,000) into integer paise. */
export function rupeesToPaise(raw: string): number | null {
  const cleaned = raw.replace(/[₹,\s]/g, "");
  if (!cleaned) {
    return null;
  }
  const value = Number(cleaned);
  if (!Number.isFinite(value) || value < 0) {
    return null;
  }
  return Math.round(value * 100);
}

export function formatClock(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function remainingLabel(releasesAt: string | null): string {
  if (!releasesAt) {
    return "—";
  }
  const end = new Date(releasesAt).getTime();
  const ms = end - Date.now();
  if (ms <= 0) {
    return "0:00";
  }
  const total = Math.floor(ms / 1000);
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export function percent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}
