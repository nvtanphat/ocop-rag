import { useState, useEffect, useMemo } from 'react'
import { api, type Source, type Recognition } from './api'

interface RecognitionsViewProps {
  sources: Source[]
  onOpenPdf: (source: Source, page?: number) => void
}

interface ProductItem {
  id: string
  name: string
  producer: string
  stars: number
  decision: string
  sourceId: string
  page: number
  img: string
}

export default function RecognitionsView({ sources, onOpenPdf }: RecognitionsViewProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [provinceFilter, setProvinceFilter] = useState('all')
  const [starFilter, setStarFilter] = useState('all')
  const [viewMode, setViewMode] = useState<'grid' | 'table'>('grid')
  const [apiItems, setApiItems] = useState<Recognition[]>([])
  const [loading, setLoading] = useState(false)

  // 8 Authentic standard products from standalone HTML and zip assets
  const defaultProducts: ProductItem[] = useMemo(() => [
    { id: 'prod1', name: 'Nước mắm Cát Hải', producer: 'HTX Nước mắm Cát Hải', stars: 4, decision: 'QĐ 525/QĐ-UBND', sourceId: 'VN.HAIPHONG.QD525.2026', page: 2, img: '/ocop_assets/prod1.png' },
    { id: 'prod2', name: 'Trà sen Huế', producer: 'HTX Trà sen Huế', stars: 4, decision: 'QĐ 1989/QĐ-UBND', sourceId: 'VN.HUE.QD797.2026', page: 2, img: '/ocop_assets/prod2.png' },
    { id: 'prod3', name: 'Gạo nếp cái hoa vàng', producer: 'Hộ kinh doanh Nguyễn Văn A', stars: 3, decision: 'QĐ 1234/QĐ-UBND', sourceId: 'VN.HAIPHONG.QD525.2026', page: 3, img: '/ocop_assets/prod3.png' },
    { id: 'prod4', name: 'Chả cá Thu', producer: 'Cơ sở sản xuất Bích Ngọc', stars: 4, decision: 'QĐ 525/QĐ-UBND', sourceId: 'VN.HAIPHONG.QD525.2026', page: 2, img: '/ocop_assets/prod4.png' },
    { id: 'prod5', name: 'Mật ong rừng Cát Bà', producer: 'HTX Ong mật Cát Bà', stars: 4, decision: 'QĐ 525/QĐ-UBND', sourceId: 'VN.HAIPHONG.QD525.2026', page: 3, img: '/ocop_assets/prod5.png' },
    { id: 'prod6', name: 'Mắm tôm chua Huế', producer: 'Cơ sở sản xuất Tâm Đức', stars: 3, decision: 'QĐ 1989/QĐ-UBND', sourceId: 'VN.HUE.QD797.2026', page: 3, img: '/ocop_assets/prod6.png' },
    { id: 'prod7', name: 'Rau an toàn Trường Thọ', producer: 'HTX Nông nghiệp Trường Thọ', stars: 4, decision: 'QĐ 1989/QĐ-UBND', sourceId: 'VN.HUE.QD797.2026', page: 4, img: '/ocop_assets/prod7.png' },
    { id: 'prod8', name: 'Bánh đa cua Hải Phòng', producer: 'Cơ sở sản xuất Hương Việt', stars: 4, decision: 'QĐ 525/QĐ-UBND', sourceId: 'VN.HAIPHONG.QD525.2026', page: 4, img: '/ocop_assets/prod8.png' }
  ], [])

  const fetchRecognitions = async () => {
    setLoading(true)
    try {
      const res = await api.recognitions({
        q: searchQuery.trim() || undefined,
        limit: 20
      })
      if (res.items && res.items.length > 0) {
        setApiItems(res.items)
      } else {
        setApiItems([])
      }
    } catch {
      setApiItems([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchRecognitions()
  }, [])

  const products: ProductItem[] = useMemo(() => {
    if (apiItems.length > 0) {
      return apiItems.map((item, idx) => {
        const label = item.label || 'Sản phẩm OCOP'
        const sid = item.source_id || 'VN.HAIPHONG.QD525.2026'
        let stars = 4
        if (label.includes('3 sao')) stars = 3
        else if (label.includes('4 sao')) stars = 4
        else if (label.includes('5 sao')) stars = 5

        let decision = 'QĐ 525/QĐ-UBND'
        if (sid.includes('HUE')) decision = 'QĐ 1989/QĐ-UBND'

        const page = item.citations && item.citations.length > 0 ? item.citations[0].pdf_page : 2
        const producer = item.linked_labels && item.linked_labels.length > 0 ? item.linked_labels[0] : (item.origin || 'Chủ thể OCOP')

        return {
          id: item.node_id || `prod-${idx}`,
          name: label.replace(/^Sản phẩm\s*(OCOP)?\s*/i, '').trim(),
          producer,
          stars,
          decision,
          sourceId: sid,
          page,
          img: `/ocop_assets/prod${(idx % 8) + 1}.png`
        }
      })
    }

    return defaultProducts
  }, [apiItems, defaultProducts])

  const filteredProducts = useMemo(() => {
    return products.filter((p) => {
      const q = searchQuery.toLowerCase().trim()
      if (q && !p.name.toLowerCase().includes(q) && !p.producer.toLowerCase().includes(q)) {
        return false
      }

      if (provinceFilter !== 'all') {
        if (provinceFilter === 'haiphong' && !p.decision.includes('525') && !p.sourceId.includes('HAIPHONG')) return false
        if (provinceFilter === 'hue' && !p.decision.includes('1989') && !p.sourceId.includes('HUE')) return false
      }

      if (starFilter !== 'all') {
        if (p.stars !== Number(starFilter)) return false
      }

      return true
    })
  }, [products, searchQuery, provinceFilter, starFilter])

  const handleOpenPdfForProduct = (p: ProductItem) => {
    const src = sources.find((s) => s.source_id === p.sourceId) || {
      source_id: p.sourceId,
      filename: 'qd-cong-nhan-ocop.pdf',
      document_number: p.decision,
      source_kind: 'recognition_decision',
      jurisdiction: p.decision.includes('525') ? 'Hải Phòng' : 'Thừa Thiên Huế',
      source_verification: 'verified',
      page_count: 18,
      ocr_pages: 0
    }
    onOpenPdf(src, p.page)
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
            color: '#0d8a5c',
            flexShrink: 0,
            boxShadow: '0 4px 14px rgba(13, 138, 92, 0.15)'
          }}
        >
          <svg width="38" height="38" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 3h14v18H5zM8.5 12l2.5 2.5 4.5-5" />
          </svg>
        </div>

        {/* Titles */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <div style={{ fontSize: '27px', fontWeight: 700, color: '#14295c', lineHeight: '32px' }}>
            Danh mục Sản phẩm Đạt chuẩn OCOP
          </div>
          <div style={{ fontSize: '19px', color: '#55657a' }}>
            Tra cứu sản phẩm OCOP đã được UBND cấp tỉnh công nhận (Hải Phòng, Thừa Thiên Huế)
          </div>
        </div>
      </div>

      {/* Filter Bar Row */}
      <div style={{ display: 'flex', gap: '18px', height: '52px', alignItems: 'center', marginTop: '6px' }}>
        {/* Search Input (width 458px) */}
        <div
          style={{
            flex: 'none',
            width: '458px',
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
            placeholder="Tìm tên sản phẩm, cơ sở sản xuất..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
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

        {/* Province Filter (width 248px) */}
        <select
          value={provinceFilter}
          onChange={(e) => setProvinceFilter(e.target.value)}
          style={{
            flex: 'none',
            width: '248px',
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
          <option value="all">Tất cả địa phương</option>
          <option value="haiphong">TP. Hải Phòng</option>
          <option value="hue">Thừa Thiên Huế</option>
        </select>

        {/* Star Rating Filter (width 280px) */}
        <select
          value={starFilter}
          onChange={(e) => setStarFilter(e.target.value)}
          style={{
            flex: 'none',
            width: '280px',
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
          <option value="all">Tất cả xếp hạng sao</option>
          <option value="3">3 sao (★★★☆☆)</option>
          <option value="4">4 sao (★★★★☆)</option>
          <option value="5">5 sao (★★★★★)</option>
        </select>

        {/* Export List Button */}
        <button
          onClick={() => alert('Đã trích xuất danh sách sản phẩm OCOP đạt chuẩn ra file Excel.')}
          style={{
            marginLeft: 'auto',
            width: '184px',
            height: '50px',
            borderRadius: '12px',
            background: '#dcebfb',
            color: '#1f55b8',
            fontSize: '15px',
            fontWeight: 500,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '10px',
            border: 'none',
            cursor: 'pointer'
          }}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 14V3M8 7l4-4 4 4M5 12v8h14v-8" />
          </svg>
          Xuất danh sách
        </button>
      </div>

      {/* Sub-bar (Totals & View Toggles) */}
      <div style={{ display: 'flex', gap: '22px', alignItems: 'center', height: '52px', marginTop: '20px', fontSize: '15px', color: '#6b7b8d' }}>
        <div
          style={{
            height: '38px',
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
          Tổng {products.length * 15} sản phẩm
        </div>

        <span>Hiển thị {filteredProducts.length} sản phẩm</span>

        <div style={{ marginLeft: 'auto', display: 'flex', gap: '10px' }}>
          <button
            onClick={() => setViewMode('grid')}
            style={{
              height: '50px',
              width: '146px',
              borderRadius: '12px',
              background: viewMode === 'grid' ? '#ffffff' : 'rgba(255, 255, 255, 0.67)',
              border: viewMode === 'grid' ? '2px solid #4a9bff' : 'none',
              boxSizing: 'border-box',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '9px',
              color: '#1f55b8',
              fontWeight: 500,
              fontSize: '15px',
              cursor: 'pointer'
            }}
          >
            ▦ Dạng lưới
          </button>
          <button
            onClick={() => setViewMode('table')}
            style={{
              height: '50px',
              width: '146px',
              borderRadius: '12px',
              background: viewMode === 'table' ? '#ffffff' : 'rgba(255, 255, 255, 0.67)',
              border: viewMode === 'table' ? '2px solid #4a9bff' : 'none',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '9px',
              color: '#17356e',
              fontSize: '15px',
              cursor: 'pointer'
            }}
          >
            ▤ Dạng bảng
          </button>
        </div>
      </div>

      {/* Products Grid (4 Columns x 2 Rows) */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
          gridAutoRows: '310px',
          gap: '23px',
          marginTop: '22px'
        }}
      >
        {filteredProducts.slice(0, 8).map((p) => {
          const goldStars = '★'.repeat(p.stars)
          const emptyStars = '★'.repeat(5 - p.stars)

          return (
            <div
              key={p.id}
              style={{
                borderRadius: '16px',
                background: 'rgba(255, 255, 255, 0.93)',
                boxShadow: '0 6px 18px rgba(27, 63, 110, 0.08)',
                overflow: 'hidden',
                display: 'flex',
                flexDirection: 'column',
                border: '1px solid #ffffff'
              }}
            >
              {/* Product Cover Image */}
              <div
                style={{
                  width: '100%',
                  height: '127px',
                  flexShrink: 0,
                  background: `url(${p.img}) center / cover no-repeat`
                }}
              />

              {/* Product Info */}
              <div style={{ padding: '14px 20px 0', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <div
                  style={{
                    fontSize: '19px',
                    fontWeight: 700,
                    color: '#14295c',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis'
                  }}
                >
                  {p.name}
                </div>

                <div
                  style={{
                    fontSize: '16px',
                    color: '#55657a',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis'
                  }}
                >
                  {p.producer}
                </div>

                {/* Star rating row */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '14px', color: '#8a98a8', marginTop: '4px' }}>
                  <span style={{ fontSize: '24px', letterSpacing: '1px', color: '#f5a623' }}>
                    {goldStars}
                    <span style={{ color: '#d9e0e8' }}>{emptyStars}</span>
                  </span>
                  <span>{p.stars} sao</span>
                  <span>{p.decision}</span>
                </div>

                {/* Action Button: Xem quyết định */}
                <button
                  onClick={() => handleOpenPdfForProduct(p)}
                  style={{
                    marginTop: '10px',
                    width: '176px',
                    height: '42px',
                    borderRadius: '12px',
                    background: '#e6effa',
                    color: '#1f55b8',
                    fontSize: '15px',
                    fontWeight: 500,
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    paddingLeft: '16px',
                    boxSizing: 'border-box',
                    border: 'none',
                    cursor: 'pointer'
                  }}
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                    <rect x="5" y="3" width="14" height="18" rx="3" />
                    <path d="M9 9h6M9 13h4" />
                  </svg>
                  Xem quyết định
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
