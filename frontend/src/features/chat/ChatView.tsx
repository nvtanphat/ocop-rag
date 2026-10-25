import type { AskResult, Citation } from '../../api/client'
import { CitationText } from './CitationText'

export type Message = { question: string; answer?: AskResult; error?: string }

export function ChatView({ messages, busy, question, setQuestion, useLlm, setUseLlm, onSend, onOpen }: {
  messages: Message[]; busy: boolean; question: string; setQuestion: (value: string) => void
  useLlm: boolean; setUseLlm: (value: boolean) => void; onSend: () => void; onOpen: (citation: Citation) => void
}) {
  return <>
    <h2>Hỏi đáp OCOP</h2>
    {!messages.length && <p>Đặt câu hỏi để tra cứu tài liệu. Trích dẫn mở trang PDF và vùng bằng chứng gốc.</p>}
    <div aria-live="polite" className="messages">
      {messages.map((message, index) => <article key={index}>
        <h3>{message.question}</h3>
        {message.error && <p role="alert" className="error">{message.error}</p>}
        {message.answer && <>
          <small>Trạng thái trả lời: {message.answer.status} · Corpus: {message.answer.corpus_version || 'chưa có'}</small>
          <CitationText text={message.answer.answer} citations={message.answer.citations} onOpen={onOpen} />
          <div className="citations">{message.answer.citations.map((citation, i) => <button key={i}
            onClick={() => onOpen(citation)}>[S{i + 1}] {citation.source_id} · Trang {citation.pdf_page}
            <small>{citation.review_status === 'verified' ? 'Đã xác minh' : 'Nguồn chưa xác minh'}</small>
          </button>)}</div>
          {!!message.answer.tools_used.length && <details><summary>Truy vết công cụ</summary>
            <ul>{message.answer.tools_used.map((tool, i) => <li key={i}>{tool}</li>)}</ul>
          </details>}
        </>}
      </article>)}
      {busy && <p role="status">Đang tìm bằng chứng…</p>}
    </div>
    <form onSubmit={event => { event.preventDefault(); onSend() }}>
      <label htmlFor="question">Câu hỏi</label>
      <textarea id="question" maxLength={4000} value={question} onChange={event => setQuestion(event.target.value)}
        placeholder="Nhập câu hỏi về OCOP" required />
      <label className="llm-option"><input type="checkbox" checked={useLlm} onChange={event => setUseLlm(event.target.checked)} /> Sinh câu trả lời bằng mô hình ngôn ngữ</label>
      <button type="submit" disabled={busy || !question.trim()}>Gửi câu hỏi</button>
    </form>
  </>
}
