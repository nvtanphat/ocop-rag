import { useEffect, useRef, useState } from "react";
import { api, EVIDENCE_DPI, evidenceBoxes, type Citation, type Source } from "../../api/client";
import { sourceTitle } from "../../app/sourceLabels";
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
  const [zoom, setZoom] = useState(1.2);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);

  const cited = Array.from(
    new Set([citation.pdf_page, ...(citation.source_spans || []).map((span) => span.pdf_page)]),
  ).sort((a, b) => a - b);
  const total = Math.max(source?.page_count || 0, cited[cited.length - 1], page);
  const imageUrl = api.evidence(citation, page, highlight);
  const box = citation.bbox || citation.table_bbox;
  const title = sourceTitle(source, citation.source_id);

  useEffect(() => {
    setError(false);
    setLoading(true);
  }, [imageUrl]);
  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1800);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const last = source?.page_count || total;
  const goto = (next: number) => next >= 1 && next <= last && setPage(next);
  // Bring the marked region into view: on a long page it may sit far below the top.
  const reveal = (image: HTMLImageElement) => {
    const boxes = highlight ? evidenceBoxes(citation, page) : [];
    if (!boxes.length || !scroller.current) return;
    const scale = image.clientWidth / (image.naturalWidth * 72 / EVIDENCE_DPI);
    const top = Math.min(...boxes.map((b) => b[1])) * scale;
    scroller.current.scrollTop = Math.max(0, image.offsetTop + top - scroller.current.clientHeight / 3);
  };
  const copyCitation = async () => {
    const text = `${title}, trang ${page}${box ? `, BBox [${box.join(", ")}]` : ""}${citation.evidence_unit_id ? `, ${citation.evidence_unit_id}` : ""}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <section className="cv glass pdf" id="pdf" role="dialog" aria-label="Bằng chứng PDF">
      <div className="pdf-head">
        <div className="pdfico">PDF</div>
        <div className="tt">
          <b>{title}</b>
          <span>{source?.filename || citation.source_id}</span>
        </div>
        <div className="ctl">
          <div className="zm">
            <button type="button" disabled={page <= 1} onClick={() => goto(page - 1)} aria-label="Trang trước">
              ‹
            </button>
            <span style={{ minWidth: 84 }}>
              Trang {page}
              {source?.page_count ? ` / ${source.page_count}` : ""}
            </span>
            <button type="button" disabled={page >= last} onClick={() => goto(page + 1)} aria-label="Trang sau">
              ›
            </button>
          </div>
          <div className="zm">
            <button type="button" onClick={() => setZoom((z) => Math.max(0.6, Math.round((z - 0.1) * 10) / 10))} aria-label="Thu nhỏ">
              −
            </button>
            <span>{Math.round(zoom * 100)}%</span>
            <button type="button" onClick={() => setZoom((z) => Math.min(2, Math.round((z + 0.1) * 10) / 10))} aria-label="Phóng to">
              +
            </button>
          </div>
          <button
            type="button"
            className="ib"
            title="Tới trang trích dẫn"
            aria-label="Tới trang trích dẫn"
            onClick={() => setPage(citation.pdf_page)}
          >
            <Icon name="search" size={18} strokeWidth={2} />
          </button>
          <a className="ib" href={api.pdf(citation.source_id, page)} target="_blank" rel="noreferrer" title="Mở PDF gốc" aria-label="Mở PDF gốc">
            <Icon name="expand" size={18} strokeWidth={2} />
          </a>
          <button type="button" className="close" onClick={onClose} title="Đóng PDF (Esc)" aria-label="Đóng PDF">
            <Icon name="close" size={18} strokeWidth={2} />
          </button>
        </div>
      </div>
      <div className="viewer">
        <div className="thumbs" id="thumbs">
          {Array.from({ length: total }, (_, index) => index + 1).map((number) => (
            <button
              key={number}
              type="button"
              className={`th ${number === page ? "on" : ""} ${cited.includes(number) ? "cited" : ""}`}
              onClick={() => setPage(number)}
              aria-label={`Trang ${number}`}
            >
              <em>{number}</em>
            </button>
          ))}
        </div>
        <div className="scroller" id="scroller" ref={scroller}>
          {loading && !error && <div className="loading">Đang mở trang nguồn…</div>}
          {error ? (
            <div className="vstate err" role="alert">
              <h3>Không tải được trang bằng chứng</h3>
              <p>Kiểm tra kết nối, số trang hoặc mã SHA-256 của nguồn.</p>
              <button type="button" onClick={() => setPage(citation.pdf_page)}>
                Về trang trích dẫn
              </button>
            </div>
          ) : (
            <div className="pgimg" style={{ width: `${zoom * 420}px` }}>
              <img
                key={imageUrl}
                src={imageUrl}
                alt={`Trang ${page} của ${citation.source_id}, vùng bằng chứng được đánh dấu`}
                onLoad={(event) => {
                  setLoading(false);
                  reveal(event.currentTarget);
                }}
                onError={() => {
                  setError(true);
                  setLoading(false);
                }}
              />
            </div>
          )}
        </div>
        <div className="tools">
          <button
            type="button"
            className={highlight ? "on" : ""}
            onClick={() => setHighlight(!highlight)}
            title="Hiện/ẩn vị trí trích dẫn"
            aria-pressed={highlight}
          >
            <Icon name="region" size={18} strokeWidth={2} />
          </button>
          <button type="button" onClick={() => void copyCitation()} title="Sao chép trích dẫn">
            <Icon name={copied ? "check" : "copy"} size={18} strokeWidth={2} />
          </button>
          <button type="button" onClick={() => setZoom(1.2)} title="Về cỡ 120%">
            <Icon name="fit" size={18} strokeWidth={2} />
          </button>
        </div>
      </div>
      <div className="pdf-foot">
        <button type="button" className={`pill ${highlight ? "" : "off"}`} onClick={() => setHighlight(!highlight)}>
          <Icon name="hlDot" size={16} strokeWidth={2} />
          Vị trí trích dẫn
        </button>
        <span className="pill g">
          <Icon name="page" size={15} strokeWidth={2} />
          Trang {page}
        </span>
        <span className="bb" title={`${citation.evidence_unit_id || ""} ${citation.source_sha256 || ""}`.trim()}>
          {box ? `BBox: [${box.join(", ")}]` : "Không chọn vùng cụ thể"}
        </span>
        <a className="full" href={api.pdf(citation.source_id, page)} target="_blank" rel="noreferrer">
          <Icon name="open" size={15} strokeWidth={2} />
          Mở PDF gốc
        </a>
      </div>
    </section>
  );
}
