import type { Citation, ReferenceResponse, Source } from "../api/client";
import type { View } from "../app/navigation";
import { Icon } from "./Icon";

export function RightSidebar({
  sources,
  products,
  loading,
  sourceError,
  productError,
  onNavigate,
  onDocument,
  onCitation,
  onGraph,
}: {
  sources: Source[];
  products: ReferenceResponse | null;
  loading: boolean;
  sourceError?: string;
  productError?: string;
  onNavigate: (view: View) => void;
  onDocument: (source: Source) => void;
  onCitation: (citation: Citation) => void;
  onGraph: () => void;
}) {
  return (
    <aside className="right-sidebar">
      <section className="side-card panel">
        <h3>
          <Icon name="sparkles" size={18} className="gold-icon" />
          Hành động nhanh
        </h3>
        <div className="quick-actions">
          <button onClick={() => onNavigate("documents")}>
            <span className="quick-icon">
              <Icon name="file" size={23} />
            </span>
            <span>
              <b>Tra cứu văn bản</b>
              <small>Pháp luật OCOP</small>
            </span>
          </button>
          <button onClick={() => onNavigate("criteria")}>
            <span className="quick-icon">
              <Icon name="criteria" size={23} />
            </span>
            <span>
              <b>Xem tiêu chí</b>
              <small>Đã xác minh</small>
            </span>
          </button>
          <button onClick={() => onNavigate("products")}>
            <span className="quick-icon">
              <Icon name="box" size={23} />
            </span>
            <span>
              <b>Tìm sản phẩm</b>
              <small>Nguồn đã duyệt</small>
            </span>
          </button>
          <button onClick={onGraph}>
            <span className="quick-icon">
              <Icon name="graph" size={23} />
            </span>
            <span>
              <b>Đồ thị dẫn chứng</b>
              <small>Truy vết câu trả lời</small>
            </span>
          </button>
        </div>
      </section>
      <section className="side-card panel">
        <h3>
          <Icon name="file" size={17} />
          Tài liệu nguồn
          <button className="text-link" onClick={() => onNavigate("documents")}>
            Xem thêm →
          </button>
        </h3>
        {loading ? (
          <p className="side-note">Đang tải tài liệu…</p>
        ) : sourceError ? (
          <p className="inline-error" role="alert">
            {sourceError}
          </p>
        ) : !sources.length ? (
          <p className="side-note">Chưa có tài liệu trong danh mục.</p>
        ) : (
          <div className="related-documents">
            {sources.slice(0, 4).map((source) => (
              <button key={source.source_id} onClick={() => onDocument(source)}>
                <span className="file-badge">PDF</span>
                <span className="related-copy">
                  <b>{source.document_number || source.filename}</b>
                  <small>{source.jurisdiction || source.filename}</small>
                </span>
                <Icon name="right" size={13} />
              </button>
            ))}
          </div>
        )}
      </section>
      <section className="side-card panel products-card">
        <h3>
          <Icon name="award" size={17} />
          Sản phẩm OCOP
          <button className="text-link" onClick={() => onNavigate("products")}>
            Xem thêm →
          </button>
        </h3>
        {loading ? (
          <p className="side-note">Đang tải sản phẩm…</p>
        ) : productError ? (
          <p className="inline-error" role="alert">
            {productError}
          </p>
        ) : !products?.items.length ? (
          <div className="product-empty">
            <div className="product-empty-art">
              <Icon name="leaf" size={43} />
              <span />
              <i />
            </div>
            <b>Chưa có dữ liệu xác minh</b>
            <p>Sản phẩm sẽ hiển thị khi có căn cứ đã được đối soát.</p>
            <button
              className="subtle-button"
              onClick={() => onNavigate("products")}
            >
              Xem danh mục <Icon name="arrow" size={14} />
            </button>
          </div>
        ) : (
          <div className="verified-products">
            {products.items.slice(0, 3).map((item) => (
              <button
                key={item.id}
                onClick={() => onCitation(item.citations[0])}
              >
                <span className="verified-product-icon">
                  <Icon name="box" size={31} />
                </span>
                <b>{item.label}</b>
                <small>
                  <Icon name="check" size={12} /> Nguồn đã xác minh
                </small>
              </button>
            ))}
          </div>
        )}
      </section>
      <p className="sidebar-footnote">
        <Icon name="leaf" size={13} />
        Tri thức từ nguồn · Tin cậy từ bằng chứng
      </p>
    </aside>
  );
}
