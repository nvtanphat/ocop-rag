import { useEffect, useMemo, useState } from "react";
import { api, type Citation, type Subgraph, type SubgraphNode, type SubgraphSeed } from "../../api/client";
import { GRAPH_SIZE, layoutSubgraph } from "./layout";

const TYPE_LABELS: Record<string, string> = {
  Criterion: "Tiêu chí",
  CriterionSheet: "Phiếu tiêu chí",
  ScoreOption: "Mức điểm",
  EvidenceType: "Minh chứng",
  EvidenceUnit: "Đoạn bằng chứng",
  Article: "Điều",
  Clause: "Khoản",
  Point: "Điểm",
  SourceDocument: "Văn bản",
  Product: "Sản phẩm",
  ProductGroup: "Nhóm sản phẩm",
  RecognitionDecision: "Quyết định công nhận",
  RecognitionRecord: "Bản ghi công nhận",
  ProcedureStep: "Bước thủ tục",
  FormTemplate: "Biểu mẫu",
  Condition: "Điều kiện",
  Authority: "Cơ quan",
  StarLevel: "Hạng sao",
};
const RELATION_LABELS: Record<string, string> = {
  SUPPORTED_BY: "được dẫn chứng bởi",
  HAS_CRITERION: "có tiêu chí",
  HAS_SUBCRITERION: "có tiêu chí con",
  HAS_OPTION: "có mức điểm",
  HAS_POINT: "có điểm",
  HAS_CLAUSE: "có khoản",
  HAS_ARTICLE: "có điều",
  HAS_CONDITION: "có điều kiện",
  REQUIRES_EVIDENCE: "yêu cầu minh chứng",
  REFERENCES: "tham chiếu",
  REPLACES: "thay thế",
  BASED_ON: "căn cứ",
  RESPONSIBLE_FOR: "chịu trách nhiệm",
  CONTAINS: "chứa",
  MENTIONS: "đề cập",
};
const PALETTE = ["#2f6b52", "#2a6fdb", "#e8453c", "#f09a1a", "#8a5bd6", "#13a06a", "#c4623b", "#3a86b4"];
const typeLabel = (type: string) => TYPE_LABELS[type] ?? type;
const relationLabel = (type: string) => RELATION_LABELS[type] ?? type;
const clip = (text: string, max: number) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);
const reviewed = (node: SubgraphNode) => node.review_status === "verified" || node.review_status === "human_verified";

export function KnowledgeGraph({
  seed,
  onSeed,
  onOpen,
}: {
  seed: SubgraphSeed;
  onSeed: (seed: SubgraphSeed) => void;
  onOpen: (citation: Citation) => void;
}) {
  const [graph, setGraph] = useState<Subgraph | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const seedKey = "evidenceUnitId" in seed ? `e:${seed.evidenceUnitId}` : `n:${seed.nodeId}`;

  useEffect(() => {
    let live = true;
    setGraph(null);
    setError("");
    setSelected(null);
    api
      .subgraph(seed)
      .then((result) => live && setGraph(result))
      .catch((reason: unknown) => live && setError(reason instanceof Error ? reason.message : "Không tải được đồ thị."));
    return () => {
      live = false;
    };
    // The seed key identifies the request; the object identity changes on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seedKey]);

  const placed = useMemo(
    () => (graph?.status === "ok" ? layoutSubgraph(graph.nodes, graph.edges, graph.seed_ids) : []),
    [graph],
  );
  const types = useMemo(() => Array.from(new Set(placed.map((p) => p.node.node_type))).sort(), [placed]);
  const color = (type: string) => PALETTE[types.indexOf(type) % PALETTE.length];
  const at = new Map(placed.map((p) => [p.node.node_id, p]));
  const chosen = selected ? at.get(selected)?.node : undefined;
  const links = chosen && graph ? graph.edges.filter((e) => e.source === chosen.node_id || e.target === chosen.node_id) : [];

  if (error) return <div className="vstate err" role="alert"><h3>Không tải được đồ thị tri thức</h3><p>{error}</p></div>;
  if (!graph) return <div className="vstate">Đang tải quan hệ tri thức…</div>;
  if (graph.status !== "ok")
    return (
      <div className="vstate">
        <h3>{graph.status === "no_graph" ? "Chưa có đồ thị tri thức" : "Không tìm thấy nút phù hợp"}</h3>
        <p>Chỉ hiển thị các nút và quan hệ đã qua kiểm tra của hệ thống.</p>
      </div>
    );

  return (
    <>
      <div id="glegend" style={{ display: "flex" }}>
        {types.map((type) => (
          <span key={type}>
            <i style={{ background: color(type) }} />
            {typeLabel(type)}
          </span>
        ))}
      </div>
      <svg id="gsvg" viewBox={`0 0 ${GRAPH_SIZE.width} ${GRAPH_SIZE.height}`} preserveAspectRatio="xMidYMid meet">
        {graph.edges.map((edge) => {
          const a = at.get(edge.source);
          const b = at.get(edge.target);
          if (!a || !b) return null;
          const hot = chosen && (edge.source === chosen.node_id || edge.target === chosen.node_id);
          return (
            <line
              key={edge.edge_id}
              className={`ed ${hot ? "hot" : chosen ? "dim" : ""}`}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
            />
          );
        })}
        {placed.map(({ node, x, y, depth }) => {
          const isSeed = depth === 0;
          const active = selected === node.node_id;
          return (
            <g
              key={node.node_id}
              className={`nd ${active ? "sel" : ""} ${chosen && !active ? "dim" : ""}`}
              tabIndex={0}
              role="button"
              aria-label={`${typeLabel(node.node_type)}: ${node.label}`}
              onClick={() => setSelected(node.node_id)}
              onKeyDown={(event) => event.key === "Enter" && setSelected(node.node_id)}
            >
              <circle
                cx={x}
                cy={y}
                r={isSeed ? 11 : 7}
                style={{ fill: color(node.node_type), stroke: reviewed(node) ? "#18a56e" : "#fff", strokeDasharray: reviewed(node) ? undefined : "3 2" }}
              />
              {(isSeed || active) && (
                <text x={x} y={y + (isSeed ? 24 : 20)} textAnchor="middle" className="t2">
                  {clip(node.label, 24)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <div id="gdet">
        {chosen ? (
          <>
            <b>{clip(chosen.label, 90)}</b>
            <div className="meta">
              {typeLabel(chosen.node_type)} · đạt kiểm tra tự động ·{" "}
              {reviewed(chosen) ? "đã được người duyệt" : "chưa được người duyệt"}
            </div>
            {links.slice(0, 5).map((edge) => {
              const otherId = edge.source === chosen.node_id ? edge.target : edge.source;
              const other = at.get(otherId)?.node;
              return (
                <div className="meta" key={edge.edge_id}>
                  {edge.source === chosen.node_id ? "→" : "←"} {relationLabel(edge.relation_type)}{" "}
                  {other ? clip(other.label, 40) : otherId}
                </div>
              );
            })}
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button type="button" onClick={() => onSeed({ nodeId: chosen.node_id })}>
                Khám phá từ nút này
              </button>
              {chosen.citations.slice(0, 2).map((citation, index) => (
                <button
                  key={index}
                  type="button"
                  onClick={() =>
                    onOpen({
                      source_id: citation.source_id,
                      pdf_page: citation.pdf_page,
                      bbox: citation.bbox,
                      evidence_unit_id: citation.evidence_unit_id,
                      source_sha256: citation.source_sha256,
                    })
                  }
                >
                  Mở PDF trang {citation.pdf_page}
                </button>
              ))}
            </div>
          </>
        ) : (
          "Chọn một nút để xem quan hệ và căn cứ."
        )}
      </div>
      <p className="gnote">
        {graph.nodes.length} nút, {graph.edges.length} quan hệ đã qua kiểm tra
        {graph.truncated ? " (đã giới hạn số nút hiển thị)" : ""}. Viền xanh liền là nút đã được người duyệt; viền đứt là
        nút chỉ đạt kiểm tra tự động.
      </p>
    </>
  );
}
