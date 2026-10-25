import type { Health } from '../api/client'

export function TopHeader({ health, loading, error, onReload }: {
  health: Health | null; loading: boolean; error?: string; onReload: () => void
}) {
  return <header className="workspace-header">
    <div><h1>OCOP GraphRAG</h1><p>Tra cứu có căn cứ từ tài liệu gốc</p></div>
    <div role="status" className="corpus-status">
      {error || (loading ? 'Đang kết nối…' : `Backend: ${health?.status || 'không rõ'}`)}
      {health && <small>Corpus: {health.corpus_version || 'chưa dựng'} · {health.sources_registered} nguồn · {health.pages} trang đã xử lý</small>}
    </div>
    <button onClick={onReload} disabled={loading}>Tải lại dữ liệu</button>
  </header>
}
