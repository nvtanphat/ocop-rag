import { useEffect } from 'react'
import { X, ExternalLink, Download, FileText, BookmarkCheck } from 'lucide-react'
import { api, type Source } from './api'
import { sourceTitle } from './catalog'

interface PdfViewerModalProps {
  source: Source | null
  page: number
  bbox?: number[] | null
  onClose: () => void
}

export default function PdfViewerModal({ source, page, bbox, onClose }: PdfViewerModalProps) {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  if (!source) return null

  const title = sourceTitle(source)
  const pdfUrl = api.pdf(source.source_id, page)

  return (
    <div 
      className="modal-backdrop"
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: 'rgba(5, 9, 17, 0.75)',
        backdropFilter: 'blur(10px)',
        zIndex: 999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
        boxSizing: 'border-box'
      }}
      role="dialog"
      aria-modal="true"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div 
        style={{
          width: '100%',
          maxWidth: '1280px',
          height: '92vh',
          backgroundColor: '#0c121e',
          borderRadius: 20,
          boxShadow: '0 30px 80px rgba(0, 0, 0, 0.8), 0 0 0 1px rgba(255, 255, 255, 0.1)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        {/* Modal Header */}
        <div 
          style={{
            height: 64,
            padding: '0 24px',
            backgroundColor: '#0f172a',
            borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flex: 'none'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, minWidth: 0 }}>
            <div 
              style={{
                width: 38,
                height: 38,
                borderRadius: 10,
                backgroundColor: 'rgba(16, 185, 129, 0.15)',
                color: '#10b981',
                border: '1px solid rgba(16, 185, 129, 0.3)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flex: 'none'
              }}
            >
              <FileText size={20} />
            </div>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: '#f8fafc', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {title}
              </div>
              <div style={{ fontSize: 12.5, color: '#94a3b8', display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ fontFamily: 'monospace', color: '#cbd5e1' }}>{source.document_number || source.filename}</span>
                <span>•</span>
                <span style={{ color: '#38bdf8', fontWeight: 600 }}>Trang {page} / {source.page_count || '—'}</span>
                {bbox && (
                  <>
                    <span>•</span>
                    <span style={{ 
                      color: '#34d399', 
                      background: 'rgba(16, 185, 129, 0.15)', 
                      border: '1px solid rgba(16, 185, 129, 0.3)',
                      padding: '2px 8px', 
                      borderRadius: 6, 
                      fontSize: 11, 
                      fontWeight: 600,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 4
                    }}>
                      <BookmarkCheck size={12} />
                      BBox [{bbox.join(', ')}]
                    </span>
                  </>
                )}
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <a 
              href={pdfUrl}
              download={source.filename}
              style={{
                height: 36,
                padding: '0 14px',
                borderRadius: 10,
                backgroundColor: 'rgba(255, 255, 255, 0.06)',
                border: '1px solid rgba(255, 255, 255, 0.12)',
                color: '#e2e8f0',
                fontSize: 13,
                fontWeight: 600,
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                transition: 'all 0.15s ease'
              }}
              title="Tải xuống PDF"
            >
              <Download size={14} />
              <span>Tải về</span>
            </a>
            <a 
              href={pdfUrl}
              target="_blank"
              rel="noreferrer"
              style={{
                height: 36,
                padding: '0 14px',
                borderRadius: 10,
                backgroundColor: 'rgba(16, 185, 129, 0.15)',
                border: '1px solid rgba(16, 185, 129, 0.3)',
                color: '#34d399',
                fontSize: 13,
                fontWeight: 600,
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                transition: 'all 0.15s ease'
              }}
              title="Mở toàn màn hình trong tab mới"
            >
              <ExternalLink size={14} />
              <span>Mở tab mới</span>
            </a>
            <button 
              onClick={onClose}
              style={{
                width: 36,
                height: 36,
                borderRadius: 10,
                border: '1px solid rgba(255, 255, 255, 0.1)',
                backgroundColor: 'rgba(255, 255, 255, 0.05)',
                color: '#94a3b8',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: 'pointer',
                transition: 'all 0.18s'
              }}
              aria-label="Đóng cửa sổ PDF"
              title="Đóng (Esc)"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* PDF Iframe */}
        <div style={{ flex: 1, backgroundColor: '#1e293b', position: 'relative' }}>
          <iframe 
            src={pdfUrl}
            title={`${title} - Trang ${page}`}
            style={{
              width: '100%',
              height: '100%',
              border: 'none',
              backgroundColor: '#0f172a'
            }}
          />
        </div>
      </div>
    </div>
  )
}
