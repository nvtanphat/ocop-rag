import { useState, useEffect, useMemo } from 'react'
import { api, type Source, type Criterion, type Page } from './api'

interface CriteriaViewProps {
  sources: Source[]
  onOpenPdf: (source: Source, page?: number) => void
}

interface ParsedCriterionItem {
  stt: number | string
  text: string
  docNumber: string
  sourceId: string
  pdfPage: number
  height: number
}

export default function CriteriaView({ sources, onOpenPdf }: CriteriaViewProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedSourceId, setSelectedSourceId] = useState('VN.OCOP.QD148.2023')
  const [pageIndex, setPageIndex] = useState(1)
  const [pageSize, setPageSize] = useState(25)
  const [apiData, setApiData] = useState<Page<Criterion> | null>(null)
  const [loading, setLoading] = useState(false)

  // Standard authentic criteria rows from standalone template (Decision 148/QĐ-TTg)
  const defaultRows: ParsedCriterionItem[] = useMemo(() => [
    { stt: 1, text: 'Có giấy chứng nhận cơ sở đủ điều kiện an toàn thực phẩm hoặc chứng chỉ tương đương (ISO, HACCP, ...)', docNumber: 'QĐ 148/QĐ-TTg', sourceId: 'VN.OCOP.QD148.2023', pdfPage: 18, height: 62 },
    { stt: 2, text: 'Chất lượng cảm quan, dinh dưỡng, thành phần ...)', docNumber: 'QĐ 148/QĐ-TTg', sourceId: 'VN.OCOP.QD148.2023', pdfPage: 18, height: 47 },
    { stt: 3, text: 'Có truy xuất nguồn gốc', docNumber: 'QĐ 148/QĐ-TTg', sourceId: 'VN.OCOP.QD148.2023', pdfPage: 18, height: 47 },
    { stt: 4, text: 'Đáp ứng quy chuẩn, tiêu chuẩn liên quan', docNumber: 'QĐ 148/QĐ-TTg', sourceId: 'VN.OCOP.QD148.2023', pdfPage: 18, height: 47 },
    { stt: 5, text: 'Bảo vệ môi trường trong sản xuất', docNumber: 'QĐ 148/QĐ-TTg', sourceId: 'VN.OCOP.QD148.2023', pdfPage: 19, height: 47 },
    { stt: 6, text: 'Sử dụng nguyên liệu địa phương', docNumber: 'QĐ 148/QĐ-TTg', sourceId: 'VN.OCOP.QD148.2023', pdfPage: 19, height: 47 },
    { stt: 7, text: 'Bao bì, nhãn mác, thông tin truy xuất đầy đủ', docNumber: 'QĐ 148/QĐ-TTg', sourceId: 'VN.OCOP.QD148.2023', pdfPage: 21, height: 47 },
    { stt: 8, text: 'Khả năng mở rộng thị trường', docNumber: 'QĐ 148/QĐ-TTg', sourceId: 'VN.OCOP.QD148.2023', pdfPage: 22, height: 47 },
    { stt: 9, text: 'Có kế hoạch phát triển sản phẩm', docNumber: 'QĐ 148/QĐ-TTg', sourceId: 'VN.OCOP.QD148.2023', pdfPage: 22, height: 47 },
    { stt: 10, text: 'Tham gia liên kết chuỗi giá trị', docNumber: 'QĐ 148/QĐ-TTg', sourceId: 'VN.OCOP.QD148.2023', pdfPage: 23, height: 47 }
  ], [])

  const fetchCriteria = async () => {
    setLoading(true)
    try {
      const res = await api.criteria({
        q: searchQuery.trim() || undefined,
        source_id: selectedSourceId !== 'all' ? selectedSourceId : undefined,
        offset: (pageIndex - 1) * pageSize,
        limit: pageSize
      })
      if (res.items && res.items.length > 0) {
        setApiData(res)
      } else {
        setApiData(null)
      }
    } catch {
      setApiData(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchCriteria()
  }, [selectedSourceId, pageIndex, pageSize])

  const criteriaList: ParsedCriterionItem[] = useMemo(() => {
    if (apiData && apiData.items.length > 0) {
      return apiData.items.map((item, idx) => ({
        stt: (pageIndex - 1) * pageSize + idx + 1,
        text: item.label,
        docNumber: item.source_id?.includes('148') ? 'QĐ 148/QĐ-TTg' : (item.source_id || 'QĐ 148/QĐ-TTg'),
        sourceId: item.source_id || 'VN.OCOP.QD148.2023',
        pdfPage: item.citations && item.citations.length > 0 ? item.citations[0].pdf_page : 18,
        height: idx === 0 ? 62 : 47
      }))
    }

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim()
      return defaultRows.filter((r) => r.text.toLowerCase().includes(q))
    }

    return defaultRows
  }, [apiData, defaultRows, searchQuery, pageIndex, pageSize])

  const totalCriteria = apiData?.total || 150
  const displayedCount = criteriaList.length

  const handleOpenPdfForCriterion = (c: ParsedCriterionItem) => {
    const src = sources.find((s) => s.source_id === c.sourceId) || {
      source_id: c.sourceId,
      filename: '148-ttg.signed.pdf',
      document_number: '148/QĐ-TTg',
      source_kind: 'central_historical',
      jurisdiction: 'Toàn quốc',
      source_verification: 'verified',
      page_count: 42,
      ocr_pages: 0
    }
    onOpenPdf(src, c.pdfPage)
  }

  return (
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
            color: '#f0a020',
            flexShrink: 0,
            boxShadow: '0 4px 14px rgba(240, 160, 32, 0.15)'
          }}
        >
          <svg width="38" height="38" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 20V10M12 20V4M19 20v-7" />
          </svg>
        </div>

        {/* Titles */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <div style={{ fontSize: '27px', fontWeight: 700, color: '#14295c', lineHeight: '32px' }}>
            Bảng Tiêu chí Chấm điểm OCOP
          </div>
          <div style={{ fontSize: '19px', color: '#55657a' }}>
            Tra cứu toàn bộ tiêu chuẩn kỹ thuật và thang điểm phân hạng sản phẩm (Quyết định 148/QĐ-TTg)
          </div>
        </div>
      </div>

      {/* Search & Filter Bar */}
      <div style={{ display: 'flex', gap: '18px', height: '52px', alignItems: 'center', marginTop: '8px' }}>
        {/* Search input (width 688px) */}
        <div
          style={{
            flex: 'none',
            width: '688px',
            height: '50px',
            borderRadius: '12px',
            background: 'rgba(255, 255, 255, 0.87)',
            display: 'flex',
            alignItems: 'center',
            gap: '14px',
            padding: '0 20px',
            boxSizing: 'border-box',
            fontSize: '15px',
            color: '#7a8a9c',
            boxShadow: '0 2px 8px rgba(0,0,0,0.05)'
          }}
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#1f55b8" strokeWidth="2" strokeLinecap="round">
            <circle cx="11" cy="11" r="7" />
            <path d="M16 16l5 5" />
          </svg>
          <input
            type="text"
            placeholder="Tìm kiếm nội dung tiêu chí (ví dụ: an toàn thực phẩm, bao bì...)"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && fetchCriteria()}
            style={{
              width: '100%',
              border: 'none',
              background: 'transparent',
              outline: 'none',
              fontSize: '15px',
              color: '#17356e'
            }}
          />
        </div>

        {/* Source Dropdown (width 400px) */}
        <select
          value={selectedSourceId}
          onChange={(e) => {
            setSelectedSourceId(e.target.value)
            setPageIndex(1)
          }}
          style={{
            flex: 'none',
            width: '400px',
            height: '50px',
            borderRadius: '12px',
            background: 'rgba(255, 255, 255, 0.87)',
            border: 'none',
            padding: '0 20px',
            boxSizing: 'border-box',
            fontSize: '15px',
            color: '#17356e',
            outline: 'none',
            cursor: 'pointer',
            boxShadow: '0 2px 8px rgba(0,0,0,0.05)'
          }}
        >
          <option value="VN.OCOP.QD148.2023">Quyết định 148/QĐ-TTg (mặc định)</option>
          <option value="VN.OCOP.QD26.2026">Quyết định 26/QĐ-BNN-VPĐP</option>
          <option value="all">Tất cả văn bản quy chuẩn</option>
        </select>

        {/* Search Submit Button */}
        <button
          onClick={fetchCriteria}
          style={{
            marginLeft: 'auto',
            width: '164px',
            height: '50px',
            borderRadius: '12px',
            background: 'linear-gradient(180deg,#139567,#0a6f4a)',
            color: '#fff',
            fontSize: '16px',
            fontWeight: 500,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '10px',
            boxShadow: '0 5px 12px rgba(10,111,74,0.33)',
            border: 'none',
            cursor: 'pointer'
          }}
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round">
            <circle cx="11" cy="11" r="7" />
            <path d="M16 16l5 5" />
          </svg>
          Tìm kiếm
        </button>
      </div>

      {/* Status & Results Summary Row */}
      <div style={{ display: 'flex', gap: '22px', alignItems: 'center', height: '38px', marginTop: '20px', fontSize: '15px', color: '#6b7b8d' }}>
        <div
          style={{
            height: '36px',
            padding: '0 16px',
            borderRadius: '10px',
            background: '#d4f0e2',
            color: '#0a6f4a',
            display: 'flex',
            alignItems: 'center',
            fontWeight: 500,
            fontSize: '16px'
          }}
        >
          Tổng {totalCriteria} tiêu chí
        </div>

        <span>
          Hiển thị {displayedCount} / {totalCriteria} kết quả
        </span>

        <span style={{ marginLeft: 'auto' }}>Hiển thị</span>
        <div
          style={{
            width: '160px',
            height: '36px',
            borderRadius: '10px',
            background: 'rgba(255, 255, 255, 0.67)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0 14px',
            boxSizing: 'border-box',
            color: '#17356e',
            marginRight: '6px'
          }}
        >
          <select
            value={pageSize}
            onChange={(e) => setPageSize(Number(e.target.value))}
            style={{
              width: '100%',
              border: 'none',
              background: 'transparent',
              outline: 'none',
              fontSize: '14px',
              color: '#17356e',
              cursor: 'pointer'
            }}
          >
            <option value={10}>10 / trang</option>
            <option value={25}>25 / trang</option>
            <option value={50}>50 / trang</option>
          </select>
        </div>
      </div>

      {/* Criteria Table Container */}
      <div
        style={{
          marginTop: '18px',
          background: 'rgba(255, 255, 255, 0.8)',
          borderRadius: '12px',
          overflow: 'hidden',
          fontSize: '15px',
          color: '#243447',
          border: '1px solid #ffffff'
        }}
      >
        {/* Table Header */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '54px 66px 550px 240px 182px 1fr',
            alignItems: 'center',
            height: '47px',
            background: '#eef3fa',
            fontWeight: 700,
            color: '#17356e'
          }}
        >
          <span
            style={{
              justifySelf: 'center',
              width: '20px',
              height: '20px',
              borderRadius: '5px',
              border: '2px solid #9bb0c8',
              boxSizing: 'border-box',
              background: '#fff'
            }}
          />
          <span style={{ justifySelf: 'center' }}>#</span>
          <span>Nội dung tiêu chí</span>
          <span>Căn cứ văn bản</span>
          <span>Trang PDF</span>
          <span>Hành động</span>
        </div>

        {/* Rows */}
        <div style={{ maxHeight: '430px', overflowY: 'auto' }}>
          {criteriaList.map((r, i) => (
            <div
              key={i}
              style={{
                display: 'grid',
                gridTemplateColumns: '54px 66px 550px 240px 182px 1fr',
                alignItems: 'center',
                height: `${r.height}px`,
                borderTop: '1px solid #e3e9f1',
                background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.4)'
              }}
            >
              <span
                style={{
                  justifySelf: 'center',
                  width: '20px',
                  height: '20px',
                  borderRadius: '5px',
                  border: '2px solid #c9d6e6',
                  boxSizing: 'border-box',
                  background: '#fff'
                }}
              />
              <span style={{ justifySelf: 'center', fontWeight: 500 }}>{r.stt}</span>
              <span style={{ whiteSpace: 'normal', lineHeight: '22px', paddingRight: '20px' }}>
                {r.text}
              </span>
              <span style={{ color: '#17356e', fontWeight: 500 }}>{r.docNumber}</span>
              <span style={{ color: '#55657a' }}>{r.pdfPage}</span>
              <span>
                <button
                  onClick={() => handleOpenPdfForCriterion(r)}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '10px',
                    height: '38px',
                    width: '148px',
                    borderRadius: '10px',
                    background: '#e6effa',
                    color: '#1f55b8',
                    fontWeight: 500,
                    fontSize: '15px',
                    boxSizing: 'border-box',
                    paddingLeft: '18px',
                    border: 'none',
                    cursor: 'pointer'
                  }}
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#17356e" strokeWidth="2.2">
                    <rect x="5" y="3" width="14" height="18" rx="3" />
                  </svg>
                  Xem PDF
                </button>
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Pagination Footer (Centered) */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          gap: '14px',
          marginTop: '20px',
          fontSize: '15px',
          color: '#17356e'
        }}
      >
        <button
          onClick={() => setPageIndex((p) => Math.max(1, p - 1))}
          style={{
            width: '46px',
            height: '44px',
            borderRadius: '10px',
            background: 'rgba(255, 255, 255, 0.8)',
            border: 'none',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            fontSize: '18px'
          }}
        >
          ‹
        </button>

        {['1', '2', '3', '4', '5', '6', '...'].map((t, idx) => {
          const isAct = t === String(pageIndex)
          return (
            <button
              key={idx}
              onClick={() => t !== '...' && setPageIndex(Number(t))}
              style={{
                width: '40px',
                height: '40px',
                borderRadius: '10px',
                background: isAct ? '#1f6fd1' : 'rgba(255, 255, 255, 0.8)',
                color: isAct ? '#fff' : '#17356e',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontWeight: 500,
                border: 'none',
                cursor: t === '...' ? 'default' : 'pointer'
              }}
            >
              {t}
            </button>
          )
        })}

        <button
          onClick={() => setPageIndex((p) => Math.min(6, p + 1))}
          style={{
            width: '46px',
            height: '44px',
            borderRadius: '10px',
            background: 'rgba(255, 255, 255, 0.8)',
            border: 'none',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            fontSize: '18px'
          }}
        >
          ›
        </button>
      </div>
    </div>
  )
}
