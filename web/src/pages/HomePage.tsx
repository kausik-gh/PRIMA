import { Link } from "react-router-dom";
import { TierLegend } from "../components/TierLegend";
import { readWatchToken } from "../lib/watchLink";

type Card = {
  to: string | null;
  title: string;
  blurb: string;
  note?: string;
};

export function HomePage() {
  const watchToken = readWatchToken();
  const cards: Card[] = [
    {
      to: "/console",
      title: "Console",
      blurb: "The live view. Every payment as it happens, on a graph.",
    },
    {
      to: "/pay",
      title: "Pay",
      blurb: "Try sending money as a demo account and see the check in real time.",
    },
    {
      to: "/ops",
      title: "Ops",
      blurb: "Set up a scenario, provision judges, seed data.",
    },
    {
      to: watchToken ? `/watch/${watchToken}` : null,
      title: "Watch",
      blurb: "The second-person screen. Silent until a payment needs another opinion.",
      note: watchToken
        ? "A scenario is set up — open the live watch link."
        : "Opens automatically when Ops provisions a scenario. Not browsable directly.",
    },
  ];

  return (
    <div className="home">
      <div className="home-head">
        <h1>PRIMA</h1>
        <p className="home-lede">
          A risk check that runs in the seconds before a payment is confirmed — not after.
        </p>
        <p className="home-sub">
          It plugs into an existing fraud stack and answers with a graduated action, never a
          freeze. Everything here runs on a demo ledger — no real money, no payment rails.
        </p>
      </div>

      <div className="home-cards">
        {cards.map((card) =>
          card.to ? (
            <Link className="home-card" to={card.to} key={card.title}>
              <span className="home-card-title">{card.title}</span>
              <span className="home-card-blurb">{card.blurb}</span>
              {card.note ? <span className="home-card-note">{card.note}</span> : null}
            </Link>
          ) : (
            <div className="home-card is-disabled" key={card.title} aria-disabled>
              <span className="home-card-title">{card.title}</span>
              <span className="home-card-blurb">{card.blurb}</span>
              {card.note ? <span className="home-card-note">{card.note}</span> : null}
            </div>
          ),
        )}
      </div>

      <div className="home-legend">
        <span className="home-legend-label">The five tiers</span>
        <TierLegend />
      </div>
    </div>
  );
}
