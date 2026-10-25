import { useEffect, useState } from 'react'
import { api, type AskResult, type Citation, type Health, type ReferenceResponse, type Source } from '../ocop/api/client'
import { CitationText } from '../ocop/portal/CitationText'
import { PortalPdfModal } from '../ocop/portal/PortalPdfModal'
import '../styles/workspace.css'

type View = 'chat' | 'documents' | 'criteria' | 'products'
type Message = { question: string; answer?: AskResult; error?: string }
const labels: Record<View, string> = { chat: 'Hỏi đáp', documents: 'Tài liệu', criteria: 'Tiêu chí', products: 'Sản phẩm' }
const errorText = (error: unknown) => error instanceof Error ? error.message : 'Không tải được dữ liệu OCOP.'

export default function OcopPortal() {
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
    <header className="workspace-header">
      <div><h1>OCOP GraphRAG</h1><p>Tra cứu có căn cứ từ tài liệu gốc</p></div>
      <div role="status" className="corpus-status">
        {errors.health || (loading ? 'Đang kết nối…' : `Backend: ${health?.status || 'không rõ'}`)}
        {health && <small>Corpus: {health.corpus_version || 'chưa dựng'} · {health.sources_registered} nguồn · {health.pages} trang đã xử lý</small>}
      </div>
      <button onClick={() => void load()} disabled={loading}>Tải lại dữ liệu</button>
    </header>
    <div className="workspace-layout">
      <nav aria-label="Điều hướng">
        {(Object.keys(labels) as View[]).map(key => <button key={key} aria-current={view === key ? 'page' : undefined}
          onClick={() => { setView(key); setSearch('') }}>{labels[key]}</button>)}
        <button disabled={busy} onClick={() => { setMessages([]); setSessionId(crypto.randomUUID()); setView('chat') }}>Cuộc trò chuyện mới</button>
      </nav>
      <main>
        {view === 'chat' ? <>
          <h2>Hỏi đáp OCOP</h2>
          {!messages.length && <p>Đặt câu hỏi để tra cứu tài liệu. Trích dẫn mở trang PDF và vùng bằng chứng gốc.</p>}
          <div aria-live="polite" className="messages">
            {messages.map((message, index) => <article key={index}>
              <h3>{message.question}</h3>
              {message.error && <p role="alert" className="error">{message.error}</p>}
              {message.answer && <>
                <small>Trạng thái trả lời: {message.answer.status} · Corpus: {message.answer.corpus_version || 'chưa có'}</small>
                <CitationText text={message.answer.answer} citations={message.answer.citations} onOpen={setSelected} />
                <div className="citations">{message.answer.citations.map((citation, i) => <button key={i}
                  onClick={() => setSelected(citation)}>[S{i + 1}] {citation.source_id} · Trang {citation.pdf_page}
                  <small>{citation.review_status === 'verified' ? 'Đã xác minh' : 'Nguồn chưa xác minh'}</small>
                </button>)}</div>
              </>}
            </article>)}
            {busy && <p role="status">Đang tìm bằng chứng…</p>}
          </div>
          <form onSubmit={event => { event.preventDefault(); void send() }}>
            <label htmlFor="question">Câu hỏi</label>
            <textarea id="question" maxLength={4000} value={question} onChange={event => setQuestion(event.target.value)}
              placeholder="Nhập câu hỏi về OCOP" required />
            <label className="llm-option"><input type="checkbox" checked={useLlm} onChange={event => setUseLlm(event.target.checked)} /> Sinh câu trả lời bằng mô hình ngôn ngữ</label>
            <button type="submit" disabled={busy || !question.trim()}>Gửi câu hỏi</button>
          </form>
        </> : <>
          <h2>{labels[view]}</h2>
          <label htmlFor="search">Tìm trong danh sách</label>
          <input id="search" type="search" value={search} onChange={event => setSearch(event.target.value)} />
          {loading && <p role="status">Đang tải…</p>}
          {errors[view] && <p role="alert" className="error">{errors[view]}</p>}
          {view === 'documents' ? <div className="records">
            {!loading && !errors.documents && !sources.length && <p>Chưa có tài liệu trong danh mục.</p>}
            {sources.filter(s => `${s.document_number} ${s.filename} ${s.jurisdiction}`.toLocaleLowerCase().includes(search.toLocaleLowerCase())).map(source =>
              <article key={source.source_id}><h3>{source.document_number || source.filename}</h3>
                <p>{source.filename}</p><p>{source.jurisdiction || 'Chưa có thông tin phạm vi'} · {source.page_count} trang đã xử lý</p>
                <small>{source.source_verification}</small><button onClick={() => openDocument(source)}>Mở PDF</button>
              </article>)}
          </div> : <div className="records">
            {!loading && !errors[view] && reference && !reference.items.length && <p>Chưa có dữ liệu xác minh.</p>}
            {reference?.items.filter(item => item.label.toLocaleLowerCase().includes(search.toLocaleLowerCase())).map(item =>
              <article key={item.id}><h3>{item.label}</h3><small>Corpus: {reference.corpus_version}</small>
                {item.citations.map((citation, i) => <button key={i} onClick={() => setSelected(citation)}>Nguồn {citation.source_id} · Trang {citation.pdf_page}</button>)}
              </article>)}
          </div>}
        </>}
      </main>
    </div>
    {selected && <PortalPdfModal citation={selected} onClose={() => setSelected(null)} />}
  </div>
}
