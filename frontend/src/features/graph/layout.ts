import type { SubgraphEdge, SubgraphNode } from "../../api/client";

export interface Placed {
  node: SubgraphNode;
  x: number;
  y: number;
  depth: number;
}

export const GRAPH_SIZE = { width: 460, height: 420 };

// Deterministic concentric layout: seeds in the middle, then one ring per hop; nodes of the same type stay together.
export function layoutSubgraph(nodes: SubgraphNode[], edges: SubgraphEdge[], seeds: string[]): Placed[] {
  const neighbours = new Map<string, string[]>();
  for (const edge of edges) {
    neighbours.set(edge.source, [...(neighbours.get(edge.source) ?? []), edge.target]);
    neighbours.set(edge.target, [...(neighbours.get(edge.target) ?? []), edge.source]);
  }
  const depth = new Map<string, number>(seeds.map((id) => [id, 0]));
  const queue = [...seeds];
  for (let index = 0; index < queue.length; index++) {
    for (const next of neighbours.get(queue[index]) ?? []) {
      if (!depth.has(next)) {
        depth.set(next, depth.get(queue[index])! + 1);
        queue.push(next);
      }
    }
  }
  const rings = new Map<number, SubgraphNode[]>();
  for (const node of nodes) {
    const level = depth.get(node.node_id) ?? Math.max(1, ...depth.values());
    rings.set(level, [...(rings.get(level) ?? []), node]);
  }
  const cx = GRAPH_SIZE.width / 2;
  const cy = GRAPH_SIZE.height / 2;
  const maxLevel = Math.max(...rings.keys());
  const placed: Placed[] = [];
  for (const [level, ring] of rings) {
    ring.sort((a, b) => a.node_type.localeCompare(b.node_type) || a.label.localeCompare(b.label));
    const radius = level === 0 ? (ring.length > 1 ? 38 : 0) : 62 + (level * (Math.min(cx, cy) - 70)) / Math.max(1, maxLevel);
    ring.forEach((node, index) => {
      const angle = (2 * Math.PI * index) / ring.length - Math.PI / 2;
      placed.push({ node, depth: level, x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) });
    });
  }
  return placed;
}
