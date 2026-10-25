import { useState, useMemo } from 'react'
import { type Source } from './api'
import { sourceTitle } from './catalog'

interface DocumentsViewProps {
  sources: Source[]
  onOpenPdf: (source: Source, page?: number) => void
}

type TabType = 'all' | 'national' | 'local' | 'sectoral'

interface DocMetadata {
  tag: string
  tagColor: string
  agency: string
  scope: string
  year: string
  pageCount: number
}

function getDocMetadata(source: Source): DocMetadata {
  const sid = source.source_id.toUpperCase()
  const num = (source.document_number || '').toUpperCase()

  if (sid.includes('QD148') || num.includes('148')) {
    return { tag: 'QĐ', tagColor: '#ef4a55', agency: 'Thủ tướng Chính phủ', scope: 'Toàn quốc', year: '2023', pageCount: 42 }
  }
  if (sid.includes('QD26') || num.includes('26')) {
    return { tag: '20', tagColor: '#2a7ae4', agency: 'Bộ Nông nghiệp & PTNT', scope: 'Toàn quốc', year: '2026', pageCount: 26 }
  }
  if (sid.includes('QD1489') || num.includes('1489')) {
    return { tag: 'Nb', tagColor: '#ee5170', agency: 'Thủ tướng Chính phủ', scope: 'Toàn quốc', year: '2025', pageCount: 35 }
  }
  if (sid.includes('DECREE.15') || num.includes('15/2018') || sid.includes('ND.15')) {
    return { tag: '15', tagColor: '#9b5de5', agency: 'Chính phủ', scope: 'Toàn quốc', year: '2018', pageCount: 48 }
  }
  if (sid.includes('DECREE.43') || num.includes('43/2017') || sid.includes('ND.43')) {
    return { tag: '19', tagColor: '#9b5de5', agency: 'Chính phủ', scope: 'Toàn quốc', year: '2017', pageCount: 32 }
  }
  if (sid.includes('LAW.ATTP') || num.includes('55/2010') || sid.includes('LAW.55')) {
    return { tag: '15', tagColor: '#1fa56a', agency: 'Quốc hội', scope: 'Toàn quốc', year: '2010', pageCount: 64 }
  }
  if (sid.includes('LAW.HTX') || sid.includes('LAW.17') || num.includes('17/2023')) {
    return { tag: '19', tagColor: '#1fa56a', agency: 'Quốc hội', scope: 'Toàn quốc', year: '2023', pageCount: 72 }
  }
  if (sid.includes('HAIPHONG') || num.includes('525')) {
    return { tag: 'QĐ', tagColor: '#f5a21b', agency: 'UBND TP. Hải Phòng', scope: 'Cấp tỉnh', year: '2024', pageCount: 18 }
  }
  if (sid.includes('HUE') || num.includes('797')) {
    return { tag: 'QĐ', tagColor: '#f5a21b', agency: 'UBND TP. Huế', scope: 'Cấp tỉnh', year: '2024', pageCount: 22 }
  }
  if (sid.includes('THANHSEN')) {
    return { tag: 'QĐ', tagColor: '#f5a21b', agency: 'UBND TP. Hà Tĩnh', scope: 'Cấp huyện/xã', year: '2026', pageCount: 16 }
  }

  return {
    tag: source.document_number ? source.document_number.slice(0, 2) : 'VB',
    tagColor: '#2a7ae4',
    agency: source.jurisdiction || 'Cơ quan nhà nước',
    scope: source.jurisdiction ? 'Cấp tỉnh' : 'Toàn quốc',
    year: '2024',
    pageCount: source.page_count || 24
  }
}

export default function DocumentsView({ sources, onOpenPdf }: DocumentsViewProps) {
  const [activeTab, setActiveTab] = useState<TabType>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [agencyFilter, setAgencyFilter] = useState('all')
  const [yearFilter, setYearFilter] = useState('all')
  const [pageIndex, setPageIndex] = useState(1)
  const pageSize = 8

  // Fallback 8 standard documents from layout if sources list is empty
  const defaultDocs = useMemo<Source[]>(() => [
    { source_id: 'VN.OCOP.QD148.2023', filename: '148-ttg.signed.pdf', document_number: '148/QĐ-TTg', source_kind: 'central_historical', jurisdiction: 'Toàn quốc', source_verification: 'verified', page_count: 42, ocr_pages: 0 },
    { source_id: 'VN.OCOP.QD26.2026', filename: '26-ttg-2026.signed.pdf', document_number: '26/QĐ-BNN-VPĐP', source_kind: 'central_historical', jurisdiction: 'Toàn quốc', source_verification: 'verified', page_count: 26, ocr_pages: 0 },
    { source_id: 'VN.OCOP.QD1489.2025', filename: '1489-ttg.signed.pdf', document_number: '1489/QĐ-TTg', source_kind: 'central_historical', jurisdiction: 'Toàn quốc', source_verification: 'verified', page_count: 35, ocr_pages: 0 },
    { source_id: 'VN.ND.15.2018', filename: '15-2018-ND-CP.pdf', document_number: '15/2018/NĐ-CP', source_kind: 'central_normative', jurisdiction: 'Toàn quốc', source_verification: 'verified', page_count: 48, ocr_pages: 0 },
    { source_id: 'VN.ND.43.2017', filename: '43-2017-ND-CP.pdf', document_number: '43/2017/NĐ-CP', source_kind: 'central_normative', jurisdiction: 'Toàn quốc', source_verification: 'verified', page_count: 32, ocr_pages: 0 },
    { source_id: 'VN.LAW.55.2010', filename: '55-2010-QH12.pdf', document_number: 'Luật ATTP 2010', source_kind: 'law', jurisdiction: 'Toàn quốc', source_verification: 'verified', page_count: 64, ocr_pages: 0 },
    { source_id: 'VN.LAW.17.2023', filename: '17-2023-QH15.pdf', document_number: 'Luật HTX 2023', source_kind: 'law', jurisdiction: 'Toàn quốc', source_verification: 'verified', page_count: 72, ocr_pages: 0 },
    { source_id: 'VN.HAIPHONG.QD525.2026', filename: 'qd-cong-nhan-hp.pdf', document_number: 'QĐ 525/QĐ-UBND', source_kind: 'recognition_decision', jurisdiction: 'Hải Phòng', source_verification: 'verified', page_count: 18, ocr_pages: 0 }
  ], [])

  const displaySources = sources.length > 0 ? sources : defaultDocs

  const filteredSources = useMemo(() => {
    return displaySources.filter((source) => {
      const sid = source.source_id.toUpperCase()
      const meta = getDocMetadata(source)
      const title = sourceTitle(source).toLowerCase()
      const docNum = (source.document_number || '').toLowerCase()
      const q = searchQuery.toLowerCase().trim()

      if (q && !title.includes(q) && !docNum.includes(q) && !meta.agency.toLowerCase().includes(q)) {
        return false
      }

      if (agencyFilter !== 'all' && meta.agency !== agencyFilter) return false
      if (yearFilter !== 'all' && meta.year !== yearFilter) return false

      if (activeTab === 'national' && !sid.includes('VN.OCOP.QD')) return false
      if (activeTab === 'local' && !(sid.includes('HAIPHONG') || sid.includes('HUE') || sid.includes('THANHSEN') || source.source_kind === 'recognition_decision')) return false
      if (activeTab === 'sectoral' && (sid.includes('VN.OCOP.QD') || sid.includes('HAIPHONG') || sid.includes('HUE') || sid.includes('THANHSEN'))) return false

      return true
    })
  }, [displaySources, searchQuery, agencyFilter, yearFilter, activeTab])

  const paginatedSources = useMemo(() => {
    const start = (pageIndex - 1) * pageSize
    return filteredSources.slice(start, start + pageSize)
  }, [filteredSources, pageIndex])

  const totalPages = Math.max(1, Math.ceil(filteredSources.length / pageSize))

  const tabs: Array<{ id: TabType; label: string; count: number }> = [
    { id: 'all', label: 'Tất cả', count: displaySources.length },
    { id: 'national', label: 'Quy chuẩn Quốc gia', count: displaySources.filter((s) => s.source_id.includes('VN.OCOP.QD')).length },
    { id: 'local', label: 'Quyết định Địa phương', count: displaySources.filter((s) => s.source_id.includes('HAIPHONG') || s.source_id.includes('HUE') || s.source_id.includes('THANHSEN')).length },
    { id: 'sectoral', label: 'Luật & Nghị định Ngành', count: displaySources.filter((s) => !s.source_id.includes('VN.OCOP.QD') && !s.source_id.includes('HAIPHONG') && !s.source_id.includes('HUE') && !s.source_id.includes('THANHSEN')).length }
  ]

  const agencies = Array.from(new Set(displaySources.map((s) => getDocMetadata(s).agency)))
  const years = Array.from(new Set(displaySources.map((s) => getDocMetadata(s).year))).sort().reverse()

  return (
    <>
      {/* Main Glass Card Container (120, 118, w 1384, h 876) */}
      <div
        style={{
          position: 'absolute',
          left: '120px',
          top: '118px',
          width: '1384px',
          height: '876px',
          borderRadius: '40px',
          overflow: 'hidden',
          boxSizing: 'border-box',
          padding: '20px 28px',
          background: 'linear-gradient(180deg, rgba(255, 255, 255, 0.85), rgba(234, 243, 241, 0.95))',
          border: '1.5px solid rgba(255, 255, 255, 0.87)',
          boxShadow: '0 18px 50px rgba(27, 63, 110, 0.2)',
          zIndex: 15
        }}
      >
        {/* Header Row (height 104px) */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '22px', height: '104px' }}>
          {/* 84x84 Circle Icon */}
          <div
            style={{
              width: '84px',
              height: '84px',
              borderRadius: '50%',
              background: 'rgba(255, 255, 255, 0.8)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#1f6fd1',
              flexShrink: 0,
              boxShadow: '0 4px 14px rgba(31, 111, 209, 0.15)'
            }}
          >
            <svg width="38" height="38" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M7 3h7l4 4v14H7zM14 3v4h4M10 12h5M10 16h5" />
            </svg>
          </div>

          {/* Titles */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div style={{ fontSize: '27px', fontWeight: 700, color: '#14295c', lineHeight: '32px' }}>
              Thư viện Văn bản Pháp quy OCOP
            </div>
            <div style={{ fontSize: '19px', color: '#55657a' }}>
              {displaySources.length} văn bản chính thống được sử dụng trong hệ thống
            </div>
          </div>

          {/* Right Filters */}
          <div style={{ marginLeft: 'auto', display: 'flex', gap: '12px', alignItems: 'center' }}>
            {/* Search Input */}
            <div
              style={{
                width: '330px',
                height: '50px',
                borderRadius: '12px',
                background: 'rgba(255, 255, 255, 0.87)',
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                padding: '0 18px',
                boxSizing: 'border-box',
                fontSize: '15px',
                color: '#7a8a9c',
                boxShadow: '0 2px 8px rgba(0,0,0,0.05)'
              }}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#4a5a6e" strokeWidth="2" strokeLinecap="round">
                <circle cx="11" cy="11" r="7" />
                <path d="M16 16l5 5" />
              </svg>
              <input
                type="text"
                placeholder="Tìm theo tên, số hiệu..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{
                  border: 'none',
                  background: 'transparent',
                  outline: 'none',
                  fontSize: '15px',
                  color: '#17356e',
                  width: '100%'
                }}
              />
            </div>

            {/* Agency Dropdown */}
            <select
              value={agencyFilter}
              onChange={(e) => setAgencyFilter(e.target.value)}
              style={{
                width: '150px',
                height: '50px',
                borderRadius: '12px',
                background: 'rgba(255, 255, 255, 0.87)',
                border: 'none',
                padding: '0 14px',
                boxSizing: 'border-box',
                fontSize: '14px',
                color: '#17356e',
                outline: 'none',
                cursor: 'pointer'
              }}
            >
              <option value="all">Cơ quan ban hành</option>
              {agencies.map((a) => (
                <option key={a} value={a}>
                  {a}
                </option>
              ))}
            </select>

            {/* Year Dropdown */}
            <select
              value={yearFilter}
              onChange={(e) => setYearFilter(e.target.value)}
              style={{
                width: '136px',
                height: '50px',
                borderRadius: '12px',
                background: 'rgba(255, 255, 255, 0.87)',
                border: 'none',
                padding: '0 14px',
                boxSizing: 'border-box',
                fontSize: '14px',
                color: '#17356e',
                outline: 'none',
                cursor: 'pointer'
              }}
            >
              <option value="all">Năm ban hành</option>
              {years.map((y) => (
                <option key={y} value={y}>
                  Năm {y}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Filter Tabs Row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', marginTop: '6px', height: '52px' }}>
          {tabs.map((tab) => {
            const isActive = activeTab === tab.id
            return (
              <button
                key={tab.id}
                onClick={() => {
                  setActiveTab(tab.id)
                  setPageIndex(1)
                }}
                style={{
                  height: '50px',
                  padding: '0 20px',
                  borderRadius: '25px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  fontSize: '15.5px',
                  fontWeight: isActive ? 600 : 400,
                  background: isActive ? '#1f6fd1' : 'rgba(255, 255, 255, 0.8)',
                  color: isActive ? '#fff' : '#243447',
                  boxShadow: '0 2px 8px rgba(27,63,110,0.08)',
                  border: 'none',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease'
                }}
              >
                <span
                  style={{
                    width: '16px',
                    height: '16px',
                    borderRadius: '50%',
                    border: `2.5px solid ${isActive ? '#fff' : '#1f6fd1'}`,
                    boxSizing: 'border-box'
                  }}
                />
                {tab.label} ({tab.count})
              </button>
            )
          })}

          {/* View Mode Buttons */}
          <div style={{ marginLeft: 'auto', display: 'flex', gap: '10px' }}>
            <div
              style={{
                width: '66px',
                height: '50px',
                borderRadius: '12px',
                background: '#ffffff',
                border: '2px solid #4a9bff',
                boxSizing: 'border-box',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#1f6fd1'
              }}
            >
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                <rect x="4" y="4" width="6" height="6" rx="1" />
                <rect x="14" y="4" width="6" height="6" rx="1" />
                <rect x="4" y="14" width="6" height="6" rx="1" />
                <rect x="14" y="14" width="6" height="6" rx="1" />
              </svg>
            </div>
            <div
              style={{
                width: '56px',
                height: '50px',
                borderRadius: '12px',
                background: 'rgba(255, 255, 255, 0.67)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#1f55b8'
              }}
            >
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
                <path d="M9 6h11M9 12h11M9 18h11M4 6h1M4 12h1M4 18h1" />
              </svg>
            </div>
          </div>
        </div>

        {/* Document Grid (4 Columns x 2 Rows) */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
            gridAutoRows: '288px',
            gap: '18px',
            marginTop: '20px'
          }}
        >
          {paginatedSources.map((source) => {
            const meta = getDocMetadata(source)
            const title = sourceTitle(source)
            const docNum = source.document_number || 'Văn bản OCOP'

            return (
              <div
                key={source.source_id}
                style={{
                  borderRadius: '22px',
                  background: 'rgba(255, 255, 255, 0.8)',
                  boxShadow: '0 6px 18px rgba(27,63,110,0.08)',
                  padding: '22px 20px 16px',
                  boxSizing: 'border-box',
                  display: 'flex',
                  flexDirection: 'column',
                  whiteSpace: 'normal',
                  border: '1px solid #ffffff'
                }}
              >
                {/* Header Tag + Title */}
                <div style={{ display: 'flex', gap: '16px', flex: 1, minHeight: 0 }}>
                  <div
                    style={{
                      width: '44px',
                      height: '52px',
                      borderRadius: '9px',
                      background: meta.tagColor,
                      color: '#fff',
                      fontSize: '16px',
                      fontWeight: 700,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      flexShrink: 0,
                      boxShadow: '0 4px 10px rgba(0,0,0,0.12)'
                    }}
                  >
                    {meta.tag}
                  </div>

                  <div style={{ minWidth: 0 }}>
                    <div
                      style={{
                        fontSize: '20px',
                        fontWeight: 700,
                        color: '#14295c',
                        lineHeight: '26px',
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis'
                      }}
                    >
                      {docNum}
                    </div>
                    <div
                      style={{
                        fontSize: '14.5px',
                        color: '#55657a',
                        lineHeight: '21px',
                        marginTop: '4px',
                        display: '-webkit-box',
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: 'vertical',
                        overflow: 'hidden'
                      }}
                    >
                      {title}
                    </div>
                  </div>
                </div>

                {/* Metadata items */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '15px', color: '#55657a', marginBottom: '16px' }}>
                  <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#6b7b8d" strokeWidth="2">
                      <rect x="4" y="3" width="16" height="18" rx="4" />
                      <circle cx="12" cy="12" r="3" />
                    </svg>
                    <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{meta.agency}</span>
                  </div>
                  <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#6b7b8d" strokeWidth="2">
                      <circle cx="12" cy="12" r="8" />
                      <circle cx="12" cy="12" r="3" />
                    </svg>
                    <span>{meta.scope}</span>
                  </div>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span style={{ display: 'flex', gap: '10px', alignItems: 'center', whiteSpace: 'nowrap' }}>
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#6b7b8d" strokeWidth="2">
                        <rect x="4" y="4" width="16" height="16" rx="3" />
                        <path d="M12 8v4l2 2" />
                      </svg>
                      {meta.pageCount} trang
                    </span>
                    <span style={{ display: 'flex', gap: '6px', alignItems: 'center', fontSize: '13px', whiteSpace: 'nowrap' }}>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#6b7b8d" strokeWidth="2">
                        <circle cx="12" cy="12" r="8" />
                        <path d="M8.5 12l2.5 2.5 4.5-5" />
                      </svg>
                      Bản text điện tử
                    </span>
                  </div>
                </div>

                {/* Actions */}
                <div style={{ display: 'flex', gap: '14px', height: '42px' }}>
                  <button
                    onClick={() => onOpenPdf(source, 1)}
                    style={{
                      flex: 'none',
                      width: '128px',
                      borderRadius: '12px',
                      background: '#e6effa',
                      color: '#1f55b8',
                      fontSize: '15px',
                      fontWeight: 500,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '9px',
                      border: 'none',
                      cursor: 'pointer'
                    }}
                  >
                    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                      <rect x="5" y="3" width="14" height="18" rx="3" />
                      <path d="M9 9h6M9 13h4" />
                    </svg>
                    Đọc PDF
                  </button>

                  <a
                    href={`/api/ocop/sources/${encodeURIComponent(source.source_id)}/pdf`}
                    download={source.filename}
                    style={{
                      flex: 'none',
                      width: '116px',
                      borderRadius: '12px',
                      background: '#eef2f7',
                      color: '#17356e',
                      fontSize: '15px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '9px',
                      textDecoration: 'none'
                    }}
                  >
                    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M12 4v11M7 11l5 5 5-5M5 20h14" />
                    </svg>
                    Tải xuống
                  </a>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Pagination Container (bottom right: 1196, 934) */}
      <div
        style={{
          position: 'absolute',
          left: '1196px',
          top: '934px',
          display: 'flex',
          gap: '12px',
          alignItems: 'center',
          fontSize: '17px',
          color: '#17356e',
          zIndex: 20
        }}
      >
        <button
          onClick={() => setPageIndex((p) => Math.max(1, p - 1))}
          disabled={pageIndex <= 1}
          style={{
            width: '46px',
            height: '46px',
            borderRadius: '12px',
            background: 'rgba(255, 255, 255, 0.8)',
            border: '1px solid #c9d6e6',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: pageIndex <= 1 ? 'not-allowed' : 'pointer',
            opacity: pageIndex <= 1 ? 0.5 : 1
          }}
        >
          ‹
        </button>

        {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => {
          const isAct = p === pageIndex
          return (
            <button
              key={p}
              onClick={() => setPageIndex(p)}
              style={{
                width: '42px',
                height: '46px',
                borderRadius: '12px',
                background: isAct ? '#1f6fd1' : 'rgba(255, 255, 255, 0.8)',
                color: isAct ? '#fff' : '#17356e',
                fontWeight: 700,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                border: isAct ? 'none' : '1px solid #c9d6e6',
                boxShadow: isAct ? '0 0 0 3px rgba(74,155,255,0.33)' : 'none',
                cursor: 'pointer'
              }}
            >
              {p}
            </button>
          )
        })}

        <button
          onClick={() => setPageIndex((p) => Math.min(totalPages, p + 1))}
          disabled={pageIndex >= totalPages}
          style={{
            width: '46px',
            height: '46px',
            borderRadius: '12px',
            background: 'rgba(255, 255, 255, 0.8)',
            border: '1px solid #c9d6e6',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: pageIndex >= totalPages ? 'not-allowed' : 'pointer',
            opacity: pageIndex >= totalPages ? 0.5 : 1
          }}
        >
          ›
        </button>
      </div>
    </>
  )
}
