import type { Citation, ReferenceResponse } from '../../api/client'

export function ReferenceView({ data, search, loaded, onOpen }: {
  data: ReferenceResponse | null; search: string; loaded: boolean; onOpen: (citation: Citation) => void
}) {
  const filtered = data?.items.filter(item => item.label.toLocaleLowerCase().includes(search.toLocaleLowerCase())) || []
  return <div className="records">
    {loaded && data && !data.items.length && <p>Chưa có dữ liệu xác minh.</p>}
    {loaded && !!data?.items.length && !filtered.length && <p>Không tìm thấy dữ liệu phù hợp.</p>}
    {filtered.map(item => <article key={item.id}><h3>{item.label}</h3><small>Corpus: {data?.corpus_version}</small>
      {item.citations.map((citation, i) => <button key={i} onClick={() => onOpen(citation)}>Nguồn {citation.source_id} · Trang {citation.pdf_page}</button>)}
    </article>)}
  </div>
}
