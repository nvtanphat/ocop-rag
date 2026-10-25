import React, { useRef } from 'react'
import { IMAGES } from '../assets'
import type { ChatMessage, BotAnswer, SrcItem, ActiveView } from './types'
import { CHECK_SVG, esc } from './utils'
import { QUICK_QUESTIONS, FOLLOW_QUESTIONS, REL_DOCS, PROD_CAROUSEL } from './data'

interface PortalChatProps {
  messages: ChatMessage[]
  convoRef: React.RefObject<HTMLDivElement | null>
  isBusy: boolean
  inputQ: string
  setInputQ: (value: string) => void
  textareaRef: React.RefObject<HTMLTextAreaElement | null>
  searchMode: 'exact' | 'wide'
  setSearchMode: (mode: 'exact' | 'wide') => void
  handleSend: (text: string) => void
  copyText: (text: string) => void
  toggleLike: (index: number) => void
  toggleDislike: (index: number) => void
  toggleSave: (index: number) => void
  openGraph: (tab: 'ev' | 'doc', ans?: BotAnswer | null) => void
  openSrc: (sid: string) => void
  srcMap: Record<string, SrcItem>
  setActiveView: (view: ActiveView) => void
  toast: (msg: string) => void
}

export const PortalChat: React.FC<PortalChatProps> = ({
  messages,
  convoRef,
  isBusy,
  inputQ,
  setInputQ,
  textareaRef,
  searchMode,
  setSearchMode,
  handleSend,
  copyText,
  toggleLike,
  toggleDislike,
  toggleSave,
  openGraph,
  openSrc,
  srcMap,
  setActiveView,
  toast,
}) => {
  const carTrackRef = useRef<HTMLDivElement | null>(null)

  return (
    <>
      <section className={`cv glass chatbox ${messages.length === 0 ? 'empty' : ''}`} id="chatbox">
        {messages.length === 0 && (
          <div id="welcome">
            <img src={IMAGES.welcomeAvatar} alt="Trợ lý OCOP" />
            <h2>Xin chào, tôi giúp gì cho bạn về OCOP?</h2>
            <p>Hỏi đáp dựa trên 12 văn bản pháp quy chính thống, kèm trích dẫn đối soát PDF gốc</p>
            <div className="wsug" id="wsug">
              {QUICK_QUESTIONS.map((q, i) => (
                <button key={i} type="button" onClick={() => handleSend(q)}>
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        <div id="convo" ref={convoRef} aria-live="polite">
          {messages.map((m, idx) =>
            m.sender === 'u' ? (
              <div key={m.id} className="msg u">
                <div className="ub">
                  <div className="bub">{m.text}</div>
                  <time>{m.time}</time>
                </div>
                <svg className="uic" viewBox="0 0 24 24" fill="currentColor">
                  <circle cx="12" cy="8" r="4.2" />
                  <path d="M4 21c0-4.2 3.6-7 8-7s8 2.8 8 7z" />
                </svg>
              </div>
            ) : (
              <div key={m.id} className="msg b">
                <img className="rb" src={IMAGES.botAvatar} alt="" />
                <div className="body">
                  <div className="tools2">
                    <button type="button" onClick={() => copyText(m.text)} title="Sao chép">
                      <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                        <rect x="8" y="8" width="12" height="12" rx="2" />
                        <path d="M16 8V6a2 2 0 00-2-2H6a2 2 0 00-2 2v8a2 2 0 002 2h2" />
                      </svg>
                    </button>
                    <button type="button" className={m.liked ? 'on' : ''} onClick={() => toggleLike(idx)} title="Hữu ích">
                      <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                        <path d="M7 11v9H4v-9zM7 11l4-8c2 0 3 1.5 2.5 3.5L13 9h6a2 2 0 012 2.3l-1.2 7A2 2 0 0118 20H7" />
                      </svg>
                    </button>
                    <button type="button" className={m.disliked ? 'on' : ''} onClick={() => toggleDislike(idx)} title="Chưa tốt">
                      <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                        <path d="M7 13V4H4v9zM7 13l4 8c2 0 3-1.5 2.5-3.5L13 15h6a2 2 0 002-2.3l-1.2-7A2 2 0 0018 4H7" />
                      </svg>
                    </button>
                    <button type="button" className={m.saved ? 'on' : ''} onClick={() => toggleSave(idx)} title="Lưu">
                      <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                        <path d="M6 3h12v18l-6-4-6 4z" />
                      </svg>
                    </button>
                    <button type="button" onClick={() => openGraph('ev', m.ans)} title="Xem truy vết RAG">
                      <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                        <circle cx="12" cy="5" r="1.2" />
                        <circle cx="12" cy="12" r="1.2" />
                        <circle cx="12" cy="19" r="1.2" />
                      </svg>
                    </button>
                  </div>

                  {m.verified ? (
                    <span className="verify">
                      Đã tìm thấy câu trả lời <span dangerouslySetInnerHTML={{ __html: CHECK_SVG }} />
                    </span>
                  ) : (
                    <span className="verify warn">Nội dung minh họa, chưa xác minh</span>
                  )}

                  <div dangerouslySetInnerHTML={{ __html: m.html || '' }} />

                  {m.sources && m.sources.length > 0 && (
                    <div className="srcs">
                      <h4>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                          <rect x="5" y="3" width="14" height="18" rx="2.5" />
                          <path d="M8.5 8h7M8.5 12h7M8.5 16h4" />
                        </svg>
                        Nguồn tham khảo ({m.sources.length})
                        <button type="button" className="glink" onClick={() => openGraph('ev', m.ans)}>
                          Xem đồ thị dẫn chứng
                        </button>
                      </h4>
                      {m.sources.map((sid) => {
                        const s = srcMap[sid]
                        if (!s) return null
                        return (
                          <button key={sid} type="button" className="src" onClick={() => openSrc(sid)}>
                            <span className={`fi k-${s.kind}`}>{s.kind.toUpperCase()}</span>
                            <div className="t">
                              <b>{s.name}</b>
                              <span>{s.sub}</span>
                            </div>
                            <span className="pg">Trang {s.page}</span>
                            <span className="ext">
                              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                                <path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1h5" />
                              </svg>
                            </span>
                          </button>
                        )
                      })}
                    </div>
                  )}
                </div>
              </div>
            )
          )}

          {isBusy && (
            <div className="msg b">
              <img className="rb" src={IMAGES.botAvatar} alt="" />
              <div className="body">
                <div className="typing">
                  <i />
                  <i />
                  <i />
                </div>
              </div>
            </div>
          )}
        </div>

        <div id="follow" style={{ visibility: isBusy ? 'hidden' : 'visible' }}>
          {FOLLOW_QUESTIONS.map(([t, iconSvg], i) => (
            <button key={i} type="button" onClick={() => handleSend(t)}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" dangerouslySetInnerHTML={{ __html: iconSvg }} />
              {t}
            </button>
          ))}
        </div>

        <form
          className="cmp"
          id="form"
          autoComplete="off"
          onSubmit={(e) => {
            e.preventDefault()
            handleSend(inputQ)
          }}
        >
          <button type="button" className="clip hov" id="btnClip" title="Đính kèm tài liệu" onClick={() => toast('Đính kèm tài liệu: Chưa kết nối trong bản demo')}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M20 11l-8.5 8.5a5 5 0 01-7-7L13 4a3.3 3.3 0 014.7 4.7L9.2 17.2a1.7 1.7 0 01-2.4-2.4L14.5 7" />
            </svg>
          </button>
          <textarea
            ref={textareaRef}
            id="q"
            rows={1}
            placeholder="Nhập câu hỏi về quy định, tiêu chuẩn, thủ tục OCOP..."
            maxLength={600}
            value={inputQ}
            onChange={(e) => {
              setInputQ(e.target.value)
              e.target.style.height = '26px'
              e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px'
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSend(inputQ)
              }
            }}
          />
          <button type="submit" className="send hov" id="btnSend" aria-label="Gửi" disabled={!inputQ.trim()}>
            <svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinejoin="round">
              <path d="M21 3L3 10l7 3 3 7z" />
              <path d="M10 13l11-10" />
            </svg>
          </button>
          <div
            className={`seg ${searchMode === 'wide' ? 'wide' : ''}`}
            id="seg"
            role="switch"
            aria-checked={searchMode === 'exact'}
            tabIndex={0}
            onClick={() => {
              const next = searchMode === 'exact' ? 'wide' : 'exact'
              setSearchMode(next)
              toast(next === 'exact' ? 'Chỉ trả lời khi có căn cứ trong văn bản' : 'Cho phép mở rộng thêm nguồn liên quan')
            }}
          >
            <div className="sw" />
            <span className="cur" id="segL">
              {searchMode === 'exact' ? 'Tìm kiếm chính xác' : 'Tìm kiếm mở rộng'}
            </span>
            <span id="segR">{searchMode === 'exact' ? 'Tìm kiếm mở rộng' : 'Tìm kiếm chính xác'}</span>
          </div>
          <div className="hint">Shift + Enter xuống dòng · nội dung có dẫn chứng</div>
          <button type="button" className="refresh" id="btnClear" aria-label="Làm mới" onClick={() => setInputQ('')} />
        </form>
      </section>

      {/* Right Column: Quick actions, related docs, product carousel */}
      <aside className="cv rightcol" id="rightcol">
        <section className="rcd">
          <h3>
            <svg viewBox="0 0 24 24" fill="#f5b014" stroke="#f5b014" strokeWidth="1" strokeLinejoin="round">
              <path d="M13 2L4 14h6l-1 8 9-12h-6z" />
            </svg>
            Hành động nhanh
          </h3>
          <div className="qa">
            <button type="button" className="c1" onClick={() => setActiveView('docs')}>
              <span className="ic">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
                  <rect x="5" y="3" width="14" height="18" rx="2.5" />
                  <path d="M8.5 8h7M8.5 12h7M8.5 16h4" />
                </svg>
              </span>
              <div>
                <b>Tra cứu văn bản</b>
                <span>Pháp luật OCOP</span>
              </div>
            </button>
            <button type="button" className="c2" onClick={() => setActiveView('crit')}>
              <span className="ic">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="5" y="3" width="14" height="18" rx="2.5" />
                  <path d="M9 12l2 2 4-4" />
                </svg>
              </span>
              <div>
                <b>Xem tiêu chí</b>
                <span>3–4–5 sao</span>
              </div>
            </button>
            <button type="button" className="c3" onClick={() => setActiveView('prod')}>
              <span className="ic">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round">
                  <path d="M4 9l2-5h12l2 5v1a3 3 0 01-6 0 3 3 0 01-6 0 3 3 0 01-4 0zM5 13v7h14v-7" />
                </svg>
              </span>
              <div>
                <b>Tìm sản phẩm</b>
                <span>Đã công nhận</span>
              </div>
            </button>
            <button type="button" className="c4" onClick={() => openGraph('doc')}>
              <span className="ic">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
                  <circle cx="5" cy="6" r="2.2" />
                  <circle cx="19" cy="6" r="2.2" />
                  <circle cx="12" cy="18" r="2.2" />
                  <path d="M7 7l4 9M17 7l-4 9" />
                </svg>
              </span>
              <div>
                <b>Đồ thị văn bản</b>
                <span>Quan hệ giữa văn bản</span>
              </div>
            </button>
          </div>
        </section>

        <section className="rcd">
          <h3>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
              <rect x="5" y="3" width="14" height="18" rx="2.5" />
              <path d="M8.5 8h7M8.5 12h7M8.5 16h4" />
            </svg>
            Tài liệu liên quan
            <a onClick={() => setActiveView('docs')} style={{ cursor: 'pointer' }}>Xem thêm →</a>
          </h3>
          <div className="rel" id="rel">
            {REL_DOCS.map(([sid, title, sub, yr]) => {
              const s = srcMap[sid]
              return (
                <button key={sid} type="button" onClick={() => openSrc(sid)}>
                  <span className={`fi k-${s?.kind || 'doc'}`}>{s?.kind?.toUpperCase() || 'DOC'}</span>
                  <div className="t">
                    <b>{title}</b>
                    <span className="s">{sub}</span>
                  </div>
                  <span className="y">{yr}</span>
                </button>
              )
            })}
          </div>
        </section>

        <section className="rcd grow">
          <h3>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <rect x="5" y="3" width="14" height="18" rx="2.5" />
              <path d="M9 12l2 2 4-4" />
            </svg>
            Sản phẩm OCOP nổi bật
            <a onClick={() => setActiveView('prod')} style={{ cursor: 'pointer' }}>Xem thêm →</a>
          </h3>
          <div className="car">
            <button
              type="button"
              className="pv"
              id="carPv"
              aria-label="Trước"
              onClick={() => carTrackRef.current?.scrollBy({ left: -200, behavior: 'smooth' })}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
                <path d="M15 5l-7 7 7 7" />
              </svg>
            </button>
            <div className="track" id="carTrack" ref={carTrackRef}>
              {PROD_CAROUSEL.map(([name, rating, im, bg], i) => (
                <div key={i} className="pc">
                  <div className="im" style={{ background: bg }}>
                    {im.startsWith('<') ? (
                      <div dangerouslySetInnerHTML={{ __html: im }} />
                    ) : (
                      <img src={im} alt={name} />
                    )}
                  </div>
                  <div className="tx">
                    <b>{name}</b>
                    <div className="st">
                      ★★★★<span style={{ opacity: 0.35 }}>★</span>
                      <i>{rating}</i>
                    </div>
                    <small>OCOP 4 sao</small>
                  </div>
                </div>
              ))}
            </div>
            <button
              type="button"
              className="nx"
              id="carNx"
              aria-label="Sau"
              onClick={() => carTrackRef.current?.scrollBy({ left: 200, behavior: 'smooth' })}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round">
                <path d="M9 5l7 7-7 7" />
              </svg>
            </button>
          </div>
        </section>
      </aside>
    </>
  )
}
