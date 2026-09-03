import { FormEvent, useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { api, ApiError } from "../lib/api";
import { rememberGuest } from "../lib/guests";
import type { GraphNode, Health } from "../types";

type GuestCard = {
  handle: string;
  account_id: string;
  pay_url: string;
  balance_paise: number;
};

type Named = { id: string; handle: string };

const EVENT_TYPES = [
  "login_new_device",
  "credential_changed",
  "payee_added",
  "limit_raised",
  "screen_share_active",
];

const STAGE = new Set([
  "ramesh@prima",
  "priya.k@prima",
  "grocery@prima",
  "rentals@prima",
  "quickcash@prima",
  "merchant.ok@prima",
]);

export function OpsPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [named, setNamed] = useState<Named[]>([]);
  const [accountId, setAccountId] = useState("");
  const [guestName, setGuestName] = useState("Judge 3");
  const [guests, setGuests] = useState<GuestCard[]>([]);
  const [contextText, setContextText] = useState("");
  const [eventType, setEventType] = useState(EVENT_TYPES[0]);
  const [contactName, setContactName] = useState("Priya");
  const [watchToken, setWatchToken] = useState("priya-ramesh-demo");
  const [txId, setTxId] = useState("");
  const [log, setLog] = useState<string>("");
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    const [h, graph] = await Promise.all([api.health(), api.graph(500)]);
    setHealth(h);
    const rows = graph.nodes
      .filter((node: GraphNode) => STAGE.has(node.handle))
      .map((node) => ({ id: node.id, handle: node.handle }));
    setNamed(rows);
    if (!accountId && rows.length) {
      const ramesh = rows.find((row) => row.handle === "ramesh@prima") || rows[0];
      setAccountId(ramesh.id);
    }
  };

  useEffect(() => {
    void refresh().catch((err) => setLog(String(err)));
  }, []);

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      const result = await fn();
      setLog(`${label}: ${JSON.stringify(result)}`);
      await refresh();
    } catch (err) {
      const message =
        err instanceof ApiError ? `${err.code}: ${err.message}` : String(err);
      setLog(`${label}: ${message}`);
    } finally {
      setBusy(false);
    }
  };

  const onGuest = async (event: FormEvent) => {
    event.preventDefault();
    await run("guest", async () => {
      const created = await api.guest(guestName);
      rememberGuest(created.account_id);
      const origin = window.location.origin;
      const card = {
        ...created,
        pay_url: `${origin}/pay?as=${encodeURIComponent(created.handle)}`,
      };
      setGuests((rows) => [card, ...rows]);
      return created;
    });
  };

  return (
    <div className="ops">
      <h1>PRIMA ops</h1>
      <p>Demo ledger control. Not the product surface.</p>
      <div className="ops-grid">
        <section className="ops-card">
          <h2>health</h2>
          {health ? (
            <ul className="facts">
              <li className={health.db_ok ? "health-ok" : "health-bad"}>
                db_ok {String(health.db_ok)}
              </li>
              <li>rf_model_loaded {String(health.rf_model_loaded)}</li>
              <li>gnn_model_loaded {String(health.gnn_model_loaded)}</li>
              <li>ws_clients {health.ws_clients}</li>
              <li>last_decision_at {health.last_decision_at || "none"}</li>
            </ul>
          ) : (
            "loading"
          )}
          <button className="btn" type="button" disabled={busy} onClick={() => void refresh()}>
            refresh
          </button>
        </section>

        <section className="ops-card">
          <h2>seed / reset</h2>
          <button
            className="btn"
            type="button"
            disabled={busy}
            onClick={() => void run("seed", () => api.seed(500, 21))}
          >
            seed 500 / 21d
          </button>
          <button
            className="btn danger"
            type="button"
            disabled={busy}
            onClick={() => void run("reset", () => api.reset())}
            style={{ marginTop: 8 }}
          >
            reset
          </button>
        </section>

        <section className="ops-card">
          <h2>provision guest</h2>
          <form onSubmit={onGuest}>
            <input value={guestName} onChange={(e) => setGuestName(e.target.value)} />
            <button className="btn" type="submit" disabled={busy} style={{ marginTop: 8 }}>
              provision guest
            </button>
          </form>
          {guests.map((guest) => (
            <div className="guest-qr" key={guest.account_id}>
              <QRCodeSVG value={guest.pay_url} size={96} />
              <div>
                <div>{guest.handle}</div>
                <a href={guest.pay_url}>{guest.pay_url}</a>
              </div>
            </div>
          ))}
        </section>

        <section className="ops-card">
          <h2>act 3 inject</h2>
          <select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
            {named.map((row) => (
              <option key={row.id} value={row.id}>
                {row.handle}
              </option>
            ))}
          </select>
          <button
            className="btn"
            type="button"
            disabled={busy || !accountId}
            onClick={() => void run("inject", () => api.inject(accountId))}
            style={{ marginTop: 8 }}
          >
            inject takeover_isolation
          </button>
          <button
            className="btn btn-ghost"
            type="button"
            disabled={busy || !accountId}
            onClick={() => void run("event", () => api.event(accountId, "login_new_device"))}
            style={{ marginTop: 8 }}
          >
            manual: login_new_device
          </button>
          <textarea
            rows={4}
            placeholder="scripted call-context text"
            value={contextText}
            onChange={(e) => setContextText(e.target.value)}
            style={{ width: "100%", marginTop: 8 }}
          />
          <button
            className="btn"
            type="button"
            disabled={busy || !accountId || !contextText.trim()}
            onClick={() => void run("context", () => api.context(accountId, contextText))}
            style={{ marginTop: 8 }}
          >
            inject context
          </button>
        </section>

        <section className="ops-card">
          <h2>circuit breaker</h2>
          <input value={watchToken} onChange={(e) => setWatchToken(e.target.value)} />
          <button
            className="btn"
            type="button"
            disabled={busy}
            onClick={() => void run("fire", () => api.fireBreaker(watchToken))}
            style={{ marginTop: 8 }}
          >
            fire breaker (manual)
          </button>
          <input
            value={contactName}
            onChange={(e) => setContactName(e.target.value)}
            style={{ marginTop: 8 }}
          />
          <button
            className="btn btn-ghost"
            type="button"
            disabled={busy || !accountId}
            onClick={() => void run("nominate", () => api.nominate(accountId, contactName))}
            style={{ marginTop: 8 }}
          >
            nominate contact
          </button>
          <p>
            watch{" "}
            <a href={`/watch/${watchToken}`} target="_blank" rel="noreferrer">
              /watch/{watchToken}
            </a>
          </p>
        </section>

        <section className="ops-card">
          <h2>event form</h2>
          <select value={eventType} onChange={(e) => setEventType(e.target.value)}>
            {EVENT_TYPES.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <button
            className="btn"
            type="button"
            disabled={busy || !accountId}
            onClick={() => void run("event", () => api.event(accountId, eventType))}
            style={{ marginTop: 8 }}
          >
            inject event
          </button>
        </section>

        <section className="ops-card">
          <h2>report</h2>
          <input
            placeholder="transaction_id"
            value={txId}
            onChange={(e) => setTxId(e.target.value)}
          />
          <button
            className="btn"
            type="button"
            disabled={busy || !txId.trim()}
            onClick={() => void run("report_fraud", () => api.reportFraud(txId.trim()))}
            style={{ marginTop: 8 }}
          >
            Report fraud
          </button>
        </section>
      </div>
      <pre style={{ marginTop: 24, whiteSpace: "pre-wrap" }}>{log}</pre>
    </div>
  );
}
