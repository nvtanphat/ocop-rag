import { useEffect, useState } from "react";
import { api, type Source } from "../../api/client";
import {
  docGroups,
  groupColor,
  groupOf,
  normalize,
  sourceBadge,
  sourceTitle,
  type DocGroup,
} from "../../app/sourceLabels";
import { Icon } from "../../components/Icon";
import { Pager } from "../../components/Pager";

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
  const [list, setList] = useState(false);
  const [group, setGroup] = useState<"ALL" | DocGroup>("ALL");
  const [scope, setScope] = useState("");
  const [page, setPage] = useState(1);
  const perPage = list ? 6 : 8;
  const query = normalize(search);
  const matches = (source: Source, ignoreGroup = false) =>
    (ignoreGroup || group === "ALL" || groupOf(source.source_kind) === group) &&
    (!scope || source.jurisdiction === scope) &&
    (!query ||
      normalize(`${source.document_number ?? ""} ${source.filename} ${source.jurisdiction ?? ""}`).includes(query));
  const filtered = sources.filter((source) => matches(source));
  const base = sources.filter((source) => matches(source, true));
  const scopes = Array.from(
    new Set(sources.map((source) => source.jurisdiction).filter((value): value is string => !!value)),
  );
  useEffect(() => setPage(1), [search, group, scope, list]);
  const start = (page - 1) * perPage;
  const rows = filtered.slice(start, start + perPage);

  return (
    <>
      <div className="vhead">
        <div className="vico" style={{ background: "#eef0ed", color: "#2a6fdb" }}>
          <Icon name="pages" size={28} strokeWidth={1.8} />
        </div>
        <div className="vt">
          <h2>Thư viện Văn bản Pháp quy OCOP</h2>
          <p>
            {loaded
              ? `${sources.length} văn bản trong danh mục, đối soát trực tiếp với PDF gốc`
              : "Đang tải danh mục…"}
          </p>
        </div>
        <div className="vtools">
          <label className="fld" style={{ width: 240 }}>
            <Icon name="search" size={16} strokeWidth={2} />
            <input
              id="dQ"
              type="text"
              aria-label="Tìm trong danh sách"
              placeholder="Tìm theo tên, số hiệu..."
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          <select
            className="sel"
            aria-label="Phạm vi áp dụng"
            value={scope}
            onChange={(event) => setScope(event.target.value)}
          >
            <option value="">Phạm vi áp dụng</option>
            {scopes.map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </div>
      </div>
      <div className="chiprow">
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <button type="button" className={`chip ${group === "ALL" ? "on" : ""}`} onClick={() => setGroup("ALL")}>
            Tất cả ({base.length})
          </button>
          {docGroups.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`chip ${group === item.id ? "on" : ""}`}
              onClick={() => setGroup(item.id)}
            >
              <i style={{ background: item.color }} />
              {item.label} ({base.filter((source) => groupOf(source.source_kind) === item.id).length})
            </button>
          ))}
        </div>
        <div className="seg2">
          <button type="button" className={list ? "" : "on"} onClick={() => setList(false)} title="Dạng lưới" aria-label="Dạng lưới">
            <Icon name="gridView" size={16} strokeWidth={2} />
          </button>
          <button type="button" className={list ? "on" : ""} onClick={() => setList(true)} title="Dạng danh sách" aria-label="Dạng danh sách">
            <Icon name="listView" size={16} strokeWidth={2} />
          </button>
        </div>
      </div>
      {loaded && !filtered.length ? (
        <div className="vstate">
          <h3>{search || scope || group !== "ALL" ? "Không có văn bản phù hợp bộ lọc." : "Chưa có tài liệu trong danh mục."}</h3>
          <p>Thử thay đổi từ khoá hoặc tải lại dữ liệu nguồn.</p>
        </div>
      ) : (
        <div className={`dgrid ${list ? "list" : ""}`} id="dGrid">
          {rows.map((source) => (
            <article className="dcard" key={source.source_id}>
              <div className="dtop">
                <div className="dbadge" style={{ background: groupColor(source.source_kind) }}>
                  {sourceBadge(source)}
                </div>
                <div>
                  <b>{sourceTitle(source, source.source_id)}</b>
                  <span>{source.filename}</span>
                </div>
              </div>
              <div className="dmeta">
                <div>
                  <Icon name="globe" size={14} strokeWidth={2} />
                  {source.jurisdiction || "Chưa có thông tin phạm vi"}
                </div>
                <div className="two">
                  <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <Icon name="page" size={14} strokeWidth={2} />
                    {source.page_count} trang đã xử lý
                  </span>
                  <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <Icon name="check" size={14} strokeWidth={2} />
                    {source.source_verification === "verified" ? "Đã xác minh" : "Bản PDF gốc"}
                  </span>
                </div>
              </div>
              <div className="dact">
                <button type="button" className="rd" onClick={() => onOpen(source)}>
                  <Icon name="pages" size={14} strokeWidth={2} />
                  Đọc PDF
                </button>
                <a
                  className="dl"
                  href={api.pdf(source.source_id).split("#")[0]}
                  download={source.filename}
                >
                  <Icon name="download" size={14} strokeWidth={2} />
                  Tải xuống
                </a>
              </div>
            </article>
          ))}
        </div>
      )}
      <Pager total={filtered.length} perPage={perPage} current={page} onGo={setPage} />
    </>
  );
}
