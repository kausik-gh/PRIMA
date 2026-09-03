const ids = new Set<string>();
const listeners = new Set<() => void>();

export function rememberGuest(accountId: string): void {
  ids.add(accountId);
  listeners.forEach((fn) => fn());
}

export function isRememberedGuest(accountId: string): boolean {
  return ids.has(accountId);
}

export function subscribeGuests(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}
