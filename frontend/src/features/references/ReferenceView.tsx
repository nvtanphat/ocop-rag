import { useEffect, useState } from "react";
import type { Citation, ReferenceItem, ReferenceResponse, Source } from "../../api/client";
import { normalize, sourceTitle } from "../../app/sourceLabels";
import { Icon } from "../../components/Icon";
import { Pager } from "../../components/Pager";

const tiles = [
  ["#f3b86a", "#d98521"],
  ["#a8dca0", "#46a05a"],
  ["#9fd3ea", "#3a86b4"],
  ["#f2b18a", "#c4623b"],
  ["#c9b6ea", "#7a56c2"],
];

export function ReferenceView({
  data,
  sources,
  search,
  setSearch,
  loaded,
  onOpen,
  kind,
}: {
  data: ReferenceResponse | null;
  sources: Source[];
  search: string;
  setSearch: (value: string) => void;
  loaded: boolean;
  onOpen: (citation: Citation) => void;
  kind: "criteria" | "products";
}) {
  const products = kind === "products";
  const [doc, setDoc] = useState("");
  const [group, setGroup] = useState("");
  const [perPage, setPerPage] = useState(products ? 20 : 25);
  const [table, setTable] = useState(false);
  const [page, setPage] = useState(1);
  const docName = (id: string) => sourceTitle(sources.find((s) => s.source_id === id), id);
  const query = normalize(search);
  const items = data?.items ?? [];
  const docs = Array.from(new Set(items.flatMap((item) => item.citations.map((c) => c.source_id))));
  const inDoc = items.filter((item) => !doc || item.citations.some((c) => c.source_id === doc));
  const groups = Array.from(new Set(inDoc.map((item) => item.group).filter((g): g is string => !!g)));
  const filtered = inDoc.filter(
    (item) =>
      (!group || item.group === group) &&
      (!query || normalize(`${item.label} ${item.group ?? ""}`).includes(query)),
  );
  useEffect(() => setGroup(""), [doc]);
  useEffect(() => setPage(1), [search, doc, group, perPage, table]);
  const start = (page - 1) * perPage;
  const rows = filtered.slice(start, start + perPage);

  const exportCsv = () => {
    const cell = (value: string | number) => `"${String(value).replace(/"/g, '""')}"`;
    const csv =
      (products ? "\uFEFFSTT,Nội dung,Văn bản,Trang\n" : "\uFEFFSTT,Bộ sản phẩm,Tiêu chí,Điểm tối đa,Văn bản,Trang\n") +
      filtered
        .map((item, index) =>
          [
            index + 1,
            ...(products ? [item.label] : [item.group ?? "", item.label, item.points ?? ""]),
            Array.from(new Set(item.citations.map((c) => docName(c.source_id)))).join("; "),
            item.citations.map((c) => c.pdf_page).join("; "),
          ]
            .map(cell)
            .join(","),
        )
        .join("\n");
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    link.download = products ? "san-pham-ocop.csv" : "tieu-chi-ocop.csv";
    link.click();
    URL.revokeObjectURL(link.href);
  };

  const links = (item: ReferenceItem) =>
    item.citations.map((citation, index) => (
      <button key={index} type="button" className="xem" onClick={() => onOpen(citation)}>
        {docName(citation.source_id)} · tr.{citation.pdf_page}
        <Icon name="external" size={12} strokeWidth={2} />
      </button>
    ));

  return (
    <>
      <div className="vhead">
        <div
          className="vico"
          style={products ? { background: "#d9f1e5", color: "#2f6b52" } : { background: "#fff0d6", color: "#e8930c" }}
        >
          <Icon name={products ? "award" : "criteria"} size={28} strokeWidth={1.8} />
        </div>
        <div className="vt">
          <h2>{products ? "Danh mục Sản phẩm Đạt chuẩn OCOP" : "Bảng Tiêu chí Chấm điểm OCOP"}</h2>
          <p>
            {products
              ? "Sản phẩm có căn cứ đã được đối soát với văn bản công nhận"
              : "Tiêu chí kỹ thuật đã xác minh, kèm căn cứ trên văn bản gốc"}
            {data?.corpus_version ? ` · Corpus ${data.corpus_version}` : ""}
          </p>
        </div>
      </div>
      <div className="crow">
        <label className="fld">
          <Icon name="search" size={16} strokeWidth={2} />
          <input
            type="text"
            aria-label="Tìm trong danh sách"
            placeholder={products ? "Tìm tên sản phẩm..." : "Tìm kiếm nội dung tiêu chí..."}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <select
          className="sel"
          style={{ width: 300 }}
          aria-label="Văn bản"
          value={doc}
          onChange={(event) => setDoc(event.target.value)}
        >
          <option value="">Tất cả văn bản</option>
          {docs.map((id) => (
            <option key={id} value={id}>
              {docName(id)}
            </option>
          ))}
        </select>
        {!products && (
          <select
            className="sel"
            style={{ width: 260 }}
            aria-label="Bộ sản phẩm"
            value={group}
            onChange={(event) => setGroup(event.target.value)}
          >
            <option value="">Tất cả bộ sản phẩm</option>
            {groups.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        )}
        <button type="button" className="btn-b" onClick={exportCsv} disabled={!filtered.length}>
          <Icon name="download" size={16} strokeWidth={2} />
          Xuất danh sách
        </button>
      </div>
      <div className="cinfo">
        <span className="chip green">
          Tổng {filtered.length} {products ? "sản phẩm" : "tiêu chí"}
        </span>
        <span>
          Hiển thị {rows.length} / {filtered.length} kết quả
        </span>
        <span style={{ marginLeft: "auto" }}>Hiển thị</span>
        <select
          className="sel"
          aria-label="Số dòng mỗi trang"
          value={perPage}
          onChange={(event) => setPerPage(Number(event.target.value))}
        >
          {(products ? [8, 20, 40] : [25, 50, 100]).map((n) => (
            <option key={n}>{n}</option>
          ))}
        </select>
        <span>/ trang</span>
        {products && (
          <div className="seg2" style={{ marginLeft: 12 }}>
            <button type="button" className={table ? "" : "on"} onClick={() => setTable(false)}>
              <Icon name="gridView" size={15} strokeWidth={2} />
              Dạng lưới
            </button>
            <button type="button" className={table ? "on" : ""} onClick={() => setTable(true)}>
              <Icon name="listView" size={15} strokeWidth={2} />
              Dạng bảng
            </button>
          </div>
        )}
      </div>
      {loaded && data && !items.length ? (
        <div className="vstate">
          <h3>Chưa có dữ liệu xác minh.</h3>
          <p>
            {products
              ? "Sản phẩm sẽ được hiển thị khi có nguồn công nhận đã được đối soát."
              : "Tiêu chí sẽ được hiển thị khi có quy tắc tham chiếu đã được xác minh."}
          </p>
          <small>Hệ thống không dùng dữ liệu OCR chưa duyệt để kết luận điểm hoặc hạng sao.</small>
        </div>
      ) : loaded && !filtered.length ? (
        <div className="vstate">
          <h3>Không có kết quả phù hợp bộ lọc.</h3>
          <p>Thử tìm kiếm bằng từ khoá khác.</p>
        </div>
      ) : products && !table ? (
        <div className="pgrid" id="pGrid">
          {rows.map((item, index) => {
            const [c1, c2] = tiles[(start + index) % tiles.length];
            return (
              <article className="pcard" key={item.id}>
                <div className="pimg tile" style={{ background: `linear-gradient(150deg,${c1},${c2})` }}>
                  <Icon name="box" size={54} strokeWidth={1.6} />
                </div>
                <div className="pbody">
                  <b>{item.label}</b>
                  <span className="ok-tag">
                    <Icon name="check" size={12} strokeWidth={2.4} />
                    Đã xác minh
                  </span>
                  <div className="links">{links(item)}</div>
                </div>
              </article>
            );
          })}
        </div>
      ) : products ? (
        <div className="pgrid table">
          <table>
            <thead>
              <tr>
                <th>Sản phẩm</th>
                <th>Căn cứ</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((item) => (
                <tr key={item.id}>
                  <td>
                    <b>{item.label}</b>
                  </td>
                  <td>{links(item)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="tbl2" id="cWrap">
          <table>
            <thead>
              <tr>
                <th style={{ width: 60 }}>#</th>
                <th style={{ width: 200 }}>Bộ sản phẩm</th>
                <th>Tiêu chí</th>
                <th style={{ width: 90 }}>Điểm tối đa</th>
                <th style={{ width: 260 }}>Căn cứ văn bản</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((item, index) => (
                <tr key={item.id}>
                  <td className="n">{start + index + 1}</td>
                  <td>{item.group}</td>
                  <td className="lbl">{item.label}</td>
                  <td className="n">{item.points ?? "—"}</td>
                  <td>{links(item)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pager total={filtered.length} perPage={perPage} current={page} onGo={setPage} />
    </>
  );
}
