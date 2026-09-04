import { useState } from "react";
import { useParams } from "react-router-dom";
import { BreakerSheet } from "../components/BreakerSheet";
import { DemoChip } from "../components/Chrome";
import { useTopicSocket } from "../lib/ws";

type Fired = {
  headline: string;
  amount: string;
  facts: string[];
};

export function WatchPage() {
  const { token = "priya-ramesh-demo" } = useParams();
  const [connected, setConnected] = useState(false);
  const [watchingFor, setWatchingFor] = useState("Ramesh");
  const [fired, setFired] = useState<Fired | null>(null);
  const [acked, setAcked] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [wsError, setWsError] = useState<string | null>(null);

  const { send, reconnecting } = useTopicSocket(
    `/ws/watch/${token}`,
    (event) => {
      if (event.type === "snapshot") {
        const data = event.data as { watching_for?: string };
        if (data.watching_for) {
          setWatchingFor(data.watching_for);
        }
      }
      if (event.type === "circuit_breaker.fired") {
        const data = event.data as Fired;
        setFired({
          headline: data.headline,
          amount: data.amount,
          facts: data.facts || [],
        });
        setAcked(null);
        if (navigator.vibrate) {
          navigator.vibrate([200, 100, 200]);
        }
      }
      if (event.type === "circuit_breaker.acked") {
        const data = event.data as { ack_action?: string };
        setAcked(data.ack_action || "acked");
      }
      if (event.type === "error") {
        const data = event.data as { message?: string };
        setWsError(data.message || "Watch channel error.");
      }
    },
    setConnected,
    { onDead: () => setWsError("Watch token not found.") },
  );

  const ack = (action: "hold" | "approved") => {
    setBusy(true);
    send({ type: "circuit_breaker.ack", action });
    setBusy(false);
  };

  if (fired && !acked) {
    return (
      <BreakerSheet
        headline={fired.headline}
        amount={fired.amount}
        facts={fired.facts}
        busy={busy}
        onHold={() => ack("hold")}
        onApprove={() => ack("approved")}
      />
    );
  }

  return (
    <div className="watch-shell">
      <header className="chrome">
        <DemoChip />
        {reconnecting || !connected ? <span className="reconnect">reconnecting…</span> : null}
      </header>
      <div className="watch-idle">
        <p>You're watching for {watchingFor}.</p>
        <p>{acked ? "That's noted." : "Nothing needs you right now."}</p>
        {wsError ? <p className="field-error">{wsError}</p> : null}
        <p>
          <span className={connected ? "dot" : "dot off"} />
          {connected ? "connected" : "reconnecting"}
        </p>
      </div>
    </div>
  );
}
