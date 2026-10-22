import { useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, ExternalLink, X } from 'lucide-react'
import type { Citation, Source } from './api'

type Box = [number, number, number, number]
const BASE = '/api/ocop'

function boxesOn(page: number, spans: Citation['source_spans'], key: 'bbox' | 'table_bbox' = 'bbox'): Box[] {
  return (spans || []).filter(s => s.pdf_page === page && Array.isArray(s[key]) && s[key]!.length === 4).map(s => s[key] as Box)
}

export function evidenceUrl(citation: Citation, crop: boolean): string {
  const params = new URLSearchParams()
  const own = boxesOn(citation.pdf_page, citation.source_spans)
  if (!own.length && citation.bbox) own.push(citation.bbox)
  own.forEach(b => params.append('box', b.join(',')))
  boxesOn(citation.pdf_page, citation.context_source_spans).forEach(b => params.append('context', b.join(',')))
  if (citation.source_sha256) params.set('sha', citation.source_sha256)
  params.set('dpi', crop ? '130' : '100')
  if (crop) params.set('crop', 'true')
  return `${BASE}/sources/${encodeURIComponent(citation.source_id)}/pages/${citation.pdf_page}/evidence.png?${params}`
}

/** Click a citation → the cited page region from the locked PDF, evidence amber and structural context blue. */
export default function EvidenceViewer({ citation, index, source, title, openPdf, onClose }: {
  citation: Citation; index: number; source?: Source; title: string
  openPdf: (source: Source, page?: number) => void; onClose: () => void
}) {
  const [crop, setCrop] = useState(true)
  const [state, setState] = useState<'loading' | 'ready' | 'failed'>('loading')
  useEffect(() => { setState('loading') }, [crop, citation])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const verified = citation.review_status === 'verified'
  const hasContext = boxesOn(citation.pdf_page, citation.context_source_spans).length > 0
  return <div className="ocop-evidence-overlay" role="dialog" aria-modal="true" aria-label={`Bằng chứng S${index + 1}`}>
    <div className="ocop-evidence-panel">
      <header>
        <div><strong>S{index + 1} · {title}</strong><small>PDF trang {citation.pdf_page}</small></div>
        <button aria-label="Đóng" onClick={onClose}><X size={18}/></button>
      </header>
      <div className={verified ? 'ocop-evidence-status ok' : 'ocop-evidence-status warn'}>
        {verified ? <CheckCircle2 size={15}/> : <AlertTriangle size={15}/>}
        {verified ? 'Đã được con người xác minh' : 'Trích xuất tự động — chưa duyệt; hãy đối chiếu vùng được tô với PDF gốc'}
      </div>
      <div className="ocop-evidence-legend"><span className="amber"/> Bằng chứng được trích{hasContext && <><span className="blue"/> Ngữ cảnh cấu trúc (điều/khoản cha)</>}</div>
      <div className="ocop-evidence-image">
        {state === 'loading' && <p role="status">Đang dựng ảnh từ PDF gốc…</p>}
        {state === 'failed' && <p role="alert">Không dựng được ảnh bằng chứng (PDF không khớp khóa SHA-256 hoặc vùng không hợp lệ).</p>}
        <img alt={`Trang ${citation.pdf_page} với vùng bằng chứng S${index + 1}`} src={evidenceUrl(citation, crop)}
          style={{ display: state === 'ready' ? 'block' : 'none' }}
          onLoad={() => setState('ready')} onError={() => setState('failed')}/>
      </div>
      <footer>
        <button onClick={() => setCrop(!crop)}>{crop ? 'Xem cả trang' : 'Phóng to vùng bằng chứng'}</button>
        {source && <button onClick={() => openPdf(source, citation.pdf_page)}><ExternalLink size={14}/> Mở PDF gốc trang {citation.pdf_page}</button>}
        {citation.source_sha256 && <code title="SHA-256 của PDF nguồn">{citation.source_sha256.slice(0, 12)}…</code>}
      </footer>
    </div>
  </div>
}
