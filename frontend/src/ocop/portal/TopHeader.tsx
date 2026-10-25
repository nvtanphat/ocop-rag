import React from 'react'
import { IMAGES } from '../assets'
import type { ActiveView } from './types'

interface TopHeaderProps {
  activeView: ActiveView
  globalSearch: string
  setGlobalSearch: (value: string) => void
  onSearchSubmit: (query: string) => void
  isDark: boolean
  toggleTheme: () => void
  toast: (msg: string) => void
}

export const TopHeader: React.FC<TopHeaderProps> = ({
  activeView,
  globalSearch,
  setGlobalSearch,
  onSearchSubmit,
  isDark,
  toggleTheme,
  toast,
}) => {
  return (
    <header id="top">
      <img className="brand" src={IMAGES.brand} alt="OCOP RAG – Trợ lý pháp lý & Quy chuẩn OCOP Việt Nam" />
      <div className="tagline">
        Tri thức OCOP<span>luôn có căn cứ</span>
      </div>
      <label className="glass search">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#35505e" strokeWidth="2" strokeLinecap="round">
          <circle cx="11" cy="11" r="7" />
          <path d="M16 16l5 5" />
        </svg>
        <input
          id="gsearch"
          type="text"
          placeholder={
            activeView === 'chat'
              ? 'Khám phá tri thức OCOP...'
              : activeView === 'docs'
              ? 'Tìm văn bản pháp quy...'
              : activeView === 'crit'
              ? 'Tìm tiêu chí chấm điểm...'
              : 'Tìm sản phẩm OCOP...'
          }
          autoComplete="off"
          value={globalSearch}
          onChange={(e) => setGlobalSearch(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && globalSearch.trim()) {
              onSearchSubmit(globalSearch)
            }
          }}
        />
        <kbd>Ctrl K</kbd>
      </label>
      <button className="glass theme hov" id="btnTheme" title="Đổi giao diện sáng/tối" aria-label="Đổi giao diện" onClick={toggleTheme}>
        <svg id="icoTheme" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
          {isDark ? (
            <path d="M21 13A9 9 0 1111 3a7 7 0 0010 10z" />
          ) : (
            <>
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2" />
            </>
          )}
        </svg>
      </button>
      <div className="avc top-av" id="btnUser" title="Tài khoản" onClick={() => toast('Tài khoản demo')}>
        <img src={IMAGES.userAvatar} alt="Người dùng" />
      </div>
    </header>
  )
}
