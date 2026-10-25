import type { Citation, ReferenceResponse } from "../../api/client";
import { Icon } from "../../components/Icon";

export function ReferenceView({
  data,
  search,
  setSearch,
  loaded,
  onOpen,
  kind,
}: {
  data: ReferenceResponse | null;
  search: string;
  setSearch: (value: string) => void;
  loaded: boolean;
  onOpen: (citation: Citation) => void;
  kind: "criteria" | "products";
}) {
  const filtered =
    data?.items.filter((item) =>
      item.label.toLocaleLowerCase().includes(search.toLocaleLowerCase()),
    ) || [];
  const products = kind === "products";
  return (
    <>
      <div className="view-header">
        <div className={`view-icon ${products ? "gold-tone" : ""}`}>
          <Icon name={products ? "award" : "criteria"} size={28} />
        </div>
        <div className="view-title">
          <h1>{products ? "Sản phẩm OCOP" : "Bảng tiêu chí OCOP"}</h1>
          <p>Thông tin đã xác minh, có căn cứ đối soát từ tài liệu nguồn</p>
        </div>
        <label className="view-search">
          <Icon name="search" size={17} />
          <input
            aria-label="Tìm trong danh sách"
            type="search"
            placeholder={
              products
                ? "Tìm sản phẩm đã xác minh…"
                : "Tìm tiêu chí đã xác minh…"
            }
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
      </div>
      <div className="view-filters">
        <span className="filter-chip active">
          <Icon name="check" size={14} />
          Đã xác minh <span>{data?.items.length || 0}</span>
        </span>
        <span className="reference-corpus">
          {data?.corpus_version
            ? `Corpus: ${data.corpus_version}`
            : "Chưa có phiên bản dữ liệu"}
        </span>
      </div>
      <div className="reference-records">
        {loaded && data && !data.items.length && (
          <div className="empty-state">
            <div className="empty-illustration">
              <Icon name={products ? "box" : "criteria"} size={45} />
              <span>
                <Icon name="leaf" size={22} />
              </span>
            </div>
            <h2>Chưa có dữ liệu xác minh.</h2>
            <p>
              {products
                ? "Sản phẩm sẽ được hiển thị khi có nguồn công nhận đã được đối soát."
                : "Tiêu chí sẽ được hiển thị khi có quy tắc tham chiếu đã được xác minh."}
            </p>
            <small>
              Hệ thống không dùng dữ liệu OCR chưa duyệt để kết luận điểm hoặc
              hạng sao.
            </small>
          </div>
        )}
        {loaded && !!data?.items.length && !filtered.length && (
          <div className="empty-state">
            <Icon name="search" size={38} />
            <h2>Không tìm thấy dữ liệu phù hợp</h2>
            <p>Thử tìm kiếm bằng từ khoá khác.</p>
          </div>
        )}
        {filtered.map((item) => (
          <article className="reference-card" key={item.id}>
            <span className="reference-record-icon">
              <Icon name={products ? "box" : "criteria"} size={24} />
            </span>
            <div>
              <h2>{item.label}</h2>
              <span className="reference-id">{item.id}</span>
              <div className="reference-links">
                {item.citations.map((citation, i) => (
                  <button key={i} onClick={() => onOpen(citation)}>
                    <Icon name="file" size={14} />
                    {citation.source_id} · Trang {citation.pdf_page}
                    <Icon name="external" size={12} />
                  </button>
                ))}
              </div>
            </div>
            <span className="verified-tag">
              <Icon name="check" size={12} />
              Đã xác minh
            </span>
          </article>
        ))}
      </div>
    </>
  );
}
