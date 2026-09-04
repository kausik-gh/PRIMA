import { FormEvent, useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { rememberGuest } from "../lib/guests";
import { rememberWatchToken } from "../lib/watchLink";
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

  // Guided-run progress. Purely visual — every tile below stays clickable in
  // any order. This is a checklist, not a wizard.
  const [guideOpen, setGuideOpen] = useState(true);
  const [seeded, setSeeded] = useState(false);
  const [provisioned, setProvisioned] = useState(false);
  const [injected, setInjected] = useState(false);
  const [ambientStoppedForRun, setAmbientStoppedForRun] = useState(false);
  const [liveWatchToken, setLiveWatchToken] = useState<string | null>(null);
  const [ambientRunning, setAmbientRunning] = useState(false);

  const refresh = async () => {
    const [h, graph] = await Promise.all([api.health(), api.graph(500)]);
    setHealth(h);
    setAmbientRunning(Boolean(h.ambient_running));
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

  const run = async (
    label: string,
    fn: () => Promise<unknown>,
    onOk?: (result: unknown) => void,
  ) => {
    setBusy(true);
    try {
      const result = await fn();
      setLog(`${label}: ${JSON.stringify(result)}`);
      onOk?.(result);
      await refresh();
    } catch (err) {
      const message =
        err instanceof ApiError ? `${err.code}: ${err.message}` : String(err);
      setLog(`${label}: ${message}`);
    } finally {
      setBusy(false);
    }
  };

  const provisionGuest = async () => {
    await run(
      "guest",
      async () => {
        const created = await api.guest(guestName);
        rememberGuest(created.account_id);
        const origin = window.location.origin;
        const card = {
          ...created,
          pay_url: `${origin}/pay?as=${encodeURIComponent(created.handle)}`,
        };
        setGuests((rows) => [card, ...rows]);
        return created;
      },
      () => setProvisioned(true),
    );
  };

  const onGuest = async (event: FormEvent) => {
    event.preventDefault();
    await provisionGuest();
  };

  const doSeed = () => run("seed", () => api.seed(500, 21), () => setSeeded(true));

  const doStopAmbient = () =>
    run("ambient/stop", () => api.ambientStop(), () => setAmbientStoppedForRun(true));

  const doInject = () =>
    run(
      "inject",
      async () => {
        // Quiet the rail before Act 3 so the judge watches one row, not noise.
        await api.ambientStop();
        setAmbientStoppedForRun(true);
        return api.inject(accountId);
      },
      () => setInjected(true),
    );

  const doRearm = () => run("rearm", () => api.rearm(accountId));

  const doNominate = () =>
    run(
      "nominate",
      () => api.nominate(accountId, contactName),
      (result) => {
        const token = (result as { watch_token?: string }).watch_token;
        if (token) {
          setLiveWatchToken(token);
          setWatchToken(token);
          rememberWatchToken(token);
        }
      },
    );

  const toggleAmbient = () =>
    run("ambient", () => (ambientRunning ? api.ambientStop() : api.ambientStart()));

  const step = (n: number, done: boolean, label: string) => (
    <div className={done ? "guide-row done" : "guide-row"}>
      <span className="guide-dot" aria-hidden>
        {done ? "●" : "○"}
      </span>
      <span className="guide-num">{n}</span>
      <span className="guide-label">{label}</span>
    </div>
  );

  return (
    <div className="ops">
      <h1>PRIMA ops</h1>
      <p className="ops-context">
        Backstage controls — not shown to judges. Sets up real data the console and pay
        screens read from.
      </p>

      <section className="ops-card guide">
        <div className="guide-head">
          <h2>Guided run</h2>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => setGuideOpen((v) => !v)}
          >
            {guideOpen ? "Collapse" : "Expand"}
          </button>
        </div>
        {guideOpen ? (
          <>
            <p className="guide-intro">
              This is the order a live demo run follows. Nothing here is required in order —
              it's a checklist, not a wizard.
            </p>
            <ol className="guide-list">
              <li>
                {step(1, seeded, "Seed the ledger")}
                <button className="btn" type="button" disabled={busy} onClick={doSeed}>
                  Seed 500 / 21d
                </button>
              </li>
              <li>
                {step(2, provisioned, "Provision a judge")}
                <button
                  className="btn"
                  type="button"
                  disabled={busy}
                  onClick={() => void provisionGuest()}
                >
                  Provision guest
                </button>
              </li>
              <li>
                {step(3, ambientStoppedForRun, "Stop ambient traffic")}
                <button
                  className="btn"
                  type="button"
                  disabled={busy}
                  onClick={doStopAmbient}
                >
                  Stop ambient
                </button>
              </li>
              <li>
                {step(4, injected, "Set up the scenario")}
                <button
                  className="btn"
                  type="button"
                  disabled={busy || !accountId}
                  onClick={doInject}
                >
                  Inject takeover
                </button>
              </li>
              <li>
                {step(5, Boolean(liveWatchToken), "Nominate a trusted contact")}
                <button
                  className="btn"
                  type="button"
                  disabled={busy || !accountId}
                  onClick={doNominate}
                >
                  Nominate {contactName}
                </button>
              </li>
              <li>
                {step(6, Boolean(liveWatchToken), "Open the watch link")}
                {liveWatchToken ? (
                  <Link className="guide-link" to={`/watch/${liveWatchToken}`} target="_blank">
                    /watch/{liveWatchToken}
                  </Link>
                ) : (
                  <span className="guide-link is-muted">
                    appears once a contact is nominated
                  </span>
                )}
              </li>
              <li>
                {step(7, false, "Open the console")}
                <Link className="guide-link" to="/console" target="_blank">
                  /console
                </Link>
              </li>
              <li>
                {step(8, false, "Hand the judge their QR — they pay on their phone")}
              </li>
            </ol>
          </>
        ) : null}
      </section>

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
              <li>ambient_running {String(Boolean(health.ambient_running))}</li>
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
          <button className="btn" type="button" disabled={busy} onClick={doSeed}>
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
          <h2>ambient traffic</h2>
          <p className="ops-hint">
            Low-stakes real transfers between anonymous seeded accounts, so the graph keeps
            moving between acts. Never touches the named demo accounts.
          </p>
          <button
            className="btn"
            type="button"
            disabled={busy}
            onClick={toggleAmbient}
          >
            {ambientRunning ? "Stop ambient" : "Start ambient"}
          </button>
          <p className="facts" style={{ marginTop: 8 }}>
            status: {ambientRunning ? "running" : "stopped"}
          </p>
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
                <div>
                  <Link to={`/topup?account_id=${encodeURIComponent(guest.account_id)}`}>
                    Fund via Razorpay
                  </Link>
                </div>
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
            onClick={doInject}
            style={{ marginTop: 8 }}
          >
            inject takeover_isolation
          </button>
          <button
            className="btn btn-ghost"
            type="button"
            disabled={busy || !accountId}
            onClick={doRearm}
            style={{ marginTop: 8 }}
          >
            rearm sequence
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
            onClick={doNominate}
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
