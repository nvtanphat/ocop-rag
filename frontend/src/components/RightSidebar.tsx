import { useRef } from "react";
import type { Citation, ReferenceResponse, Source } from "../api/client";
import type { View } from "../app/navigation";
import { sourceTitle } from "../app/sourceLabels";
import { Icon, type IconName } from "./Icon";

const tiles = [
  ["#f3b86a", "#d98521"],
  ["#a8dca0", "#46a05a"],
  ["#9fd3ea", "#3a86b4"],
  ["#f2b18a", "#c4623b"],
  ["#c9b6ea", "#7a56c2"],
];

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
  const track = useRef<HTMLDivElement>(null);
  const scroll = (direction: number) =>
    track.current?.scrollBy({ left: (direction * track.current.clientWidth) / 1.5 });
  const actions: Array<{ cls: string; icon: IconName; title: string; hint: string; run: () => void }> = [
    { cls: "c1", icon: "docs", title: "Tra cứu văn bản", hint: "Pháp luật OCOP", run: () => onNavigate("documents") },
    { cls: "c2", icon: "criteria", title: "Xem tiêu chí", hint: "Đã xác minh", run: () => onNavigate("criteria") },
    { cls: "c3", icon: "store", title: "Tìm sản phẩm", hint: "Nguồn đã duyệt", run: () => onNavigate("products") },
    { cls: "c4", icon: "graph", title: "Đồ thị dẫn chứng", hint: "Truy vết câu trả lời", run: onGraph },
  ];
  return (
    <aside className="cv rightcol" id="rightcol">
      <section className="rcd">
        <h3>
          <Icon name="bolt" />
          Hành động nhanh
        </h3>
        <div className="qa">
          {actions.map((action) => (
            <button key={action.cls} type="button" className={action.cls} onClick={action.run}>
              <span className="ic">
                <Icon name={action.icon} size={30} />
              </span>
              <div>
                <b>{action.title}</b>
                <span>{action.hint}</span>
              </div>
            </button>
          ))}
        </div>
      </section>
      <section className="rcd">
        <h3>
          <Icon name="docs" strokeWidth={1.8} />
          Tài liệu nguồn
          <a href="#documents" onClick={(event) => { event.preventDefault(); onNavigate("documents"); }}>
            Xem thêm →
          </a>
        </h3>
        {loading ? (
          <p className="vstate">Đang tải tài liệu…</p>
        ) : sourceError ? (
          <p className="vstate err" role="alert">{sourceError}</p>
        ) : !sources.length ? (
          <p className="vstate">Chưa có tài liệu trong danh mục.</p>
        ) : (
          <div className="rel">
            {sources.slice(0, 4).map((source) => (
              <button key={source.source_id} type="button" onClick={() => onDocument(source)}>
                <span className="fi k-pdf">PDF</span>
                <div className="t">
                  <b>{sourceTitle(source, source.source_id)}</b>
                  <span className="s">{source.jurisdiction || source.filename}</span>
                </div>
              </button>
            ))}
          </div>
        )}
      </section>
      <section className="rcd grow">
        <h3>
          <Icon name="criteria" strokeWidth={1.8} />
          Sản phẩm OCOP
          <a href="#products" onClick={(event) => { event.preventDefault(); onNavigate("products"); }}>
            Xem thêm →
          </a>
        </h3>
        {loading ? (
          <p className="vstate">Đang tải sản phẩm…</p>
        ) : productError ? (
          <p className="vstate err" role="alert">{productError}</p>
        ) : !products?.items.length ? (
          <div className="vstate">
            <h3>Chưa có dữ liệu xác minh</h3>
            <p>Sản phẩm chỉ hiển thị khi có căn cứ đã được đối soát với nguồn.</p>
          </div>
        ) : (
          <div className="car">
            <button type="button" className="pv" onClick={() => scroll(-1)} aria-label="Trước">
              <Icon name="left" size={16} strokeWidth={2.4} />
            </button>
            <div className="track" ref={track}>
              {products.items.map((item, index) => {
                const [c1, c2] = tiles[index % tiles.length];
                return (
                  <button
                    key={item.id}
                    type="button"
                    className="pc"
                    onClick={() => onCitation(item.citations[0])}
                  >
                    <div className="im tile" style={{ ["--c1" as string]: c1, ["--c2" as string]: c2 }}>
                      <Icon name="box" size={44} />
                    </div>
                    <div className="tx">
                      <b>{item.label}</b>
                      <span className="ver">
                        <Icon name="check" size={12} strokeWidth={2.4} />
                        Nguồn đã xác minh
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
            <button type="button" className="nx" onClick={() => scroll(1)} aria-label="Sau">
              <Icon name="right" size={16} strokeWidth={2.4} />
            </button>
          </div>
        )}
      </section>
    </aside>
  );
}
