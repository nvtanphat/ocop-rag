import { useState } from "react";
import type { Source } from "../../api/client";
import { Icon } from "../../components/Icon";

export function DocumentsView({
  sources,
  search,
  setSearch,
  loaded,
  onOpen,
}: {
  sources: Source[];
  search: string;
  setSearch: (value: string) => void;
  loaded: boolean;
  onOpen: (source: Source) => void;
}) {
  const [layout, setLayout] = useState<"grid" | "list">("grid");
  const [kind, setKind] = useState("");
  const filtered = sources.filter(
    (s) =>
      (!kind || s.source_kind === kind) &&
      `${s.document_number} ${s.filename} ${s.jurisdiction}`
        .toLocaleLowerCase()
        .includes(search.toLocaleLowerCase()),
  );
  const kinds = Array.from(
    new Set(
      sources
        .map((source) => source.source_kind)
        .filter((value): value is string => !!value),
    ),
  );
  return (
    <>
      <div className="view-header">
        <div className="view-icon">
          <Icon name="file" size={28} />
        </div>
        <div className="view-title">
          <h1>Thư viện văn bản</h1>
          <p>Tra cứu và đối soát tài liệu OCOP từ PDF gốc</p>
        </div>
        <label className="view-search">
          <Icon name="search" size={17} />
          <input
            aria-label="Tìm trong danh sách"
            type="search"
            placeholder="Tìm tên, số hiệu văn bản…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
      </div>
      <div className="view-filters">
        <button
          className={`filter-chip ${!kind ? "active" : ""}`}
          onClick={() => setKind("")}
        >
          Tất cả văn bản <span>{sources.length}</span>
        </button>
        <label className="kind-filter">
          <span className="sr-only">Loại nguồn</span>
          <select
            value={kind}
            onChange={(event) => setKind(event.target.value)}
          >
            <option value="">Mọi loại nguồn</option>
            {kinds.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <div className="layout-switch">
          <button
            className={layout === "grid" ? "active" : ""}
            onClick={() => setLayout("grid")}
            aria-label="Xem dạng thẻ"
          >
            <Icon name="grid" size={17} />
          </button>
          <button
            className={layout === "list" ? "active" : ""}
            onClick={() => setLayout("list")}
            aria-label="Xem dạng danh sách"
          >
            <Icon name="list" size={18} />
          </button>
        </div>
      </div>
      <div
        className={`document-grid ${layout === "list" ? "document-list" : ""}`}
      >
        {loaded && !filtered.length && (
          <div className="empty-state">
            <Icon name="search" size={38} />
            <h2>
              {search || kind
                ? "Không tìm thấy tài liệu phù hợp"
                : "Chưa có tài liệu trong danh mục"}
            </h2>
            <p>Thử thay đổi từ khoá hoặc tải lại dữ liệu nguồn.</p>
          </div>
        )}
        {filtered.map((source) => (
          <article className="document-card" key={source.source_id}>
            <div className="document-top">
              <span className="document-badge">
                <Icon name="file" size={24} />
                <small>PDF</small>
              </span>
              <div>
                <h2>{source.document_number || source.filename}</h2>
                <p>{source.filename}</p>
              </div>
            </div>
            <div className="document-meta">
              <span>
                <Icon name="book" size={15} />
                {source.jurisdiction || "Chưa có thông tin phạm vi"}
              </span>
              <span>
                <Icon name="file" size={15} />
                {source.page_count} trang đã xử lý
              </span>
            </div>
            <div className="document-status">
              <span className="small-dot" />
              {source.source_verification === "verified"
                ? "Nguồn đã xác minh"
                : "PDF gốc trong danh mục"}
            </div>
            <button className="read-document" onClick={() => onOpen(source)}>
              <Icon name="book" size={16} />
              Đọc văn bản
              <Icon name="arrow" size={15} />
            </button>
          </article>
        ))}
      </div>
      <div className="view-footer">
        <span>
          {loaded ? `${filtered.length} văn bản` : "Đang tải danh mục…"}
        </span>
        <Icon name="leaf" size={13} />
        <span>Đối soát trực tiếp với nguồn gốc</span>
      </div>
    </>
  );
}
