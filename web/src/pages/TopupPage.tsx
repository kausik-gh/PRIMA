import { FormEvent, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";

type RazorpayInstance = {
  open: () => void;
  on: (event: string, handler: (response: { error?: { description?: string } }) => void) => void;
};

type RazorpayCtor = new (options: {
  key: string;
  amount: number;
  currency: string;
  name: string;
  description: string;
  order_id: string;
  handler: () => void;
  modal: { ondismiss: () => void };
}) => RazorpayInstance;

declare global {
  interface Window {
    Razorpay?: RazorpayCtor;
  }
}

function loadCheckout(): Promise<RazorpayCtor> {
  if (window.Razorpay) {
    return Promise.resolve(window.Razorpay);
  }
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.async = true;
    script.onload = () => {
      if (window.Razorpay) {
        resolve(window.Razorpay);
        return;
      }
      reject(new Error("Checkout script loaded without Razorpay."));
    };
    script.onerror = () => reject(new Error("Could not load Razorpay Checkout."));
    document.body.appendChild(script);
  });
}

export function TopupPage() {
  const [params] = useSearchParams();
  const accountId = (params.get("account_id") || "").trim();
  const [rupees, setRupees] = useState("1");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [waiting, setWaiting] = useState(false);

  const amountPaise = useMemo(() => {
    const n = Number(rupees);
    if (!Number.isFinite(n)) {
      return 0;
    }
    return Math.round(n * 100);
  }, [rupees]);

  const startCheckout = async (event?: FormEvent) => {
    event?.preventDefault();
    setNote(null);
    setWaiting(false);
    if (!accountId) {
      setNote("Missing account_id in the URL.");
      return;
    }
    if (amountPaise <= 0 || amountPaise > 10000) {
      setNote("Amount must be between Rs 0.01 and Rs 100.");
      return;
    }
    setBusy(true);
    try {
      const Razorpay = await loadCheckout();
      const order = await api.razorpayOrder(accountId, amountPaise);
      const checkout = new Razorpay({
        key: order.key_id,
        amount: order.amount_paise,
        currency: "INR",
        name: "PRIMA",
        description: "PRIMA demo top-up",
        order_id: order.order_id,
        handler: () => {
          // Checkout success is not a credit. The webhook is the only source of truth.
          setWaiting(true);
          setNote("Payment submitted — waiting for confirmation");
        },
        modal: {
          ondismiss: () => {
            setWaiting(false);
            setNote("Checkout closed before a payment was submitted.");
          },
        },
      });
      checkout.on("payment.failed", (response) => {
        setWaiting(false);
        setNote(response.error?.description || "Payment failed. Try again.");
      });
      checkout.open();
    } catch (err) {
      const message =
        err instanceof ApiError ? `${err.code}: ${err.message}` : err instanceof Error ? err.message : String(err);
      setNote(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ops">
      <h1>PRIMA demo top-up</h1>
      <p className="ops-context">
        Razorpay Test Mode funds one demo account. The ledger only moves after the
        webhook confirms capture. Instant guest credit on /ops is still the fast path.
      </p>
      {!accountId ? (
        <p className="field-error">Open this page from /ops after provisioning a guest.</p>
      ) : (
        <section className="ops-card" style={{ maxWidth: 420 }}>
          <h2>Fund account</h2>
          <p className="ops-hint">{accountId}</p>
          <form onSubmit={(e) => void startCheckout(e)}>
            <label htmlFor="topup-rupees">Amount (rupees)</label>
            <input
              id="topup-rupees"
              className="mono"
              value={rupees}
              onChange={(e) => setRupees(e.target.value)}
              inputMode="decimal"
            />
            <button className="btn" type="submit" disabled={busy} style={{ marginTop: 8 }}>
              {busy ? "Opening Checkout" : waiting ? "Retry Checkout" : "Pay with Razorpay"}
            </button>
          </form>
          {note ? <p className="ops-hint" style={{ marginTop: 12 }}>{note}</p> : null}
        </section>
      )}
      <p style={{ marginTop: 16 }}>
        <Link to="/ops">Back to ops</Link>
      </p>
    </div>
  );
}
