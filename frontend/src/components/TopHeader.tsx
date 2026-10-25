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
    <header className="workspace-header">
      <a className="brand" href="#" aria-label="OCOP RAG">
        <img
          src={brand}
          alt="OCOP RAG — Trợ lý pháp lý và quy chuẩn OCOP Việt Nam"
        />
      </a>
      <div className="tagline">
        Tri thức OCOP<span>luôn có căn cứ</span>
      </div>
      <div className="header-actions">
        <form
          className="global-search"
          role="search"
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit();
          }}
        >
          <Icon name="search" size={17} />
          <input
            ref={searchRef}
            aria-label="Tìm kiếm OCOP"
            placeholder="Khám phá tri thức OCOP…"
            value={search}
            onChange={(event) => onSearch(event.target.value)}
          />
          <kbd>Ctrl K</kbd>
        </form>
        <button
          className="header-icon"
          onClick={onTheme}
          aria-label="Đổi giao diện"
          title={dark ? "Giao diện sáng" : "Giao diện tối"}
        >
          <Icon name={dark ? "moon" : "sun"} />
        </button>
        <span className="profile-icon" title="Phiên tra cứu công khai">
          <Icon name="user" size={21} />
        </span>
      </div>
      <div
        className="header-status"
        role="status"
        title={
          error ||
          `Backend: ${health?.status || "đang kết nối"} · Corpus: ${health?.corpus_version || "chưa có"}`
        }
      >
        <span
          className={`status-dot ${error ? "offline" : ready ? "ready" : "pending"}`}
        />
        <span>{state}</span>
        {health && (
          <span className="source-count">
            {health.sources_registered} nguồn · {health.pages} trang
          </span>
        )}
        <button
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
