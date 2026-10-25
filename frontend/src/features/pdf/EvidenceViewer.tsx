import { useEffect, useState } from "react";
import { api, type Citation, type Source } from "../../api/client";
import { Icon } from "../../components/Icon";

export function EvidenceViewer({
  citation,
  source,
  onClose,
}: {
  citation: Citation;
  source?: Source;
  onClose: () => void;
}) {
  const [page, setPage] = useState(citation.pdf_page);
  const [highlight, setHighlight] = useState(true);
  const [zoom, setZoom] = useState(1);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [provenance, setProvenance] = useState(false);
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [onClose]);
  const imageUrl = api.evidence(citation, page, highlight);
  useEffect(() => {
    setError(false);
    setLoading(true);
  }, [imageUrl]);
  const pages = Array.from(
    new Set([
      citation.pdf_page,
      ...(citation.source_spans || []).map((span) => span.pdf_page),
    ]),
  ).sort((a, b) => a - b);
  return (
    <section
      role="dialog"
      aria-label="Bằng chứng PDF"
      className="evidence-viewer panel"
    >
      <header className="detail-header">
        <span className="file-badge large">PDF</span>
        <div className="detail-title">
          <h2>{source?.document_number || citation.source_id}</h2>
          <p>{source?.filename || citation.source_id}</p>
        </div>
        <button
          className="icon-button"
          onClick={onClose}
          aria-label="Đóng PDF"
          title="Đóng PDF (Esc)"
        >
          <Icon name="close" />
        </button>
      </header>
      <div className="evidence-toolbar">
        <div className="page-navigation">
          <button
            className="icon-button"
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
            aria-label="Trang trước"
          >
            <Icon name="left" size={18} />
          </button>
          <span>
            Trang <b>{page}</b>
          </span>
          <button
            className="icon-button"
            onClick={() => setPage((p) => p + 1)}
            aria-label="Trang sau"
          >
            <Icon name="right" size={18} />
          </button>
        </div>
        <div className="zoom-controls">
          <button
            className="icon-button"
            onClick={() => setZoom((z) => Math.max(0.6, z - 0.1))}
            aria-label="Thu nhỏ"
          >
            <Icon name="zoomOut" size={17} />
          </button>
          <button
            className="zoom-label"
            onClick={() => setZoom(1)}
            title="Vừa trang"
          >
            {Math.round(zoom * 100)}%
          </button>
          <button
            className="icon-button"
            onClick={() => setZoom((z) => Math.min(2, z + 0.1))}
            aria-label="Phóng to"
          >
            <Icon name="zoomIn" size={17} />
          </button>
        </div>
      </div>
      {pages.length > 1 && (
        <div className="cited-page-tabs" aria-label="Các trang được trích dẫn">
          {pages.map((number) => (
            <button
              key={number}
              className={number === page ? "active" : ""}
              onClick={() => setPage(number)}
            >
              Trang {number}
            </button>
          ))}
        </div>
      )}
      <div className="evidence-scroll">
        {loading && !error && (
          <div className="image-loading" role="status">
            <span className="loading-ring" />
            Đang mở trang nguồn…
          </div>
        )}
        {error && (
          <div role="alert" className="image-error">
            <Icon name="info" size={28} />
            <h3>Không tải được trang bằng chứng</h3>
            <p>Kiểm tra kết nối, số trang hoặc mã SHA-256 của nguồn.</p>
            <button onClick={() => setPage(citation.pdf_page)}>
              Về trang trích dẫn
            </button>
          </div>
        )}
        <img
          key={imageUrl}
          src={imageUrl}
          style={{ width: `${zoom * 100}%` }}
          alt={`Trang ${page} của ${citation.source_id}, vùng bằng chứng được đánh dấu`}
          onLoad={() => setLoading(false)}
          onError={() => {
            setError(true);
            setLoading(false);
          }}
        />
      </div>
      <div className="evidence-footer">
        <label className="highlight-switch">
          <input
            type="checkbox"
            checked={highlight}
            onChange={(event) => setHighlight(event.target.checked)}
          />
          <span className="highlight-dot" />
          Vùng trích dẫn
        </label>
        <a
          className="original-pdf"
          href={api.pdf(citation.source_id, page)}
          target="_blank"
          rel="noreferrer"
        >
          Mở PDF gốc <Icon name="external" size={14} />
        </a>
      </div>
      <div className="provenance">
        <button
          className="provenance-toggle"
          onClick={() => setProvenance(!provenance)}
          aria-expanded={provenance}
        >
          <Icon name="info" size={14} />
          Thông tin bằng chứng
          <Icon name={provenance ? "left" : "right"} size={13} />
        </button>
        {provenance && (
          <dl>
            <dt>Nguồn</dt>
            <dd>{citation.source_id}</dd>
            <dt>Evidence ID</dt>
            <dd>
              {citation.evidence_unit_id || "Không chọn bằng chứng cụ thể"}
            </dd>
            <dt>BBox</dt>
            <dd>
              {JSON.stringify(citation.bbox || citation.table_bbox || null)}
            </dd>
            <dt>SHA-256</dt>
            <dd>{citation.source_sha256 || "Chưa có trong trích dẫn"}</dd>
          </dl>
        )}
      </div>
    </section>
  );
}
