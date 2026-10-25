import { useEffect, useState } from 'react'
import { api, type Citation, type Health, type ReferenceResponse, type Source } from '../api/client'
import { ChatView, type Message } from '../features/chat/ChatView'
import { DocumentsView } from '../features/documents/DocumentsView'
import { ReferenceView } from '../features/references/ReferenceView'
import { EvidenceViewer } from '../features/pdf/EvidenceViewer'
import { TopHeader } from '../components/TopHeader'
import '../styles/workspace.css'

type View = 'chat' | 'documents' | 'criteria' | 'products'
const labels: Record<View, string> = { chat: 'Hỏi đáp', documents: 'Tài liệu', criteria: 'Tiêu chí', products: 'Sản phẩm' }
const errorText = (error: unknown) => error instanceof Error ? error.message : 'Không tải được dữ liệu OCOP.'

export default function Workspace() {
  const [view, setView] = useState<View>('chat')
  const [health, setHealth] = useState<Health | null>(null)
  const [sources, setSources] = useState<Source[]>([])
  const [criteria, setCriteria] = useState<ReferenceResponse | null>(null)
  const [products, setProducts] = useState<ReferenceResponse | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [messages, setMessages] = useState<Message[]>([])
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState(false)
  const [useLlm, setUseLlm] = useState(false)
  const [selected, setSelected] = useState<Citation | null>(null)
  const [search, setSearch] = useState('')
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID())

  const load = async () => {
    setLoading(true)
    const results = await Promise.allSettled([api.health(), api.sources(), api.criteria(), api.products()])
    const nextErrors: Record<string, string> = {}
    const [h, s, c, p] = results
    if (h.status === 'fulfilled') setHealth(h.value)
    else { setHealth(null); nextErrors.health = errorText(h.reason) }
    if (s.status === 'fulfilled') setSources(s.value)
    else { setSources([]); nextErrors.documents = errorText(s.reason) }
    if (c.status === 'fulfilled') setCriteria(c.value)
    else { setCriteria(null); nextErrors.criteria = errorText(c.reason) }
    if (p.status === 'fulfilled') setProducts(p.value)
    else { setProducts(null); nextErrors.products = errorText(p.reason) }
    setErrors(nextErrors)
    setLoading(false)
  }
  useEffect(() => { void load() }, [])

  const send = async () => {
    if (busy || !question.trim()) return
    const text = question.trim()
    setQuestion('')
    setBusy(true)
    setMessages(previous => [...previous, { question: text }])
    try {
      const answer = await api.ask({ query: text, session_id: sessionId, retrieval_mode: 'sparse', use_llm: useLlm })
      setMessages(previous => [...previous.slice(0, -1), { question: text, answer }])
    } catch (error) {
      setMessages(previous => [...previous.slice(0, -1), { question: text, error: errorText(error) }])
    } finally { setBusy(false) }
  }
  const openDocument = (source: Source) => setSelected({ source_id: source.source_id, pdf_page: 1, evidence_unit_id: null })
  const reference = view === 'criteria' ? criteria : products

  return <div className="workspace">
    <TopHeader health={health} loading={loading} error={errors.health} onReload={() => void load()} />
    <div className="workspace-layout">
      <nav aria-label="Điều hướng">
        {(Object.keys(labels) as View[]).map(key => <button key={key} aria-current={view === key ? 'page' : undefined}
          onClick={() => { setView(key); setSearch('') }}>{labels[key]}</button>)}
        <button disabled={busy} onClick={() => { setMessages([]); setSessionId(crypto.randomUUID()); setView('chat') }}>Cuộc trò chuyện mới</button>
      </nav>
      <main>
        {view === 'chat' ? <ChatView messages={messages} busy={busy} question={question} setQuestion={setQuestion}
          useLlm={useLlm} setUseLlm={setUseLlm} onSend={() => void send()} onOpen={setSelected} /> : <>
          <h2>{labels[view]}</h2>
          <label htmlFor="search">Tìm trong danh sách</label>
          <input id="search" type="search" value={search} onChange={event => setSearch(event.target.value)} />
          {loading && <p role="status">Đang tải…</p>}
          {errors[view] && <p role="alert" className="error">{errors[view]}</p>}
          {view === 'documents' ? <DocumentsView sources={sources} search={search} loaded={!loading && !errors.documents} onOpen={openDocument} />
            : <ReferenceView data={reference} search={search} loaded={!loading && !errors[view]} onOpen={setSelected} />}
        </>}
      </main>
    </div>
    {selected && <EvidenceViewer key={`${selected.source_id}:${selected.pdf_page}:${selected.evidence_unit_id}`} citation={selected} onClose={() => setSelected(null)} />}
  </div>
}
