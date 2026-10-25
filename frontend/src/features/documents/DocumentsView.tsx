import type { Source } from '../../api/client'

export function DocumentsView({ sources, search, loaded, onOpen }: {
  sources: Source[]; search: string; loaded: boolean; onOpen: (source: Source) => void
}) {
  const filtered = sources.filter(s => `${s.document_number} ${s.filename} ${s.jurisdiction}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()))
  return <div className="records">
    {loaded && !filtered.length && <p>{search ? 'Không tìm thấy tài liệu phù hợp.' : 'Chưa có tài liệu trong danh mục.'}</p>}
    {filtered.map(source => <article key={source.source_id}>
      <h3>{source.document_number || source.filename}</h3>
      <p>{source.filename}</p><p>{source.jurisdiction || 'Chưa có thông tin phạm vi'} · {source.page_count} trang đã xử lý</p>
      <small>{source.source_verification}</small><button onClick={() => onOpen(source)}>Mở PDF</button>
    </article>)}
  </div>
}
