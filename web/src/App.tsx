import { Suspense, lazy } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { PayPage } from "./pages/PayPage";

const ConsolePage = lazy(() =>
  import("./pages/ConsolePage").then((m) => ({ default: m.ConsolePage })),
);
const OpsPage = lazy(() => import("./pages/OpsPage").then((m) => ({ default: m.OpsPage })));
const WatchPage = lazy(() =>
  import("./pages/WatchPage").then((m) => ({ default: m.WatchPage })),
);

export default function App() {
  return (
    <Suspense fallback={<div className="pay-body">Loading</div>}>
      <Routes>
        <Route path="/" element={<Navigate to="/console" replace />} />
        <Route path="/console" element={<ConsolePage />} />
        <Route path="/pay" element={<PayPage />} />
        <Route path="/watch/:token" element={<WatchPage />} />
        <Route path="/ops" element={<OpsPage />} />
      </Routes>
    </Suspense>
  );
}
