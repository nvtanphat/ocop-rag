import { useState } from 'react'
import type { Health } from './api'

interface TopHeaderProps {
  health: Health | null
  onQuickSearch?: (query: string) => void
  onLogoClick?: () => void
}

export default function TopHeader({ health, onQuickSearch, onLogoClick }: TopHeaderProps) {
  const [searchTerm, setSearchTerm] = useState('')
  const isOnline = Boolean(health?.sources_registered !== undefined || health?.status === 'ready' || health?.status === 'not_ready')

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && searchTerm.trim() && onQuickSearch) {
      onQuickSearch(searchTerm.trim())
      setSearchTerm('')
    }
  }

  return (
    <>
      {/* Brand Logo & Title */}
      <div
        onClick={onLogoClick}
        style={{
          position: 'absolute',
          left: '125px',
          top: '14px',
          whiteSpace: 'nowrap',
          fontSize: '38px',
          fontWeight: 700,
          letterSpacing: '1px',
          lineHeight: '46px',
          color: '#1f55b8',
          textShadow: '0 2px 0 rgba(255,255,255,0.5)',
          cursor: 'pointer',
          zIndex: 30,
          userSelect: 'none'
        }}
      >
        OCOP <span style={{ color: '#1f55b8' }}>RAG</span>
      </div>

      <div
        style={{
          position: 'absolute',
          left: '126px',
          top: '58px',
          fontSize: '12px',
          fontWeight: 500,
          color: '#17356e',
          zIndex: 30,
          userSelect: 'none'
        }}
      >
        Trợ lý pháp lý &amp; Quy chuẩn OCOP Việt Nam
      </div>

      {/* Global Search Input */}
      <div
        style={{
          position: 'absolute',
          left: '952px',
          top: '21px',
          width: '302px',
          height: '42px',
          borderRadius: '21px',
          background: 'rgba(255, 255, 255, 0.8)',
          backdropFilter: 'blur(12px)',
          boxShadow: '0 4px 14px rgba(27,63,110,0.14)',
          display: 'flex',
          alignItems: 'center',
          padding: '0 14px',
          boxSizing: 'border-box',
          gap: '12px',
          fontSize: '12.5px',
          color: '#6b7b8d',
          zIndex: 30
        }}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#4a5a6e" strokeWidth="2" strokeLinecap="round">
          <circle cx="11" cy="11" r="7" />
          <path d="M16 16l5 5" />
        </svg>
        <input
          type="text"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Khám phá tri thức OCOP..."
          style={{
            flex: 1,
            border: 'none',
            background: 'transparent',
            outline: 'none',
            fontSize: '12.5px',
            color: '#17356e'
          }}
        />
        <span
          style={{
            background: '#e3ebf3',
            borderRadius: '8px',
            padding: '3px 9px',
            fontSize: '11.5px',
            color: '#4a5a6e',
            flexShrink: 0,
            userSelect: 'none'
          }}
        >
          Ctrl K
        </span>
      </div>

      {/* Sun / Theme Button */}
      <button
        style={{
          position: 'absolute',
          left: '1270px',
          top: '22px',
          width: '42px',
          height: '42px',
          borderRadius: '50%',
          background: 'rgba(255, 255, 255, 0.8)',
          boxShadow: '0 4px 14px rgba(27,63,110,0.14)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          border: 'none',
          cursor: 'pointer',
          zIndex: 30,
          transition: 'transform 0.15s ease'
        }}
        title="Giao diện OCOP"
        onMouseEnter={(e) => (e.currentTarget.style.transform = 'scale(1.08)')}
        onMouseLeave={(e) => (e.currentTarget.style.transform = 'scale(1)')}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#1f55b8" strokeWidth="2" strokeLinecap="round">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.500 1.500M17.500 17.500L19 19M5 19l1.500-1.500M17.500 6.500L19 5" />
        </svg>
      </button>

      {/* API Status Pill */}
      <div
        style={{
          position: 'absolute',
          left: '1322px',
          top: '18px',
          width: '134px',
          height: '46px',
          borderRadius: '23px',
          background: 'rgba(255, 255, 255, 0.67)',
          backdropFilter: 'blur(12px)',
          boxShadow: '0 4px 14px rgba(27,63,110,0.14)',
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          paddingLeft: '14px',
          boxSizing: 'border-box',
          zIndex: 30,
          userSelect: 'none'
        }}
        title={isOnline ? 'Máy chủ API OCOP đang hoạt động' : 'Đang kết nối API...'}
      >
        <div
          style={{
            width: '16px',
            height: '16px',
            borderRadius: '50%',
            background: isOnline ? '#12a05c' : '#ef4a55',
            boxShadow: isOnline ? '0 0 0 4px rgba(18,160,92,0.2)' : '0 0 0 4px rgba(239,74,85,0.2)',
            transition: 'background 0.3s'
          }}
        />
        <div style={{ fontSize: '11px', lineHeight: '15px', color: '#4a5a6e' }}>
          <b style={{ fontWeight: 500, fontSize: '12.5px', color: '#17356e' }}>
            {isOnline ? 'API Online' : 'Offline'}
          </b>
          <br />
          {isOnline ? 'Dữ liệu sẵn sàng' : 'Chờ khởi động'}
        </div>
      </div>

      {/* User Avatar */}
      <img
        src="/ocop_assets/c_av2.png"
        alt="Avatar"
        style={{
          position: 'absolute',
          left: '1472px',
          top: '20px',
          width: '40px',
          height: '40px',
          borderRadius: '50%',
          boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
          zIndex: 30,
          objectFit: 'cover',
          userSelect: 'none'
        }}
      />
    </>
  )
}
