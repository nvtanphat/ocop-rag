import type { Citation } from "../../api/client";
import type { Message } from "../chat/ChatView";
import { Icon } from "../../components/Icon";

export function EvidenceGraph({
  message,
  onOpen,
  onClose,
}: {
  message: Message | null;
  onOpen: (citation: Citation) => void;
  onClose: () => void;
}) {
  const citations = message?.answer?.citations || [];
  return (
    <section
      className="evidence-graph panel"
      role="dialog"
      aria-label="Đồ thị dẫn chứng"
    >
      <header className="detail-header">
        <span className="detail-icon">
          <Icon name="graph" size={21} />
        </span>
        <div>
          <h2>Đồ thị dẫn chứng</h2>
          <p>Liên kết trực tiếp từ câu trả lời tới nguồn</p>
        </div>
        <button
          className="icon-button"
          onClick={onClose}
          aria-label="Đóng đồ thị"
        >
          <Icon name="close" />
        </button>
      </header>
      {!citations.length ? (
        <div className="empty-state">
          <Icon name="graph" size={46} />
          <h2>Chưa có dẫn chứng để hiển thị</h2>
          <p>
            Đặt câu hỏi và chọn một câu trả lời có citation để xem liên kết
            nguồn.
          </p>
        </div>
      ) : (
        <div className="graph-content">
          <div className="graph-question">
            <Icon name="chat" size={21} />
            <span>{message?.question}</span>
          </div>
          <div className="graph-connector">
            <span />
            Trích dẫn từ câu trả lời
            <span />
          </div>
          <div className="graph-nodes">
            {citations.map((citation, i) => (
              <button
                className="graph-node"
                key={i}
                onClick={() => onOpen(citation)}
              >
                <span className="graph-node-heading">
                  <span className="file-badge">PDF</span>
                  <b>
                    [S{i + 1}] {citation.source_id}
                  </b>
                  <Icon name="external" size={14} />
                </span>
                <span>
                  Trang {citation.pdf_page} ·{" "}
                  {citation.review_status === "verified"
                    ? "Đã xác minh"
                    : "Chưa được duyệt"}
                </span>
                <small>
                  {citation.evidence_unit_id || "Chưa có mã bằng chứng"}
                </small>
              </button>
            ))}
          </div>
          <p className="graph-note">
            <Icon name="info" size={15} />
            Sơ đồ chỉ thể hiện các liên kết trích dẫn thực tế, không suy diễn
            quan hệ pháp lý giữa các văn bản.
          </p>
        </div>
      )}
    </section>
  );
}
