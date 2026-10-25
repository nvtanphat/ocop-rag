import React from 'react'
import type { ActiveView } from './types'

interface LeftSidebarProps {
  activeView: ActiveView
  setActiveView: (view: ActiveView) => void
  clearConvo: () => void
  toast: (msg: string) => void
}

export const LeftSidebar: React.FC<LeftSidebarProps> = ({
  activeView,
  setActiveView,
  clearConvo,
  toast,
}) => {
  return (
    <aside id="side" className="glass">
      <nav id="rail" style={{ display: 'contents' }}>
        <button
          type="button"
          className={`ni ${activeView === 'chat' ? 'on' : ''}`}
          data-view="chat"
          title="Trò chuyện"
          onClick={() => setActiveView('chat')}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round">
            <path d="M4 5h16v11H11l-5 4v-4H4z" />
            <path d="M8 9.5h8M8 12.5h5" strokeLinecap="round" />
          </svg>
          Chat
        </button>
        <button
          type="button"
          className={`ni ${activeView === 'docs' ? 'on' : ''}`}
          data-view="docs"
          title="Thư viện văn bản"
          onClick={() => setActiveView('docs')}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
            <rect x="5" y="3" width="14" height="18" rx="2.5" />
            <path d="M8.5 8h7M8.5 12h7M8.5 16h4" />
          </svg>
          Tài liệu
        </button>
        <button
          type="button"
          className={`ni ${activeView === 'crit' ? 'on' : ''}`}
          data-view="crit"
          title="Bảng tiêu chí"
          onClick={() => setActiveView('crit')}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
            <rect x="5" y="3" width="14" height="18" rx="2.5" />
            <path d="M9 12l2 2 4-4" />
          </svg>
          Tiêu chí
        </button>
        <button
          type="button"
          className={`ni ${activeView === 'prod' ? 'on' : ''}`}
          data-view="prod"
          title="Sản phẩm đạt chuẩn"
          onClick={() => setActiveView('prod')}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="9" r="5" />
            <path d="M9 13.5L7.5 21l4.5-2.5 4.5 2.5L15 13.5" />
          </svg>
          Sản phẩm
        </button>
      </nav>
      <div className="sdiv" />
      <button type="button" className="ni" id="btnHist" title="Lịch sử" onClick={clearConvo}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v5l3 2" />
        </svg>
        Lịch sử
      </button>
      <div className="sp" />
      <button type="button" className="ni sm" id="btnSettings" title="Cài đặt" onClick={() => toast('Cài đặt: Chưa có trang trong bản demo')}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
          <circle cx="12" cy="12" r="3" />
          <path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M18.7 5.3l-2.1 2.1M7.4 16.6l-2.1 2.1" />
        </svg>
      </button>
      <button type="button" className="ni sm" id="btnBell" title="Thông báo" onClick={() => toast('Không có thông báo mới')}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 17V11a6 6 0 0112 0v6l2 2H4zM10 21h4" />
        </svg>
        <i className="badge" />
      </button>
      <button type="button" className="ni sm" id="btnHelp" title="Trợ giúp" onClick={() => toast('Trợ giúp: Hỏi về văn bản, tiêu chí hoặc sản phẩm OCOP')}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
          <circle cx="12" cy="12" r="9" />
          <path d="M9.6 9.5a2.5 2.5 0 114 2c-.9.6-1.6 1-1.6 2M12 17v.2" />
        </svg>
      </button>
    </aside>
  )
}
