import { useEffect, useState } from 'react'
import { api, type Citation } from '../api/client'

export function PortalPdfModal({ citation, onClose }: { citation: Citation; onClose: () => void }) {
  const [page, setPage] = useState(citation.pdf_page)
  const [highlight, setHighlight] = useState(true)
  const [error, setError] = useState(false)
  useEffect(() => {
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    document.addEventListener('keydown', escape)
    return () => document.removeEventListener('keydown', escape)
  }, [onClose])
  const imageUrl = api.evidence(citation, page, highlight)
  useEffect(() => { setError(false) }, [imageUrl])
  return <div className="evidence-backdrop">
    <section role="dialog" aria-modal="true" aria-label="Bằng chứng PDF" className="evidence-viewer">
      <header><h2>{citation.source_id} · Trang {page}</h2><button autoFocus onClick={onClose}>Đóng</button></header>
      <div className="evidence-controls">
        <button disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Trang trước</button>
        <button onClick={() => setPage(p => p + 1)}>Trang sau</button>
        <button onClick={() => setPage(citation.pdf_page)}>Về trích dẫn</button>
        <label><input type="checkbox" checked={highlight} onChange={event => setHighlight(event.target.checked)} /> Hiện vùng bằng chứng</label>
        <a href={api.pdf(citation.source_id, page)} target="_blank" rel="noreferrer">Mở PDF gốc</a>
      </div>
      <p>Evidence ID: {citation.evidence_unit_id || 'Không chọn bằng chứng cụ thể'}</p>
      <p>BBox: {JSON.stringify(citation.bbox || citation.table_bbox || null)}</p>
      <small>SHA-256: {citation.source_sha256 || 'Chưa có trong trích dẫn'}</small>
      {error && <p role="alert" className="error">Không tải được trang bằng chứng. Kiểm tra kết nối, số trang và mã SHA-256.</p>}
      <div className="evidence-image"><img key={imageUrl} src={imageUrl} alt={`Trang ${page} của ${citation.source_id}, vùng bằng chứng được đánh dấu`} onError={() => setError(true)} /></div>
    </section>
  </div>
}
