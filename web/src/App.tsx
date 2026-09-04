import { Suspense, lazy, type ReactNode } from "react";
import { Route, Routes, useSearchParams } from "react-router-dom";
import { NavBar } from "./components/NavBar";
import { HomePage } from "./pages/HomePage";
import { PayPage } from "./pages/PayPage";

const ConsolePage = lazy(() =>
  import("./pages/ConsolePage").then((m) => ({ default: m.ConsolePage })),
);
const OpsPage = lazy(() => import("./pages/OpsPage").then((m) => ({ default: m.OpsPage })));
const WatchPage = lazy(() =>
  import("./pages/WatchPage").then((m) => ({ default: m.WatchPage })),
);

/** Wraps a page in the persistent nav bar. */
function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <NavBar />
      <div className="app-main">{children}</div>
    </div>
  );
}

/**
 * A judge who scanned a QR arrives at /pay?as=<handle> and should see ONLY the
 * payment screen. Someone who typed /pay directly (e.g. testing) gets the nav
 * bar so they are not stranded.
 */
function PayRoute() {
  const [params] = useSearchParams();
  if (params.get("as")) {
    return <PayPage />;
  }
  return (
    <Shell>
      <PayPage />
    </Shell>
  );
}

export default function App() {
  return (
    <Suspense fallback={<div className="pay-body">Loading</div>}>
      <Routes>
        <Route
          path="/"
          element={
            <Shell>
              <HomePage />
            </Shell>
          }
        />
        <Route
          path="/console"
          element={
            <Shell>
              <ConsolePage />
            </Shell>
          }
        />
        <Route path="/pay" element={<PayRoute />} />
        <Route path="/watch/:token" element={<WatchPage />} />
        <Route
          path="/ops"
          element={
            <Shell>
              <OpsPage />
            </Shell>
          }
        />
      </Routes>
    </Suspense>
  );
}
