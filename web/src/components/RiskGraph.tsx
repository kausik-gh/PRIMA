import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import type { GraphLink, GraphNode } from "../types";
import { isRememberedGuest, subscribeGuests } from "../lib/guests";
import { tierColor } from "./Chrome";

type Props = {
  nodes: GraphNode[];
  links: GraphLink[];
  paused: boolean;
  focusId: string | null;
  onNodeClick: (node: GraphNode) => void;
};

function nodeId(value: string | GraphNode): string {
  return typeof value === "string" ? value : value.id;
}

export function RiskGraph({ nodes, links, paused, focusId, onNodeClick }: Props) {
  const [, setGuestTick] = useState(0);
  useEffect(() => subscribeGuests(() => setGuestTick((n) => n + 1)), []);

  const ref2d = useRef<{
    pauseAnimation: () => void;
    resumeAnimation: () => void;
    centerAt: (x: number, y: number, ms?: number) => void;
  } | null>(null);
  const wrap = useRef<HTMLDivElement>(null);

  const data = useMemo(() => {
    const degree = new Map<string, number>();
    for (const link of links) {
      const src = nodeId(link.source);
      const dst = nodeId(link.target);
      degree.set(src, (degree.get(src) || 0) + 1);
      degree.set(dst, (degree.get(dst) || 0) + 1);
    }
    return {
      nodes: nodes.map((node) => ({
        ...node,
        val: Math.max(4, Math.min(14, Math.log2((degree.get(node.id) || 1) + 1) * 4)),
      })),
      links,
    };
  }, [nodes, links]);

  useEffect(() => {
    const graph = ref2d.current;
    if (!graph) {
      return;
    }
    if (paused) {
      graph.pauseAnimation();
    } else {
      graph.resumeAnimation();
    }
  }, [paused]);

  useEffect(() => {
    if (!focusId || !ref2d.current) {
      return;
    }
    const node = data.nodes.find((item) => item.id === focusId) as
      | { x?: number; y?: number }
      | undefined;
    if (node && typeof node.x === "number" && typeof node.y === "number") {
      ref2d.current.centerAt(node.x, node.y, 400);
    }
  }, [focusId, data.nodes]);

  const paint = (
    node: GraphNode & { x?: number; y?: number; val?: number },
    ctx: CanvasRenderingContext2D,
  ) => {
    const x = node.x || 0;
    const y = node.y || 0;
    const r = node.val || 6;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fillStyle = tierColor(node.tier);
    ctx.fill();
    if (node.is_held) {
      ctx.lineWidth = 2;
      ctx.strokeStyle = "#97232B";
      ctx.stroke();
    }
    if (isRememberedGuest(node.id)) {
      ctx.beginPath();
      ctx.arc(x, y, r + 3, 0, Math.PI * 2);
      ctx.lineWidth = 3;
      ctx.strokeStyle = "#1F5C8C";
      ctx.stroke();
    }
  };

  const width = wrap.current?.clientWidth || 800;
  const height = wrap.current?.clientHeight || 520;

  return (
    <div ref={wrap} style={{ width: "100%", height: "100%" }}>
      <ForceGraph2D
        ref={ref2d}
        graphData={data}
        width={width}
        height={height}
        backgroundColor="rgba(0,0,0,0)"
        nodeLabel={(node: GraphNode) => node.handle}
        nodeColor={(node: GraphNode) => tierColor(node.tier)}
        nodeCanvasObject={paint}
        linkColor={(link: GraphLink) => (link.taint > 0.15 ? "#97232B" : "#D2D8DF")}
        linkWidth={(link: GraphLink) =>
          Math.max(0.4, Math.min(4, Math.log10((link.amount_paise || 100) / 100 + 1)))
        }
        cooldownTicks={120}
        onEngineStop={() => {
          if (paused) {
            ref2d.current?.pauseAnimation();
          }
        }}
        onNodeClick={(node: GraphNode) => onNodeClick(node)}
      />
    </div>
  );
}
