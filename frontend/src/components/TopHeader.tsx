import type { RefObject } from "react";
import type { Health } from "../api/client";
import brand from "../assets/brand.svg";
import { Icon } from "./Icon";

export function TopHeader({
  health,
  loading,
  error,
  onReload,
  search,
  placeholder,
  onSearch,
  onSubmit,
  searchRef,
  dark,
  onTheme,
}: {
  health: Health | null;
  loading: boolean;
  error?: string;
  onReload: () => void;
  search: string;
  placeholder: string;
  onSearch: (value: string) => void;
  onSubmit: () => void;
  searchRef: RefObject<HTMLInputElement | null>;
  dark: boolean;
  onTheme: () => void;
}) {
  const ready = health?.status === "ready";
  const state = error
    ? "Mất kết nối backend"
    : loading
      ? "Đang kết nối…"
      : ready
        ? "Corpus sẵn sàng"
        : health?.status === "updating"
          ? "Đang cập nhật corpus"
          : "Corpus chưa sẵn sàng";
  return (
    <header id="top">
      <img
        className="brand"
        src={brand}
        alt="OCOP RAG — Trợ lý pháp lý và quy chuẩn OCOP Việt Nam"
      />
      <div className="tagline">
        Tri thức OCOP<span>luôn có căn cứ</span>
      </div>
      <form
        className="glass search"
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <Icon name="search" size={18} strokeWidth={2} />
        <input
          ref={searchRef}
          id="gsearch"
          type="text"
          aria-label="Tìm kiếm OCOP"
          placeholder={placeholder}
          autoComplete="off"
          value={search}
          onChange={(event) => onSearch(event.target.value)}
        />
        <kbd>Ctrl K</kbd>
      </form>
      <button
        type="button"
        className="glass theme hov"
        onClick={onTheme}
        title="Đổi giao diện sáng/tối"
        aria-label="Đổi giao diện"
      >
        <Icon name={dark ? "moon" : "sun"} strokeWidth={1.8} />
      </button>
      <span className="avc top-av" title="Phiên tra cứu công khai">
        <Icon name="userSolid" size={26} />
      </span>
      <div
        className="glass hstatus"
        role="status"
        title={
          error ||
          `Backend: ${health?.status || "đang kết nối"} · Corpus: ${health?.corpus_version || "chưa có"}`
        }
      >
        <i className={error ? "off" : ready ? "ok" : ""} />
        <span>{state}</span>
        {health && (
          <small>
            {health.sources_registered} nguồn · {health.pages} trang
          </small>
        )}
        <button
          type="button"
          onClick={onReload}
          disabled={loading}
          aria-label="Tải lại dữ liệu"
          title="Tải lại dữ liệu"
        >
          <Icon name="refresh" size={13} />
        </button>
      </div>
    </header>
  );
}
