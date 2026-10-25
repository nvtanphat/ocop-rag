import type { Section } from './api'

interface LeftRailProps {
  currentSection: Section
  onSelectSection: (section: Section) => void
}

const PATHS = {
  chat: 'M4 5h16v11H9l-5 4z',
  doc: 'M7 3h7l4 4v14H7zM14 3v4h4M10 12h5M10 16h5',
  check: 'M5 3h14v18H5zM8.5 12l2.5 2.5 4.5-5',
  award: 'M12 3a6 6 0 100 12 6 6 0 000-12zM9 14l-2 7 5-3 5 3-2-7',
  gear: 'M15.200 12a3.200 3.200 0 11-6.400 0 3.200 3.200 0 016.400 0zM12 2.500v3M12 18.500v3M2.500 12h3M18.500 12h3M5.300 5.300l2.100 2.100M16.600 16.600l2.100 2.100M5.300 18.700l2.100-2.100M16.600 7.400l2.100-2.100',
  bell: 'M6 17V11a6 6 0 0112 0v6l2 2H4zM10 21h4',
  help: 'M21 12a9 9 0 11-18 0 9 9 0 0118 0zM9.500 9.500a2.500 2.500 0 115 0c0 1.700-2.500 2-2.500 4M12 17h.01'
}

export default function LeftRail({ currentSection, onSelectSection }: LeftRailProps) {
  const navTabs: Array<{ id: Section; key: keyof typeof PATHS; cy: number; title: string }> = [
    { id: 'chat', key: 'chat', cy: 142, title: '1 · Trợ lý Tra cứu OCOP' },
    { id: 'documents', key: 'doc', cy: 221, title: '2 · Thư viện Văn bản Pháp quy' },
    { id: 'criteria', key: 'check', cy: 288, title: '3 · Bảng Tiêu chí Chấm điểm' },
    { id: 'recognitions', key: 'award', cy: 355, title: '4 · Danh mục Sản phẩm Đạt chuẩn' }
  ]

  const toolTabs: Array<{ key: keyof typeof PATHS; cy: number; title: string }> = [
    { key: 'gear', cy: 753, title: 'Cài đặt hệ thống' },
    { key: 'bell', cy: 799, title: 'Thông báo quy chuẩn' },
    { key: 'help', cy: 845, title: 'Trợ giúp & Hướng dẫn' }
  ]

  return (
    <>
      {/* Top search icon button */}
      <button
        style={{
          position: 'absolute',
          left: '22px',
          top: '20px',
          width: '44px',
          height: '44px',
          borderRadius: '50%',
          background: '#ffffffee',
          boxShadow: '0 4px 12px rgba(0,0,0,0.12)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          border: 'none',
          cursor: 'pointer',
          zIndex: 30,
          transition: 'transform 0.15s ease'
        }}
        title="Tìm kiếm nhanh OCOP"
        onClick={() => onSelectSection('chat')}
        onMouseEnter={(e) => (e.currentTarget.style.transform = 'scale(1.08)')}
        onMouseLeave={(e) => (e.currentTarget.style.transform = 'scale(1)')}
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#0d8a5c" strokeWidth="2.4" strokeLinecap="round">
          <circle cx="11" cy="11" r="7" />
          <path d="M16 16l5 5" />
        </svg>
      </button>

      {/* Upper Navigation Dock Pill */}
      <div
        style={{
          position: 'absolute',
          left: '18px',
          top: '188px',
          width: '54px',
          height: '200px',
          borderRadius: '27px',
          background: '#ffffffaa',
          border: '1px solid #fff',
          boxShadow: '0 8px 22px rgba(27,63,110,0.14)',
          pointerEvents: 'none',
          zIndex: 10
        }}
      />

      {/* Upper Navigation Icons */}
      {navTabs.map((tab, i) => {
        const isActive = currentSection === tab.id
        const sz = isActive ? (i === 0 ? 52 : 46) : 36
        const x = 45 - sz / 2
        const y = tab.cy - sz / 2

        return (
          <button
            key={tab.id}
            title={tab.title}
            onClick={() => onSelectSection(tab.id)}
            style={{
              position: 'absolute',
              left: `${x}px`,
              top: `${y}px`,
              width: `${sz}px`,
              height: `${sz}px`,
              borderRadius: '50%',
              background: isActive ? 'linear-gradient(180deg,#3f9cff,#1f6fd1)' : 'transparent',
              color: isActive ? '#fff' : '#2a6fd0',
              boxShadow: isActive ? '0 0 0 4px #fffc, 0 6px 16px rgba(31,111,209,0.35)' : 'none',
              border: 'none',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              zIndex: 25,
              transition: 'all 0.18s ease'
            }}
          >
            <svg
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill={isActive && tab.key === 'chat' ? 'currentColor' : 'none'}
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d={PATHS[tab.key]} />
            </svg>
          </button>
        )
      })}

      {/* Lower Utilities Dock Pill */}
      <div
        style={{
          position: 'absolute',
          left: '18px',
          top: '720px',
          width: '54px',
          height: '158px',
          borderRadius: '27px',
          background: '#ffffffaa',
          border: '1px solid #fff',
          boxShadow: '0 8px 22px rgba(27,63,110,0.14)',
          pointerEvents: 'none',
          zIndex: 10
        }}
      />

      {/* Lower Utilities Icons */}
      {toolTabs.map((tool) => {
        const sz = 36
        const x = 45 - sz / 2
        const y = tool.cy - sz / 2

        return (
          <button
            key={tool.key}
            title={tool.title}
            style={{
              position: 'absolute',
              left: `${x}px`,
              top: `${y}px`,
              width: `${sz}px`,
              height: `${sz}px`,
              borderRadius: '50%',
              background: 'transparent',
              color: '#2a6fd0',
              border: 'none',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              zIndex: 25,
              transition: 'transform 0.15s ease'
            }}
            onMouseEnter={(e) => (e.currentTarget.style.transform = 'scale(1.12)')}
            onMouseLeave={(e) => (e.currentTarget.style.transform = 'scale(1)')}
          >
            <svg
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d={PATHS[tool.key]} />
            </svg>
          </button>
        )
      })}
    </>
  )
}
