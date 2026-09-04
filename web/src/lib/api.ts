export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function apiBase(): string {
  const env = import.meta.env.VITE_API_BASE;
  if (typeof env === "string" && env.trim()) {
    return env.replace(/\/$/, "");
  }
  return window.location.origin;
}

function abs(path: string): string {
  if (path.startsWith("http://") || path.startsWith("https://")) {
    return path;
  }
  return `${apiBase()}${path}`;
}

export function wsUrl(path: string): string {
  const url = new URL(path, apiBase());
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

async function parse(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) {
    return {};
  }
  try {
    return JSON.parse(text);
  } catch {
    return { error: { code: "bad_json", message: text } };
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(abs(path), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  const body = (await parse(res)) as {
    error?: { code?: string; message?: string };
  };
  if (!res.ok) {
    throw new ApiError(
      res.status,
      body.error?.code || "http_error",
      body.error?.message || res.statusText,
    );
  }
  return body as T;
}

export const api = {
  quote: (body: {
    sender_handle: string;
    beneficiary_handle: string;
    amount_paise: number;
    note?: string;
  }) =>
    request<import("../types").QuoteResponse>("/api/payer/quote", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  commit: (body: { decision_id: string; purpose_text?: string }) =>
    request<import("../types").CommitResponse>("/api/payer/commit", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  probe: (probeId: string, chosen_index: number) =>
    request<{ correct: boolean }>(`/api/payer/probe/${probeId}`, {
      method: "POST",
      body: JSON.stringify({ chosen_index }),
    }),
  cancel: (decision_id: string) =>
    request<{ outcome: string }>("/api/payer/cancel", {
      method: "POST",
      body: JSON.stringify({ decision_id }),
    }),
  account: (handle: string) =>
    request<import("../types").AccountView>(
      `/api/payer/account/${encodeURIComponent(handle)}`,
    ),
  graph: (window = 500, bank = "ALL") =>
    request<{
      nodes: import("../types").GraphNode[];
      links: import("../types").GraphLink[];
    }>(`/api/console/graph?window=${window}&bank=${encodeURIComponent(bank)}`),
  decisions: (limit = 100) =>
    request<{ items: import("../types").DecisionItem[] }>(
      `/api/console/decisions?limit=${limit}`,
    ),
  investigate: (accountId: string) =>
    request<import("../types").InvestigatePayload>(
      `/api/console/investigate/${encodeURIComponent(accountId)}`,
    ),
  regulator: (decisionId: string) =>
    request<Record<string, unknown>>(
      `/api/console/decision/${encodeURIComponent(decisionId)}/regulator`,
    ),
  metrics: () => request<import("../types").Metrics>("/api/metrics/ps3"),
  health: () => request<import("../types").Health>("/api/ops/health"),
  seed: (accounts?: number, days?: number) =>
    request<Record<string, unknown>>("/api/ops/seed", {
      method: "POST",
      body: JSON.stringify({ accounts, days }),
    }),
  guest: (display_name: string) =>
    request<{
      handle: string;
      account_id: string;
      pay_url: string;
      balance_paise: number;
    }>("/api/ops/guest", {
      method: "POST",
      body: JSON.stringify({ display_name }),
    }),
  inject: (account_id: string) =>
    request<{ ok: boolean; scenario: string; events: Array<{ event_type: string; ts: string }> }>(
      "/api/ops/inject_sequence",
      {
        method: "POST",
        body: JSON.stringify({ account_id, scenario: "takeover_isolation" }),
      },
    ),
  context: (account_id: string, text: string) =>
    request<{ ok: boolean; event_id: string; event_type: string }>("/api/ops/context", {
      method: "POST",
      body: JSON.stringify({ account_id, text }),
    }),
  event: (account_id: string, event_type: string, payload?: Record<string, unknown>) =>
    request<{ ok: boolean }>("/api/ops/event", {
      method: "POST",
      body: JSON.stringify({ account_id, event_type, payload }),
    }),
  nominate: (account_id: string, contact_name: string) =>
    request<{ watch_url: string; watch_token: string; contact_name: string }>(
      "/api/ops/nominate_contact",
      {
        method: "POST",
        body: JSON.stringify({ account_id, contact_name }),
      },
    ),
  fireBreaker: (token: string) =>
    request<{ ok: boolean; log_id: string; token: string }>("/api/ops/fire_breaker", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),
  reportFraud: (transaction_id: string) =>
    request<Record<string, unknown>>("/api/ops/report_fraud", {
      method: "POST",
      body: JSON.stringify({ transaction_id }),
    }),
  reset: () => request<{ ok: boolean }>("/api/ops/reset", { method: "POST" }),
};
