import { NavLink } from "react-router-dom";

const LINKS = [
  { to: "/console", label: "Console" },
  { to: "/pay", label: "Pay" },
  { to: "/ops", label: "Ops" },
];

/**
 * Persistent top nav. Rendered on the home, console, ops and (only when no
 * `?as=` judge handle is present) the pay route. The single-purpose surfaces
 * — a judge's pay screen and a trusted contact's watch screen — get no nav
 * chrome, so nobody wanders off mid-flow.
 */
export function NavBar() {
  return (
    <header className="nav-bar">
      <NavLink to="/" className="nav-brand">
        PRIMA
      </NavLink>
      <nav className="nav-links">
        {LINKS.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
          >
            {link.label}
          </NavLink>
        ))}
      </nav>
      <span className="nav-demo">Demo ledger</span>
    </header>
  );
}
