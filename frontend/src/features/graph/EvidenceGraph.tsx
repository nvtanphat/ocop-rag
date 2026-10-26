import { useState } from "react";
import type { Citation, Source, SubgraphSeed } from "../../api/client";
import { sourceTitle } from "../../app/sourceLabels";
import { Icon } from "../../components/Icon";
import type { Message } from "../chat/ChatView";
import { KnowledgeGraph } from "./KnowledgeGraph";

const COLUMNS = 3;
const WIDTH = 460;
const NODE = { w: 140, h: 54 };
const SPACING = 150;

const clip = (text: string, max: number) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);

export function EvidenceGraph({
  message,
  sources,
  onOpen,
  onClose,
}: {
  message: Message | null;
  sources: Source[];
  onOpen: (citation: Citation) => void;
  onClose: () => void;
}) {
  const citations = message?.answer?.citations || [];
  const [tab, setTab] = useState<"evidence" | "knowledge">("evidence");
  const [selected, setSelected] = useState<number | null>(null);
  const [seed, setSeed] = useState<SubgraphSeed | null>(null);
  const rows = Math.ceil(citations.length / COLUMNS);
  const height = Math.max(420, 190 + rows * 86);
  const question = { x: WIDTH / 2, y: 52 };
  const place = (index: number) => {
    const inRow = Math.min(COLUMNS, citations.length - Math.floor(index / COLUMNS) * COLUMNS);
    const slot = index % COLUMNS;
    return { x: WIDTH / 2 + (slot - (inRow - 1) / 2) * SPACING, y: 190 + Math.floor(index / COLUMNS) * 86 };
  };
  const chosen = selected === null ? null : citations[selected];
  const firstEvidence = citations.find((citation) => citation.evidence_unit_id)?.evidence_unit_id;
  const activeSeed: SubgraphSeed | null = seed ?? (firstEvidence ? { evidenceUnitId: firstEvidence } : null);
  const explore = (citation: Citation) => {
    if (!citation.evidence_unit_id) return;
    setSeed({ evidenceUnitId: citation.evidence_unit_id });
    setTab("knowledge");
  };

  return (
    <section className="cv glass" id="gpanel" role="dialog" aria-label="Đồ thị dẫn chứng">
      <div className="gh">
        <Icon name="graph" strokeWidth={1.8} />
        <b>Đồ thị dẫn chứng</b>
        <button type="button" className="gx" onClick={onClose} aria-label="Đóng đồ thị">
          <Icon name="close" size={18} strokeWidth={2} />
        </button>
      </div>
      <div className="gtabs">
        <button type="button" className={tab === "evidence" ? "on" : ""} onClick={() => setTab("evidence")}>
          Dẫn chứng câu trả lời
        </button>
        <button type="button" className={tab === "knowledge" ? "on" : ""} onClick={() => setTab("knowledge")}>
          Quan hệ tri thức
        </button>
      </div>
      {!citations.length ? (
        <div className="vstate">
          <h3>Chưa có dẫn chứng để hiển thị</h3>
          <p>Đặt câu hỏi và chọn một câu trả lời có trích dẫn để xem liên kết tới nguồn.</p>
        </div>
      ) : tab === "knowledge" ? (
        activeSeed ? (
          <KnowledgeGraph seed={activeSeed} onSeed={setSeed} onOpen={onOpen} />
        ) : (
          <div className="vstate">
            <h3>Trích dẫn chưa gắn với đoạn bằng chứng</h3>
            <p>Đồ thị tri thức được mở từ mã bằng chứng của trích dẫn.</p>
          </div>
        )
      ) : (
        <>
          <svg id="gsvg" viewBox={`0 0 ${WIDTH} ${height}`} preserveAspectRatio="xMidYMid meet">
            {citations.map((_, index) => {
              const to = place(index);
              return (
                <path
                  key={`edge-${index}`}
                  className={`ed ${selected === index ? "hot" : selected !== null ? "dim" : ""}`}
                  d={`M${question.x},${question.y + 22} C${question.x},${(question.y + to.y) / 2 + 20} ${to.x},${(question.y + to.y) / 2} ${to.x},${to.y - NODE.h / 2}`}
                />
              );
            })}
            <g className="nd q">
              <rect x={question.x - 150} y={question.y - 22} width={300} height={44} rx={10} />
              <text x={question.x} y={question.y + 5} textAnchor="middle" className="t1">
                {clip(message?.question || "", 40)}
              </text>
            </g>
            {citations.map((citation, index) => {
              const at = place(index);
              const source = sources.find((item) => item.source_id === citation.source_id);
              const verified = citation.review_status === "verified";
              return (
                <g
                  key={`node-${index}`}
                  className={`nd s ${verified ? "src-v" : "src-u"} ${selected === index ? "sel" : selected !== null ? "dim" : ""}`}
                  onClick={() => setSelected(index)}
                  tabIndex={0}
                  role="button"
                  aria-label={`Nguồn ${index + 1}`}
                  onKeyDown={(event) => event.key === "Enter" && setSelected(index)}
                >
                  <rect x={at.x - NODE.w / 2} y={at.y - NODE.h / 2} width={NODE.w} height={NODE.h} rx={10} />
                  <text x={at.x} y={at.y - 4} textAnchor="middle" className="t1">
                    {clip(`[S${index + 1}] ${sourceTitle(source, citation.source_id)}`, 21)}
                  </text>
                  <text x={at.x} y={at.y + 14} textAnchor="middle" className="t2">
                    Trang {citation.pdf_page} · {verified ? "đã xác minh" : "chưa duyệt"}
                  </text>
                </g>
              );
            })}
          </svg>
          <div id="gdet">
            {chosen ? (
              <>
                <b>
                  [S{(selected as number) + 1}]{" "}
                  {sourceTitle(sources.find((s) => s.source_id === chosen.source_id), chosen.source_id)}
                </b>
                <div className="meta">
                  Trang {chosen.pdf_page} · {chosen.evidence_unit_id || "chưa có mã bằng chứng"}
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <button type="button" onClick={() => onOpen(chosen)}>
                    Mở PDF tại vị trí trích dẫn
                  </button>
                  {chosen.evidence_unit_id && (
                    <button type="button" onClick={() => explore(chosen)}>
                      Khám phá quan hệ tri thức
                    </button>
                  )}
                </div>
              </>
            ) : (
              "Chọn một nguồn để xem chi tiết."
            )}
          </div>
          <p className="gnote">
            Sơ đồ chỉ thể hiện các liên kết trích dẫn thực tế, không suy diễn quan hệ pháp lý giữa các văn bản.
          </p>
        </>
      )}
    </section>
  );
}
