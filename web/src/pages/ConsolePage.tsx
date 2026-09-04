import { useCallback, useEffect, useState } from "react";
import { Caption } from "../components/Caption";
import { DecisionRail } from "../components/DecisionRail";
import { InvestigationDrawer } from "../components/InvestigationDrawer";
import { MetricStrip } from "../components/MetricStrip";
import { QuadrantPanel } from "../components/QuadrantPanel";
import { RiskGraph } from "../components/RiskGraph";
import { TierLegend } from "../components/TierLegend";
import { api } from "../lib/api";
import { useTopicSocket } from "../lib/ws";
import type {
  DecisionItem,
  GraphLink,
  GraphNode,
  InvestigatePayload,
  Metrics,
} from "../types";

const STAGE_HANDLES = new Set([
  "ramesh@prima",
  "priya.k@prima",
  "grocery@prima",
  "rentals@prima",
  "quickcash@prima",
  "merchant.ok@prima",
]);

function thinGraph(nodes: GraphNode[], links: GraphLink[], maxLinks = 160) {
  const linkNode = (value: string | GraphNode) =>
    typeof value === "string" ? value : value.id;
  const idToHandle = new Map(nodes.map((n) => [n.id, n.handle]));
  const isStage = (link: GraphLink) =>
    STAGE_HANDLES.has(idToHandle.get(linkNode(link.source)) || "") ||
    STAGE_HANDLES.has(idToHandle.get(linkNode(link.target)) || "");

  // Priority: named demo accounts, then taint > 0, then original recency.
  // Ambient traffic must not crowd out the structures the demo is about.
  const priority = [...links].sort((a, b) => {
    const stageDiff = Number(isStage(b)) - Number(isStage(a));
    if (stageDiff !== 0) return stageDiff;
    const taintDiff = (b.taint || 0) - (a.taint || 0);
    if (taintDiff !== 0) return taintDiff;
    return 0;
  });

  const keptLinks = priority.slice(0, maxLinks);
  const ids = new Set<string>();
  for (const link of keptLinks) {
    ids.add(linkNode(link.source));
    ids.add(linkNode(link.target));
  }
  const keptNodes = nodes.filter(
    (node) => ids.has(node.id) || STAGE_HANDLES.has(node.handle),
  );
  return { nodes: keptNodes, links: keptLinks };
}

export function ConsolePage() {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [links, setLinks] = useState<GraphLink[]>([]);
  const [decisions, setDecisions] = useState<DecisionItem[]>([]);
  const [queued, setQueued] = useState(0);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [paused, setPaused] = useState(false);
  const [bank, setBank] = useState("ALL");
  const [focusId, setFocusId] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<InvestigatePayload | null>(null);
  const [drawerDecisionId, setDrawerDecisionId] = useState<string | null>(null);
  const [wsOk, setWsOk] = useState(false);
  const [ringBusy, setRingBusy] = useState(false);
  const [ringNote, setRingNote] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const [graph, rail, strip] = await Promise.all([
      api.graph(500, bank),
      api.decisions(100),
      api.metrics(),
    ]);
    const thinned = thinGraph(graph.nodes, graph.links);
    setNodes(thinned.nodes);
    setLinks(thinned.links);
    setDecisions(rail.items);
    setMetrics(strip);
  }, [bank]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (wsOk) {
      return;
    }
    const id = window.setInterval(() => {
      void refresh();
    }, 2000);
    return () => window.clearInterval(id);
  }, [wsOk, refresh]);

  const { reconnecting } = useTopicSocket(
    "/ws/console",
    (event) => {
      if (event.type === "snapshot") {
        const data = event.data as {
          graph?: { nodes: GraphNode[]; links: GraphLink[] };
          decisions?: DecisionItem[];
        };
        if (data.graph) {
          const thinned = thinGraph(data.graph.nodes, data.graph.links);
          setNodes(thinned.nodes);
          setLinks(thinned.links);
        }
        if (data.decisions) {
          setDecisions(data.decisions);
        }
        return;
      }
      if (paused && event.type === "decision.created") {
        setQueued((n) => n + 1);
        return;
      }
      if (event.type === "decision.created" || event.type === "decision.committed") {
        const item = event.data as unknown as DecisionItem;
        if (item.decision_id) {
          setDecisions((rows) => [
            item,
            ...rows.filter((row) => row.decision_id !== item.decision_id),
          ]);
        }
      }
      if (event.type === "graph.node_updated") {
        const node = event.data as unknown as GraphNode;
        setNodes((rows) => {
          const next = rows.filter((row) => row.id !== node.id);
          next.push(node);
          return next;
        });
      }
      if (event.type === "graph.link_added") {
        const link = event.data as unknown as GraphLink;
        setLinks((rows) => [link, ...rows]);
      }
      if (event.type === "metrics.updated") {
        setMetrics(event.data as unknown as Metrics);
      }
    },
    setWsOk,
  );

  const openAccount = async (accountId: string, decisionId?: string) => {
    setFocusId(accountId);
    const payload = await api.investigate(accountId);
    setDrawer(payload);
    setDrawerDecisionId(decisionId || null);
  };

  const openDecision = async (item: DecisionItem) => {
    const node = nodes.find((row) => row.handle === item.receiver || row.handle === item.sender);
    if (node) {
      await openAccount(node.id, item.decision_id);
    }
  };

  const downloadRegulator = async () => {
    const decisionId =
      drawerDecisionId ||
      decisions.find(
        (row) =>
          drawer &&
          (row.sender === drawer.account.handle || row.receiver === drawer.account.handle),
      )?.decision_id;
    if (!decisionId) {
      window.alert("No decision record for this account yet.");
      return;
    }
    const record = await api.regulator(decisionId);
    const blob = new Blob([JSON.stringify(record, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `prima-regulator-${decisionId}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const confirmRing = async () => {
    if (!drawer) {
      return;
    }
    const ids = Array.from(
      new Set([drawer.account.id, ...drawer.neighbours.map((row) => row.id)]),
    );
    setRingBusy(true);
    try {
      const result = await api.confirmRing(ids);
      setRingNote(
        `Held ${result.opened_holds.length} of ${result.accounts_in_ring} accounts in this ring.`,
      );
      await refresh();
      await openAccount(drawer.account.id, drawerDecisionId || undefined);
    } catch (err) {
      setRingNote(err instanceof Error ? err.message : "Could not confirm this ring.");
    } finally {
      setRingBusy(false);
    }
  };

  return (
    <>
      <div className="console-context">
        Every payment attempt, scored live. Click a node to see why.
        <Caption>
          Colour is risk tier. Node size is how many payments touch that account.
        </Caption>
      </div>
      <div className="console">
        <MetricStrip metrics={metrics} />
      <div className="stage">
        <RiskGraph
          nodes={nodes}
          links={links}
          paused={paused}
          focusId={focusId}
          onNodeClick={(node) => void openAccount(node.id)}
        />
        <div className="stage-tools">
          {reconnecting || !wsOk ? <span className="reconnect">reconnecting…</span> : null}
          <select value={bank} onChange={(e) => setBank(e.target.value)}>
            <option value="ALL">All banks</option>
            <option value="BANKA">BANKA</option>
            <option value="BANKB">BANKB</option>
          </select>
          <button
            type="button"
            onClick={() => {
              setPaused((v) => !v);
              if (paused) {
                setQueued(0);
              }
            }}
          >
            {paused ? "Resume" : "Pause"}
          </button>
          <details className="legend-details">
            <summary>Tiers</summary>
            <TierLegend />
          </details>
        </div>
        {drawer ? (
          <InvestigationDrawer
            payload={drawer}
            onClose={() => {
              setDrawer(null);
              setRingNote(null);
            }}
            onRegulator={() => void downloadRegulator()}
            onConfirmRing={() => void confirmRing()}
            ringBusy={ringBusy}
            ringNote={ringNote}
          />
        ) : null}
      </div>
        <DecisionRail
          items={decisions}
          queued={queued}
          onOpen={(item) => void openDecision(item)}
        />
        <QuadrantPanel items={decisions} />
      </div>
    </>
  );
}
