/**
 * The watch surface only makes sense with a real token from a real nominated
 * contact. Ops writes the last nominated token here after a successful
 * `nominate_contact`, so the home page can offer a working link instead of a
 * guessable default that lands on an unexplained empty screen.
 */
const KEY = "prima.watchToken";

export function rememberWatchToken(token: string): void {
  try {
    sessionStorage.setItem(KEY, token);
  } catch {
    /* private mode / storage disabled — the link just stays hidden */
  }
}

export function readWatchToken(): string | null {
  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}
