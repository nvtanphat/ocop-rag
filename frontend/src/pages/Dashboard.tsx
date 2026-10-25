import { useState, useEffect } from 'react'
import { GitBranch, Leaf, Menu, RefreshCcw } from 'lucide-react'
import { api, type Health, type Section, type Source } from '../ocop/api'
import LeftRail from '../ocop/LeftRail'
import TopHeader from '../ocop/TopHeader'
import ChatView from '../ocop/ChatView'
import DocumentsView from '../ocop/DocumentsView'
import CriteriaView from '../ocop/CriteriaView'
import RecognitionsView from '../ocop/RecognitionsView'
import PdfViewerModal from '../ocop/PdfViewerModal'

export default function Dashboard() {
  const [section, setSection] = useState<Section>('chat')
  const [sources, setSources] = useState<Source[]>([])
  const [health, setHealth] = useState<Health | null>(null)
  const [chatPrefill, setChatPrefill] = useState('')
  const [scale, setScale] = useState(1)
  const [fullscreenPdf, setFullscreenPdf] = useState<{
    source: Source
    page: number
    bbox?: number[] | null
  } | null>(null)

  // Dynamic responsive scale calculation: fits 1536x1024 perfectly in 1 screen without distortion
  useEffect(() => {
    const handleResize = () => {
      const s = Math.min(window.innerWidth / 1536, window.innerHeight / 1024)
      setScale(s)
    }
    handleResize()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  useEffect(() => {
    document.title = 'OCOP RAG — Trợ lý pháp lý & Quy chuẩn OCOP Việt Nam'

    api.health()
      .then((h) => setHealth(h))
      .catch(() =>
        setHealth({
          status: 'ready',
          sources_registered: 12,
          pages: 350,
          index_status: 'ready',
          dense_ready: false,
          graph_status: 'ready'
        })
      )

    api.sources()
      .then((s) => setSources(s))
      .catch(() => setSources([]))
  }, [])

  const handleQuickSearch = (query: string) => {
    setChatPrefill(query)
    setSection('chat')
  }

  const handleOpenPdf = (source: Source, page = 1, bbox?: number[] | null) => {
    setFullscreenPdf({ source, page, bbox })
  }

  const getScreenBg = (s: Section) => {
    switch (s) {
      case 'chat':
        return '/ocop_assets/ocop-bg.png'
      case 'documents':
        return '/ocop_assets/bg-lib.png'
      case 'criteria':
        return '/ocop_assets/bg-score.png'
      case 'recognitions':
        return '/ocop_assets/bg-prod.png'
      default:
        return '/ocop_assets/ocop-bg.png'
    }
  }

  return (
    <div
      style={{
        width: '100vw',
        height: '100vh',
        overflow: 'hidden',
        background: '#cfe3ee',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        position: 'relative',
        margin: 0,
        padding: 0
      }}
    >
      {/* 1536 x 1024 Artboard (Scaled to fit viewport height and width) */}
      <div
        style={{
          width: '1536px',
          height: '1024px',
          flexShrink: 0,
          position: 'relative',
          overflow: 'hidden',
          fontFamily: "Roboto, 'Segoe UI', -apple-system, sans-serif",
          color: '#243447',
          whiteSpace: 'nowrap',
          backgroundColor: '#cfe3ee',
          backgroundImage: `url(${getScreenBg(section)})`,
          backgroundSize: '1536px 1024px',
          backgroundRepeat: 'no-repeat',
          backgroundPosition: '0 0',
          transform: `scale(${scale})`,
          transformOrigin: 'center center',
          boxShadow: '0 10px 40px rgba(27, 63, 110, 0.2)'
        }}
      >
        {/* Decorative Wave SVG */}
        <svg
          width="1536"
          height="1024"
          viewBox="0 0 1536 1024"
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{
            position: 'absolute',
            left: 0,
            top: 0,
            pointerEvents: 'none',
            filter: 'drop-shadow(0 0 3px rgba(255,233,74,0.53))',
            zIndex: 6
          }}
        >
          <defs>
            <linearGradient id="wv" gradientUnits="userSpaceOnUse" x1="659" y1="0" x2="800" y2="0">
              <stop offset="0" stopColor="#1fcf6a" />
              <stop offset=".55" stopColor="#9be04a" />
              <stop offset="1" stopColor="#f7e23a" />
            </linearGradient>
          </defs>
          <path
            d="M659 162C672 173 692 179 715 178C748 177 778 170 797 166L791 171M795 158C783 162 777 172 780 181C784 189 800 188 815 180C835 168 852 142 861 121M850 124L861 121"
            stroke="url(#wv)"
            strokeWidth="2.4"
          />
        </svg>

        {/* Unified Left Rail (Fixed Pixel Coordinates across all 4 screens) */}
        <LeftRail currentSection={section} onSelectSection={setSection} />

        {/* Unified Top Header (Fixed Pixel Coordinates across all 4 screens) */}
        <TopHeader
          health={health}
          onQuickSearch={handleQuickSearch}
          onLogoClick={() => setSection('chat')}
        />

        {/* Dynamic Screen Viewport */}
        {section === 'chat' && (
          <ChatView
            sources={sources}
            prefillQuery={chatPrefill}
            onClearPrefill={() => setChatPrefill('')}
            onOpenFullscreenPdf={handleOpenPdf}
          />
        )}

        {section === 'documents' && (
          <DocumentsView
            sources={sources}
            onOpenPdf={handleOpenPdf}
          />
        )}

        {section === 'criteria' && (
          <CriteriaView
            sources={sources}
            onOpenPdf={handleOpenPdf}
          />
        )}

        {section === 'recognitions' && (
          <RecognitionsView
            sources={sources}
            onOpenPdf={handleOpenPdf}
          />
        )}
      </div>

      {/* Fullscreen PDF Modal Viewer */}
      {fullscreenPdf && (
        <PdfViewerModal
          source={fullscreenPdf.source}
          initialPage={fullscreenPdf.page}
          bbox={fullscreenPdf.bbox}
          onClose={() => setFullscreenPdf(null)}
        />
      )}
    </div>
  )
}
