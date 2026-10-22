import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { AlertTriangle, ArrowRight, BookOpen, CheckCircle2, Copy, ExternalLink, Leaf, RotateCcw, SendHorizontal, SlidersHorizontal, Sparkles, UserRound, X } from 'lucide-react'
import { api } from './api'
import type { AskResult, Source } from './api'
import { samplePrompts, sourceTitle } from './catalog'
import EvidenceViewer from './EvidenceViewer'
import type { Citation } from './api'

const statusLabel = (status: string) => ({
  generated_claims_verified: 'Đã xác minh',
  partial_claims_verified: 'Xác minh một phần',
  generated_unverified_claims: 'Nguồn chưa duyệt',
  partial_debug_corpus: 'Corpus mẫu (chưa duyệt)',
  retrieval_only: 'Chỉ trích xuất',
  citation_verification_failed: 'Chưa qua kiểm chứng — chỉ hiện trích xuất',
  insufficient_evidence: 'Chưa đủ bằng chứng',
  clarify: 'Cần làm rõ',
  out_of_scope: 'Ngoài phạm vi',
} as Record<string, string>)[status] || status.replace(/_/g, ' ')

type Message = { id: number; role: 'user' | 'assistant'; content: string; result?: AskResult }
export default function Chat({ sources, denseReady, messages, setMessages, openPdf, prefill, clearPrefill }: {
  sources: Source[]; denseReady: boolean; messages: Message[]; setMessages: React.Dispatch<React.SetStateAction<Message[]>>
  openPdf: (source: Source, page?: number) => void; prefill: string; clearPrefill: () => void
}) {
  const [draft, setDraft] = useState('')
  useEffect(() => { if(prefill){setDraft(prefill);clearPrefill()} }, [prefill,clearPrefill])
  const [mode, setMode] = useState<'sparse' | 'hybrid'>('sparse')
  const [llm, setLlm] = useState(false)
  const [advanced, setAdvanced] = useState(false)
  const [busy, setBusy] = useState(false)
  const [viewing, setViewing] = useState<{ citation: Citation; index: number } | null>(null)
  const [error, setError] = useState('')
  const abort = useRef<AbortController | null>(null)
  const conversationId = useRef(crypto.randomUUID())
  const bottom = useRef<HTMLDivElement | null>(null)
  useEffect(() => bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }), [messages, busy])
  useEffect(() => () => abort.current?.abort(), [])
  const submit = async (text: string) => {
    const query = text.trim(); if (!query || busy) return
    const controller = new AbortController(); abort.current = controller
    setBusy(true); setError(''); setDraft('')
    setMessages(previous => [...previous, { id: Date.now(), role: 'user', content: query }])
    try {
      const result = await api.ask(query, mode, llm, conversationId.current, controller.signal)
      setMessages(previous => [...previous, { id: Date.now() + 1, role: 'assistant', content: result.answer, result }])
    } catch (e) {
      if (!(e instanceof Error && e.name === 'AbortError')) setError(e instanceof Error ? e.message : 'Không thể truy vấn OCOP.')
    } finally { setBusy(false); abort.current = null }
  }
  return <section className="ocop-chat-layout" aria-label="Trợ lý OCOP">
    <div className="ocop-chat-top"><div><div className="ocop-eyebrow">TRỢ LÝ TRI THỨC</div><h1>Hỏi đáp về OCOP</h1><p>Tra cứu có căn cứ từ các văn bản, bảng tiêu chí và dữ liệu công nhận.</p></div>
      <button className="ocop-button-quiet" onClick={() => { setMessages([]); conversationId.current = crypto.randomUUID() }}><RotateCcw size={15}/> Xóa hội thoại</button>
    </div>
    <div className="ocop-chat-scroll">
      {messages.length === 0 && <div className="ocop-chat-welcome">
        <div className="ocop-chat-emblem"><Sparkles size={27}/></div>
        <span className="ocop-eyebrow">TRỢ LÝ OCOP · VIỆT NAM</span>
        <h2>Bạn muốn tìm hiểu điều gì<br/><em>về chương trình OCOP?</em></h2>
        <p>Hỏi về phân loại sản phẩm, quy trình đánh giá, bộ tiêu chí, biểu mẫu hoặc kết quả công nhận theo địa phương.</p>
        <div className="ocop-suggestion-grid">{samplePrompts.map(s => <button key={s.title} className="ocop-suggestion" onClick={() => void submit(s.detail)}><span>{s.tag}</span><strong>{s.detail}</strong><ArrowRight size={16}/></button>)}</div>
      </div>}
      {messages.map(message => <div className={`ocop-message ${message.role}`} key={message.id}>
        <div className="ocop-message-avatar">{message.role === 'assistant' ? <Leaf size={18}/> : <UserRound size={18}/>}</div>
        <div className="ocop-message-main"><div className="ocop-message-author">{message.role === 'assistant' ? 'Trợ lý OCOP' : 'Bạn'}</div>
          <div className="ocop-markdown"><ReactMarkdown>{message.content}</ReactMarkdown></div>
          {message.result && <>
            <div className="ocop-response-meta"><span className="ocop-subtle-chip">{message.result.intent.replace(/_/g,' ')}</span><span className="ocop-subtle-chip" title="Trạng thái kiểm chứng của câu trả lời">{statusLabel(message.result.status)}</span><span>{message.result.tools_used.length} công cụ truy xuất</span><span>{message.result.workflow_engine}</span>
              <button title="Sao chép câu trả lời" onClick={() => void navigator.clipboard?.writeText(message.content)}><Copy size={14}/></button>
            </div>
            {message.result.citations.length > 0 && <div className="ocop-citations"><div className="ocop-citations-title"><BookOpen size={15}/> Bằng chứng nguồn · {message.result.citations.length}</div>
              <div className="ocop-citation-list">{message.result.citations.map((citation, i) => {
                const source = sources.find(s => s.source_id === citation.source_id)
                return <button key={`${citation.evidence_unit_id || citation.source_id}:${i}`} className="ocop-citation" onClick={() => setViewing({ citation, index: i })}>
                  <span className="ocop-source-index">S{i + 1}</span><span className="ocop-citation-name"><strong>{source ? sourceTitle(source) : citation.source_id}</strong><small>PDF trang {citation.pdf_page} · {citation.review_status === 'verified' ? 'Đã xác minh' : 'Trích xuất tự động — chưa duyệt'}</small></span><ExternalLink size={15}/>
                </button>
              })}</div>
            </div>}
            {message.result.citations.some(c => c.review_status !== 'verified') && <div className="ocop-inline-warning"><AlertTriangle size={15}/> Có bằng chứng OCR chưa được kiểm tra thủ công. Vui lòng đối chiếu PDF gốc.</div>}
          </>}
        </div></div>)}
      {busy && <div className="ocop-message assistant"><div className="ocop-message-avatar"><Leaf size={18}/></div><div className="ocop-message-main"><div className="ocop-message-author">Trợ lý OCOP</div><div className="ocop-thinking"><span/><span/><span/> Đang tra cứu bằng chứng từ corpus...</div></div></div>}
      {error && <div className="ocop-chat-error"><AlertTriangle size={17}/>{error}<button aria-label="Đóng cảnh báo" onClick={() => setError('')}><X size={15}/></button></div>}
      <div ref={bottom}/>
    </div>
    <div className="ocop-composer-wrap">
      {advanced && <div className="ocop-chat-options"><div><strong>Chế độ truy xuất</strong><div className="ocop-segmented"><button className={mode === 'sparse' ? 'active' : ''} onClick={() => setMode('sparse')}>BM25</button><button disabled={!denseReady} className={mode === 'hybrid' ? 'active' : ''} onClick={() => setMode('hybrid')}>Hybrid {!denseReady && '· chưa có index'}</button></div></div>
        <label className="ocop-toggle-line"><input type="checkbox" checked={llm} onChange={e => setLlm(e.target.checked)}/><span>Dùng LLM để diễn giải</span><small>Theo cấu hình OCOP_ANSWER_LLM_PROVIDER của máy chủ</small></label></div>}
      <form className="ocop-composer" onSubmit={e => { e.preventDefault(); void submit(draft) }}>
        <textarea aria-label="Nhập câu hỏi OCOP" rows={2} placeholder="Nhập câu hỏi về tiêu chí, hồ sơ, quy định OCOP..." value={draft} onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void submit(draft) } }}/>
        <div className="ocop-composer-actions"><button type="button" className="ocop-advanced-btn" onClick={() => setAdvanced(!advanced)} aria-expanded={advanced}><SlidersHorizontal size={15}/> {mode === 'sparse' ? 'BM25' : 'Hybrid'} · {llm ? 'Qwen 2B' : 'Evidence-only'}</button>
          <span className="ocop-composer-hint">Enter gửi · Shift+Enter xuống dòng</span>
          <button className="ocop-send" type="submit" disabled={!draft.trim() || busy} aria-label="Gửi câu hỏi"><SendHorizontal size={18}/></button></div>
      </form>
      <div className="ocop-chat-disclaimer"><CheckCircle2 size={13}/> Công cụ hỗ trợ tra cứu, không phải kết quả công nhận OCOP chính thức.</div>
    </div>
    {viewing && <EvidenceViewer citation={viewing.citation} index={viewing.index} onClose={() => setViewing(null)} openPdf={openPdf}
      source={sources.find(s => s.source_id === viewing.citation.source_id)}
      title={(() => { const s = sources.find(x => x.source_id === viewing.citation.source_id); return s ? sourceTitle(s) : viewing.citation.source_id })()}/>}
  </section>
}
export type { Message }
