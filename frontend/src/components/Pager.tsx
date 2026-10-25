import { Icon } from "./Icon";

export function Pager({
  total,
  perPage,
  current,
  onGo,
}: {
  total: number;
  perPage: number;
  current: number;
  onGo: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / perPage));
  if (pages <= 1) return <div className="pager" />;
  const shown: Array<number | "…"> = [];
  for (let page = 1; page <= pages; page++) {
    if (page === 1 || page === pages || Math.abs(page - current) <= 1) shown.push(page);
    else if (shown[shown.length - 1] !== "…") shown.push("…");
  }
  return (
    <div className="pager">
      <button type="button" disabled={current <= 1} onClick={() => onGo(current - 1)} aria-label="Trang trước">
        <Icon name="left" size={14} />
      </button>
      {shown.map((page, index) =>
        page === "…" ? (
          <span key={`gap-${index}`}>…</span>
        ) : (
          <button key={page} type="button" className={page === current ? "on" : ""} onClick={() => onGo(page)}>
            {page}
          </button>
        ),
      )}
      <button type="button" disabled={current >= pages} onClick={() => onGo(current + 1)} aria-label="Trang sau">
        <Icon name="right" size={14} />
      </button>
    </div>
  );
}
