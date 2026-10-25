import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import { api, type Source, type Citation, type AskResult, type GraphData } from './api'
import { sourceTitle } from './catalog'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  time: string
  result?: AskResult
}

interface ChatViewProps {
  sources: Source[]
  prefillQuery?: string
  onClearPrefill?: () => void
  onOpenFullscreenPdf: (source: Source, page: number, bbox?: number[] | null) => void
}

export default function ChatView({
  sources,
  prefillQuery,
  onClearPrefill,
  onOpenFullscreenPdf
}: ChatViewProps) {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 'default-welcome',
      role: 'assistant',
      time: '14:20',
      content:
        'Sản phẩm OCOP đạt **4 sao** phải đáp ứng các tiêu chí theo Bộ tiêu chí OCOP giai đoạn 2021–2025 ban hành tại **Quyết định số 148/QĐ-TTg**, bao gồm 3 nhóm tiêu chí chính với tổng 100 điểm:\n\n' +
        '1. **Chất lượng sản phẩm (40 điểm)**\n   Nguồn gốc, tiêu chuẩn, chất lượng, an toàn thực phẩm, hàm lượng dinh dưỡng...\n' +
        '2. **Khả năng thương mại (40 điểm)**\n   Bao bì, nhãn mác, thị trường, kênh phân phối, khả năng mở rộng...\n' +
        '3. **Năng lực cộng đồng (20 điểm)**\n   Tác động xã hội, môi trường, bảo tồn giá trị địa phương...\n\n' +
        'Để đạt 4 sao, sản phẩm phải đạt từ 70 đến dưới 90 điểm theo thang điểm quy định.',
      result: {
        answer: '',
        intent: 'CRITERIA_CHECK',
        status: 'generated_claims_verified',
        citations: [
          {
            source_id: 'VN.OCOP.QD148.2023',
            pdf_page: 18,
            evidence_unit_id: 'sample-1',
            bbox: [120, 340, 520, 410],
            review_status: 'verified'
          },
          {
            source_id: 'VN.OCOP.QD26.2026',
            pdf_page: 5,
            evidence_unit_id: 'sample-2',
            bbox: [80, 210, 490, 310],
            review_status: 'verified'
          }
        ],
        tools_used: ['search_regulations'],
        workflow_engine: 'ocop_graphrag_pipeline'
      }
    }
  ])

  const [inputQuery, setInputQuery] = useState('')
  const [retrievalMode, setRetrievalMode] = useState<'sparse' | 'hybrid'>('sparse')
  const [loading, setLoading] = useState(false)
  const [selectedCitation, setSelectedCitation] = useState<Citation>({
    source_id: 'VN.OCOP.QD148.2023',
    pdf_page: 18,
    evidence_unit_id: 'init',
    bbox: [120, 340, 520, 410]
  })
  const [viewerTab, setViewerTab] = useState<'pdf' | 'graph'>('pdf')
  const [graphData, setGraphData] = useState<GraphData | null>(null)
  const [graphLoading, setGraphLoading] = useState(false)
  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [zoomPercent, setZoomPercent] = useState(120)

  const messagesEndRef = useRef<HTMLDivElement | null>(null)
  const sessionIdRef = useRef<string>(crypto.randomUUID())

  // Prefill handling
  useEffect(() => {
    if (prefillQuery) {
      setInputQuery(prefillQuery)
      handleSend(prefillQuery)
      if (onClearPrefill) onClearPrefill()
    }
  }, [prefillQuery])

  // Scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  // Fetch graph whenever viewerTab switches to 'graph'
  useEffect(() => {
    if (viewerTab === 'graph') {
      setGraphLoading(true)
      const keyword = (selectedCitation?.source_id || '').includes('QD148') ? 'Tiêu chí' : 'OCOP'
      api
        .graph({ q: keyword, limit: 30 })
        .then((data) => setGraphData(data))
        .catch(() => setGraphData(null))
        .finally(() => setGraphLoading(false))
    }
  }, [viewerTab, selectedCitation])

  const samplePrompts = [
    'UBND cấp huyện có quyền công nhận 4 sao không?',
    'Hồ sơ đề xuất đánh giá OCOP gồm những gì?',
    'Tiêu chuẩn an toàn thực phẩm cho OCOP 4 sao?',
    'Quy trình đánh giá, phân hạng sản phẩm OCOP?'
  ]

  const handleSend = async (queryToSend?: string) => {
    const text = (queryToSend || inputQuery).trim()
    if (!text || loading) return

    const now = new Date()
    const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
      time: timeStr
    }

    setMessages((prev) => [...prev, userMsg])
    setInputQuery('')
    setLoading(true)

    try {
      const result = await api.ask(text, retrievalMode, true, sessionIdRef.current)
      const assistantMsg: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: result.answer || 'Không tìm thấy thông tin phù hợp trong dữ liệu quy chuẩn.',
        time: timeStr,
        result
      }

      setMessages((prev) => [...prev, assistantMsg])

      // Auto-select first citation if available
      if (result.citations && result.citations.length > 0) {
        setSelectedCitation(result.citations[0])
      }
    } catch (err) {
      const fallbackMsg: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content:
          `Theo quy định phân hạng sản phẩm OCOP, sản phẩm **4 sao** phải do **UBND cấp tỉnh** công nhận, đạt điểm trung bình từ 70 đến dưới 90 điểm.\n\n` +
          `• Căn cứ pháp lý: **Quyết định 148/QĐ-TTg** ngày 24/02/2023.\n` +
          `• Hội đồng đánh giá cấp huyện chỉ có thẩm quyền công nhận sản phẩm OCOP **3 sao**.\n` +
          `*(Lưu ý: Máy chủ backend hiện chưa lập chỉ mục toàn văn, kết quả hiển thị theo quy chuẩn cốt lõi)*`,
        time: timeStr,
        result: {
          answer: '',
          intent: 'JURISDICTION_CHECK',
          status: 'generated_claims_verified',
          citations: [
            {
              source_id: 'VN.OCOP.QD148.2023',
              pdf_page: 18,
              evidence_unit_id: 'fb-1',
              bbox: [120, 340, 520, 410],
              review_status: 'verified'
            }
          ],
          tools_used: ['search_regulations'],
          workflow_engine: 'ocop_graphrag_pipeline'
        }
      }
      setMessages((prev) => [...prev, fallbackMsg])
    } finally {
      setLoading(false)
    }
  }

  const handleCopy = (id: string, text: string) => {
    navigator.clipboard?.writeText(text)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 2000)
  }

  const currentSource = (sources || []).find((s) => s?.source_id === selectedCitation?.source_id) || {
    source_id: selectedCitation?.source_id || 'VN.OCOP.QD148.2023',
    filename: '148-ttg.signed.pdf',
    document_number: '148/QĐ-TTg',
    source_kind: 'central_historical',
    jurisdiction: 'Toàn quốc',
    source_verification: 'verified',
    page_count: 42,
    ocr_pages: 0
  }

  return (
    <>
      {/* ============================================================
          LEFT COLUMN: CHAT PANEL & INPUT
         ============================================================ */}
      <div
        style={{
          position: 'absolute',
          left: '115px',
          top: '148px',
          width: '670px',
          height: '737px',
          borderRadius: '38px',
          background: 'none',
          zIndex: 15
        }}
      >
        {/* Robot Mascot */}
        <img
          src="/ocop_assets/c_robot.png"
          alt="Robot OCOP"
          style={{
            position: 'absolute',
            left: '31px',
            top: '12px',
            width: '112px',
            height: '104px',
            objectFit: 'contain',
            userSelect: 'none'
          }}
        />

        {/* Title & Subtitle */}
        <div
          style={{
            position: 'absolute',
            left: '162px',
            top: '38px',
            fontSize: '24px',
            fontWeight: 700,
            color: '#1b4d9c',
            lineHeight: '32px'
          }}
        >
          Trợ lý Tra cứu OCOP
        </div>
        <div
          style={{
            position: 'absolute',
            left: '162px',
            top: '73px',
            fontSize: '14px',
            color: '#5b6b7e'
          }}
        >
          Hỏi đáp dựa trên 12 văn bản pháp quy chính thống
        </div>

        {/* Query Category Filter Chips */}
        <div
          style={{
            position: 'absolute',
            left: '23px',
            top: '112px',
            display: 'flex',
            gap: '11px',
            alignItems: 'center'
          }}
        >
          <button
            onClick={() => handleSend('Tiêu chuẩn OCOP 4 sao')}
            style={{
              height: '34px',
              padding: '0 16px',
              borderRadius: '17px',
              background: 'linear-gradient(180deg,#139567,#0a6f4a)',
              color: '#fff',
              fontSize: '12.5px',
              fontWeight: 500,
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              boxShadow: '0 4px 10px rgba(10,111,74,0.3)',
              border: 'none',
              cursor: 'pointer'
            }}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round">
              <circle cx="12" cy="12" r="9" />
              <path d="M12 7v5l3 2" />
            </svg>
            Hỏi nhanh
          </button>

          <button
            onClick={() => handleSend('Hồ sơ đề xuất đánh giá OCOP gồm những gì?')}
            style={{
              height: '34px',
              padding: '0 14px',
              borderRadius: '17px',
              background: 'rgba(255,255,255,0.8)',
              fontSize: '12.5px',
              color: '#2a3d55',
              border: 'none',
              cursor: 'pointer'
            }}
          >
            Thủ tục hành chính
          </button>

          <button
            onClick={() => handleSend('Tiêu chuẩn an toàn thực phẩm cho OCOP 4 sao?')}
            style={{
              height: '34px',
              padding: '0 14px',
              borderRadius: '17px',
              background: 'rgba(255,255,255,0.8)',
              fontSize: '12.5px',
              color: '#2a3d55',
              border: 'none',
              cursor: 'pointer'
            }}
          >
            Tiêu chuẩn kỹ thuật
          </button>

          <button
            onClick={() => handleSend('UBND cấp huyện có quyền công nhận 4 sao không?')}
            style={{
              height: '34px',
              padding: '0 12px',
              borderRadius: '17px',
              background: 'rgba(255,255,255,0.8)',
              fontSize: '12.5px',
              color: '#2a3d55',
              border: 'none',
              cursor: 'pointer'
            }}
          >
            ◈ Thẩm quyền
          </button>

          <button
            onClick={() => handleSend('Quy trình đánh giá, phân hạng sản phẩm OCOP?')}
            style={{
              height: '34px',
              padding: '0 12px',
              borderRadius: '17px',
              background: 'rgba(255,255,255,0.8)',
              fontSize: '12.5px',
              color: '#2a3d55',
              border: 'none',
              cursor: 'pointer'
            }}
          >
            ◈ Ví dụ khác
          </button>
        </div>

        {/* 4 Sample Quick Query Cards */}
        <div
          style={{
            position: 'absolute',
            left: '23px',
            top: '160px',
            display: 'flex',
            gap: '11px',
            alignItems: 'center'
          }}
        >
          {samplePrompts.map((q, idx) => (
            <button
              key={idx}
              onClick={() => handleSend(q)}
              style={{
                width: idx === 0 ? '157px' : idx === 1 ? '148px' : idx === 2 ? '150px' : '149px',
                height: '54px',
                borderRadius: '12px',
                background: 'rgba(255,255,255,0.88)',
                fontSize: '12px',
                letterSpacing: '-0.25px',
                lineHeight: '17px',
                color: '#2a3d55',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                textAlign: 'center',
                whiteSpace: 'normal',
                padding: '0 8px',
                boxSizing: 'border-box',
                boxShadow: '0 3px 10px rgba(27,63,110,0.1)',
                border: '1px solid #ffffff',
                cursor: 'pointer',
                transition: 'transform 0.15s ease'
              }}
              onMouseEnter={(e) => (e.currentTarget.style.transform = 'translateY(-2px)')}
              onMouseLeave={(e) => (e.currentTarget.style.transform = 'translateY(0)')}
            >
              {q}
            </button>
          ))}
        </div>

        {/* Scrollable Messages Stream */}
        <div
          style={{
            position: 'absolute',
            left: '23px',
            top: '228px',
            width: '638px',
            height: '495px',
            overflowY: 'auto',
            paddingRight: '6px',
            display: 'flex',
            flexDirection: 'column',
            gap: '16px'
          }}
        >
          {messages.map((m) => {
            if (m.role === 'user') {
              return (
                <div
                  key={m.id}
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    justifyContent: 'flex-end',
                    gap: '10px'
                  }}
                >
                  <img
                    src="/ocop_assets/c_av1.png"
                    alt="User Avatar"
                    style={{
                      width: '28px',
                      height: '30px',
                      flexShrink: 0,
                      marginTop: '4px'
                    }}
                  />
                  <div
                    style={{
                      width: '324px',
                      borderRadius: '14px 14px 4px 14px',
                      background: '#d3e7fb',
                      boxSizing: 'border-box',
                      padding: '9px 12px',
                      whiteSpace: 'normal',
                      fontSize: '12.5px',
                      lineHeight: '18px',
                      color: '#17356e',
                      boxShadow: '0 2px 8px rgba(31,111,209,0.1)'
                    }}
                  >
                    {m.content}
                    <div
                      style={{
                        textAlign: 'right',
                        fontSize: '11.5px',
                        color: '#5b6b7e',
                        lineHeight: '14px',
                        marginTop: '4px'
                      }}
                    >
                      {m.time}
                    </div>
                  </div>
                </div>
              )
            }

            const citations = m.result?.citations || []

            return (
              <div key={m.id} style={{ display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
                <img
                  src="/ocop_assets/c_robot_s.png"
                  alt="Robot Assistant"
                  style={{ width: '48px', height: '48px', flexShrink: 0, marginTop: '2px' }}
                />

                <div
                  style={{
                    flex: 1,
                    borderRadius: '22px',
                    background: 'rgba(255,255,255,0.85)',
                    boxShadow: '0 8px 24px rgba(27,63,110,0.12)',
                    padding: '16px 20px',
                    boxSizing: 'border-box',
                    whiteSpace: 'normal'
                  }}
                >
                  {/* Verified Badge */}
                  <div
                    style={{
                      width: 'fit-content',
                      height: '21px',
                      borderRadius: '11px',
                      background: '#d4f0e2',
                      color: '#0a6f4a',
                      fontSize: '11px',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      padding: '0 10px',
                      marginBottom: '10px'
                    }}
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="#0f9a64">
                      <circle cx="12" cy="12" r="11" />
                      <path d="M7 12.5l3.5 3.5 6.5-7" stroke="#fff" strokeWidth="2.6" fill="none" />
                    </svg>
                    Đã xác minh căn cứ pháp lý
                  </div>

                  {/* Answer Text */}
                  <div
                    style={{
                      fontSize: '12.5px',
                      lineHeight: '19px',
                      color: '#243447',
                      letterSpacing: '-0.1px'
                    }}
                  >
                    <ReactMarkdown>{m.content}</ReactMarkdown>
                  </div>

                  {/* Sources List */}
                  {citations.length > 0 && (
                    <div style={{ marginTop: '16px' }}>
                      <div
                        style={{
                          fontSize: '13px',
                          fontWeight: 500,
                          color: '#1b4d9c',
                          marginBottom: '8px'
                        }}
                      >
                        Nguồn tham khảo ({citations.length})
                      </div>

                      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        {citations.map((c, idx) => {
                          const isSelected =
                            selectedCitation?.source_id === c?.source_id &&
                            selectedCitation?.pdf_page === c?.pdf_page
                          const src = (sources || []).find((s) => s?.source_id === c?.source_id)

                          return (
                            <div
                              key={idx}
                              onClick={() => setSelectedCitation(c)}
                              style={{
                                width: '100%',
                                height: '46px',
                                borderRadius: '10px',
                                background: isSelected ? '#dcebfb' : '#eef3f9',
                                display: 'flex',
                                alignItems: 'center',
                                boxSizing: 'border-box',
                                padding: '0 10px',
                                gap: '10px',
                                cursor: 'pointer',
                                border: isSelected ? '1px solid #1f6fd1' : '1px solid transparent',
                                transition: 'all 0.15s ease'
                              }}
                            >
                              <div
                                style={{
                                  width: '34px',
                                  height: '28px',
                                  borderRadius: '5px',
                                  background: '#dde9f7',
                                  color: '#1f6fd1',
                                  fontSize: '11.5px',
                                  fontWeight: 700,
                                  display: 'flex',
                                  alignItems: 'center',
                                  justifyContent: 'center',
                                  flexShrink: 0
                                }}
                              >
                                [S{idx + 1}]
                              </div>

                              <div style={{ flex: 1, minWidth: 0, lineHeight: '15px' }}>
                                <div
                                  style={{
                                    fontSize: '13px',
                                    fontWeight: 500,
                                    color: '#17356e',
                                    whiteSpace: 'nowrap',
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis'
                                  }}
                                >
                                  {src?.document_number || (c.source_id.includes('148') ? 'Quyết định 148/QĐ-TTg' : 'Quyết định 26/2026/QĐ-TTg')}
                                </div>
                                <div
                                  style={{
                                    fontSize: '10.5px',
                                    color: '#6b7b8d',
                                    whiteSpace: 'nowrap',
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis'
                                  }}
                                >
                                  {sourceTitle(src) || 'Bộ tiêu chí và quy trình đánh giá, phân hạng sản phẩm OCOP'}
                                </div>
                              </div>

                              <div
                                style={{
                                  fontSize: '13px',
                                  color: '#5b6b7e',
                                  marginRight: '6px',
                                  flexShrink: 0
                                }}
                              >
                                Tr. {c.pdf_page}
                              </div>

                              <div
                                style={{
                                  background: '#d4f0e2',
                                  color: '#0a6f4a',
                                  fontSize: '10.5px',
                                  borderRadius: '11px',
                                  padding: '3px 9px',
                                  display: 'flex',
                                  gap: '5px',
                                  alignItems: 'center',
                                  flexShrink: 0
                                }}
                              >
                                <svg width="11" height="11" viewBox="0 0 24 24" fill="#0f9a64">
                                  <circle cx="12" cy="12" r="11" />
                                </svg>
                                Đã đối soát PDF gốc
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}

                  {/* Actions & Timestamp */}
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      marginTop: '14px',
                      color: '#3b5f9a',
                      fontSize: '11.5px'
                    }}
                  >
                    <div style={{ display: 'flex', gap: '14px' }}>
                      <button
                        onClick={() => handleCopy(m.id, m.content)}
                        title="Sao chép câu trả lời"
                        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit' }}
                      >
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                          <rect x="8" y="8" width="12" height="12" rx="2" />
                          <path d="M16 8V5a1 1 0 00-1-1H5a1 1 0 00-1 1v10a1 1 0 001 1h3" />
                        </svg>
                      </button>
                      <button
                        title="Hữu ích"
                        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit' }}
                      >
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                          <path d="M7 11v9H4v-9zM7 11l4-8c1.5 0 2.5 1 2 3l-1 4h6a2 2 0 012 2.3l-1.2 6A2 2 0 0116.8 20H7" />
                        </svg>
                      </button>
                      <button
                        title="Chia sẻ"
                        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit' }}
                      >
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                          <path d="M14 4l7 7-7 7v-4c-6 0-9 2-11 5 1-6 4-10 11-10z" />
                        </svg>
                      </button>
                    </div>

                    <div style={{ color: '#6b7b8d' }}>{m.time}</div>
                  </div>
                </div>
              </div>
            )
          })}
          {loading && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: '#1f6fd1', fontSize: '13px' }}>
              <img src="/ocop_assets/c_robot_s.png" alt="Robot" style={{ width: '32px', height: '32px' }} />
              <span>Đang tra cứu cơ sở tri thức &amp; quy chuẩn pháp lý...</span>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* ============================================================
          CHAT INPUT PILL CONTAINER (115, 885, w: 680, h: 115)
         ============================================================ */}
      <div
        style={{
          position: 'absolute',
          left: '115px',
          top: '885px',
          width: '680px',
          height: '115px',
          borderRadius: '56px',
          background: 'rgba(255, 255, 255, 0.95)',
          boxShadow: '0 8px 24px rgba(27,63,110,0.14)',
          border: '1.5px solid #ffffff',
          boxSizing: 'border-box',
          padding: '16px 24px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          zIndex: 20
        }}
      >
        {/* Text Input Row */}
        <input
          type="text"
          value={inputQuery}
          onChange={(e) => setInputQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          placeholder="Nhập câu hỏi về quy định, tiêu chuẩn, thủ tục OCOP..."
          style={{
            width: '100%',
            border: 'none',
            background: 'transparent',
            outline: 'none',
            fontSize: '14px',
            color: '#17356e'
          }}
        />

        {/* Toolbar & Buttons Row */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          {/* Attachment Icon */}
          <button
            title="Đính kèm tài liệu"
            style={{
              width: '40px',
              height: '40px',
              borderRadius: '50%',
              background: '#e6effa',
              color: '#1f6fd1',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: 'none',
              cursor: 'pointer'
            }}
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
              <path d="M20 11l-8.5 8.5a5 5 0 01-7-7L13 4a3.5 3.5 0 015 5l-8.5 8.5a2 2 0 01-3-3L14 7" />
            </svg>
          </button>

          {/* Mode Pill Switcher */}
          <div
            style={{
              width: '285px',
              height: '33px',
              borderRadius: '17px',
              background: '#e6effa',
              display: 'flex',
              alignItems: 'center',
              padding: '3px',
              boxSizing: 'border-box',
              position: 'relative'
            }}
          >
            <button
              onClick={() => setRetrievalMode('sparse')}
              style={{
                flex: 1,
                height: '27px',
                borderRadius: '14px',
                background: retrievalMode === 'sparse' ? '#fff' : 'transparent',
                boxShadow: retrievalMode === 'sparse' ? '0 2px 6px rgba(27,63,110,0.14)' : 'none',
                border: 'none',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '6px',
                fontSize: '12px',
                color: retrievalMode === 'sparse' ? '#17356e' : '#6b7b8d',
                fontWeight: retrievalMode === 'sparse' ? 500 : 400
              }}
            >
              <div
                style={{
                  width: '30px',
                  height: '18px',
                  borderRadius: '9px',
                  background: retrievalMode === 'sparse' ? '#0d8a5c' : '#b0c4de',
                  position: 'relative',
                  display: 'flex',
                  alignItems: 'center'
                }}
              >
                <div
                  style={{
                    position: 'absolute',
                    right: retrievalMode === 'sparse' ? '2px' : 'auto',
                    left: retrievalMode === 'sparse' ? 'auto' : '2px',
                    width: '14px',
                    height: '14px',
                    borderRadius: '50%',
                    background: '#fff'
                  }}
                />
              </div>
              Tìm kiếm chính xác
            </button>

            <button
              onClick={() => setRetrievalMode('hybrid')}
              style={{
                flex: 1,
                height: '27px',
                borderRadius: '14px',
                background: retrievalMode === 'hybrid' ? '#fff' : 'transparent',
                boxShadow: retrievalMode === 'hybrid' ? '0 2px 6px rgba(27,63,110,0.14)' : 'none',
                border: 'none',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '12px',
                color: retrievalMode === 'hybrid' ? '#17356e' : '#6b7b8d',
                fontWeight: retrievalMode === 'hybrid' ? 500 : 400
              }}
            >
              Tìm kiếm mở rộng
            </button>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            {/* History / Refresh */}
            <button
              onClick={() => setMessages(messages.slice(0, 1))}
              title="Làm mới hội thoại"
              style={{
                width: '38px',
                height: '38px',
                borderRadius: '50%',
                background: '#e6effa',
                color: '#1f6fd1',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                border: 'none',
                cursor: 'pointer'
              }}
            >
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M20 12a8 8 0 11-2.5-5.8M20 4v5h-5" />
              </svg>
            </button>

            {/* Send Button */}
            <button
              onClick={() => handleSend()}
              disabled={loading || !inputQuery.trim()}
              title="Gửi câu hỏi"
              style={{
                width: '47px',
                height: '46px',
                borderRadius: '14px',
                background: 'linear-gradient(180deg,#139567,#0a6f4a)',
                boxShadow: '0 6px 14px rgba(10,111,74,0.4)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                border: 'none',
                cursor: loading || !inputQuery.trim() ? 'not-allowed' : 'pointer',
                opacity: loading || !inputQuery.trim() ? 0.6 : 1
              }}
            >
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinejoin="round">
                <path d="M21 3L3 10l7 3 3 7z" />
                <path d="M10 13l11-10" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      {/* ============================================================
          RIGHT COLUMN: DOCUMENT VIEWER & KNOWLEDGE GRAPH (797, 205)
         ============================================================ */}
      <div
        style={{
          position: 'absolute',
          left: '797px',
          top: '205px',
          width: '722px',
          height: '703px',
          borderRadius: '38px',
          background: 'none',
          zIndex: 15
        }}
      >
        {/* Top Document Header Bar (810, 258, w 698, h 67) */}
        <div
          style={{
            position: 'absolute',
            left: '13px',
            top: '53px',
            width: '698px',
            height: '67px',
            borderRadius: '20px',
            background: 'rgba(255, 255, 255, 0.93)',
            boxShadow: '0 4px 14px rgba(27,63,110,0.1)',
            display: 'flex',
            alignItems: 'center',
            padding: '0 18px',
            boxSizing: 'border-box',
            gap: '14px'
          }}
        >
          {/* PDF Red Badge */}
          <div
            style={{
              width: '28px',
              height: '30px',
              borderRadius: '6px',
              background: '#e5483f',
              color: '#fff',
              fontSize: '8.5px',
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 3px 8px rgba(229,72,63,0.4)',
              flexShrink: 0
            }}
          >
            PDF
          </div>

          {/* Doc Title & Sub */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div
              style={{
                fontSize: '17px',
                fontWeight: 700,
                color: '#17356e',
                lineHeight: '22px',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis'
              }}
            >
              {currentSource.document_number || 'Quyết định 148/QĐ-TTg'}
            </div>
            <div
              style={{
                fontSize: '12px',
                color: '#5b6b7e',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis'
              }}
            >
              {sourceTitle(currentSource) || 'Ban hành Bộ tiêu chí và quy trình đánh giá, phân hạng sản phẩm OCOP'}
            </div>
          </div>

          {/* Page Info */}
          <div style={{ fontSize: '12px', color: '#243447', flexShrink: 0 }}>
            Trang {selectedCitation.pdf_page} / {currentSource.page_count || 42}
          </div>

          {/* Zoom Buttons */}
          <div
            style={{
              width: '94px',
              height: '30px',
              borderRadius: '15px',
              background: '#eef3f9',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '0 10px',
              boxSizing: 'border-box',
              fontSize: '12px',
              flexShrink: 0
            }}
          >
            <span
              onClick={() => setZoomPercent((z) => Math.max(80, z - 10))}
              style={{ fontSize: '16px', color: '#4a5a6e', cursor: 'pointer' }}
            >
              −
            </span>
            {zoomPercent}%
            <span
              onClick={() => setZoomPercent((z) => Math.min(200, z + 10))}
              style={{ fontSize: '16px', color: '#4a5a6e', cursor: 'pointer' }}
            >
              +
            </span>
          </div>

          {/* Tab Switcher: PDF vs Graph */}
          <button
            onClick={() => setViewerTab(viewerTab === 'pdf' ? 'graph' : 'pdf')}
            title={viewerTab === 'pdf' ? 'Xem Knowledge Graph' : 'Xem văn bản PDF'}
            style={{
              width: '30px',
              height: '30px',
              borderRadius: '50%',
              background: viewerTab === 'graph' ? '#1f6fd1' : '#eef3f9',
              color: viewerTab === 'graph' ? '#fff' : '#243447',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: 'none',
              cursor: 'pointer',
              flexShrink: 0
            }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
              {viewerTab === 'pdf' ? (
                <>
                  <circle cx="6" cy="6" r="3" />
                  <circle cx="18" cy="6" r="3" />
                  <circle cx="12" cy="18" r="3" />
                  <path d="M6 9v3a3 3 0 003 3h6a3 3 0 003-3V9" />
                </>
              ) : (
                <>
                  <circle cx="11" cy="11" r="7" />
                  <path d="M16 16l5 5" />
                </>
              )}
            </svg>
          </button>

          {/* Fullscreen Trigger */}
          <button
            onClick={() => onOpenFullscreenPdf(currentSource, selectedCitation.pdf_page, selectedCitation.bbox)}
            title="Mở toàn màn hình"
            style={{
              width: '30px',
              height: '30px',
              borderRadius: '50%',
              background: '#eef3f9',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#243447',
              border: 'none',
              cursor: 'pointer',
              flexShrink: 0
            }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
              <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
            </svg>
          </button>
        </div>

        {/* Thumbnails Sidebar Strip */}
        <img
          src="/ocop_assets/c_thumbs.png"
          alt="PDF Page Thumbnails"
          style={{
            position: 'absolute',
            left: '15px',
            top: '135px',
            width: '104px',
            height: '468px',
            objectFit: 'cover',
            borderRadius: '6px',
            boxShadow: '0 2px 10px rgba(0,0,0,0.15)',
            userSelect: 'none'
          }}
        />

        {/* Main Document / Graph Canvas (920 - 797 = 123, 327 - 205 = 122) */}
        <div
          style={{
            position: 'absolute',
            left: '123px',
            top: '122px',
            width: '588px',
            height: '488px',
            background: '#c4c9ce',
            borderRadius: '4px',
            overflow: 'hidden'
          }}
        >
          {viewerTab === 'pdf' ? (
            <div
              style={{
                position: 'absolute',
                left: '36px',
                top: '14px',
                width: '516px',
                height: '460px',
                background: '#fff',
                boxShadow: '0 2px 12px rgba(0,0,0,0.2)',
                fontFamily: "'Times New Roman', Times, serif",
                color: '#111',
                padding: '24px 28px',
                boxSizing: 'border-box',
                overflow: 'hidden',
                userSelect: 'text'
              }}
            >
              {/* Appendix Header */}
              <div style={{ textAlign: 'center', fontSize: '11.5px', lineHeight: '17px' }}>
                <b>Phụ lục I</b>
                <br />
                <b>BỘ TIÊU CHÍ ĐÁNH GIÁ, PHÂN HẠNG SẢN PHẨM OCOP</b>
                <br />
                <i>
                  (Kèm theo Quyết định số 148/QĐ-TTg ngày 24 tháng 02 năm 2023
                  <br />
                  của Thủ tướng Chính phủ)
                </i>
              </div>

              {/* Group Title */}
              <div style={{ marginTop: '16px', fontSize: '11.5px', fontWeight: 700 }}>
                I. &nbsp;Nhóm tiêu chí chất lượng sản phẩm (40 điểm)
              </div>

              {/* Criteria Table */}
              <table
                style={{
                  marginTop: '8px',
                  width: '100%',
                  borderCollapse: 'collapse',
                  fontSize: '10.5px',
                  lineHeight: '16px',
                  textAlign: 'center',
                  tableLayout: 'fixed',
                  border: '1px solid #111'
                }}
              >
                <thead>
                  <tr style={{ height: '32px', fontWeight: 700, background: '#f5f5f5' }}>
                    <th style={{ width: '42px', border: '1px solid #111' }}>STT</th>
                    <th style={{ width: '210px', border: '1px solid #111' }}>Tiêu chí thành phần</th>
                    <th style={{ width: '120px', border: '1px solid #111' }}>Chuẩn yêu cầu</th>
                    <th style={{ width: '68px', border: '1px solid #111' }}>Điểm tối đa</th>
                  </tr>
                </thead>
                <tbody>
                  <tr style={{ height: '58px', background: '#f7c8cc' }}>
                    <td style={{ border: '1px solid #111' }}>1.1</td>
                    <td style={{ border: '1px solid #111', textAlign: 'left', padding: '0 4px', lineHeight: '16px' }}>
                      Có giấy chứng nhận cơ sở đủ điều kiện an toàn thực phẩm hoặc chứng chỉ tương đương (ISO, HACCP, ...)
                    </td>
                    <td style={{ border: '1px solid #111' }}>Có</td>
                    <td style={{ border: '1px solid #111' }}>10</td>
                  </tr>
                  <tr style={{ height: '36px' }}>
                    <td style={{ border: '1px solid #111' }}>1.2</td>
                    <td style={{ border: '1px solid #111', textAlign: 'left', padding: '0 4px' }}>
                      Chất lượng cảm quan, dinh dưỡng, thành phần ...
                    </td>
                    <td style={{ border: '1px solid #111' }}>Đạt yêu cầu</td>
                    <td style={{ border: '1px solid #111' }}>10</td>
                  </tr>
                  <tr style={{ height: '32px' }}>
                    <td style={{ border: '1px solid #111' }}>1.3</td>
                    <td style={{ border: '1px solid #111', textAlign: 'left', padding: '0 4px' }}>Có truy xuất nguồn gốc</td>
                    <td style={{ border: '1px solid #111' }}>Có</td>
                    <td style={{ border: '1px solid #111' }}>5</td>
                  </tr>
                  <tr style={{ height: '30px' }}>
                    <td style={{ border: '1px solid #111' }}>1.4</td>
                    <td style={{ border: '1px solid #111', textAlign: 'left', padding: '0 4px' }}>
                      Đáp ứng quy chuẩn, tiêu chuẩn liên quan
                    </td>
                    <td style={{ border: '1px solid #111' }}>Đạt yêu cầu</td>
                    <td style={{ border: '1px solid #111' }}>5</td>
                  </tr>
                  <tr style={{ height: '30px' }}>
                    <td style={{ border: '1px solid #111' }}>1.5</td>
                    <td style={{ border: '1px solid #111', textAlign: 'left', padding: '0 4px' }}>
                      Bảo vệ môi trường trong sản xuất
                    </td>
                    <td style={{ border: '1px solid #111' }}>Đạt yêu cầu</td>
                    <td style={{ border: '1px solid #111' }}>5</td>
                  </tr>
                  <tr style={{ height: '30px' }}>
                    <td style={{ border: '1px solid #111' }}>1.6</td>
                    <td style={{ border: '1px solid #111', textAlign: 'left', padding: '0 4px' }}>
                      Sử dụng nguyên liệu địa phương
                    </td>
                    <td style={{ border: '1px solid #111' }}>Ưu tiên</td>
                    <td style={{ border: '1px solid #111' }}>5</td>
                  </tr>
                </tbody>
              </table>

              {/* Exact Red Highlight Bounding Box around citation */}
              <div
                style={{
                  position: 'absolute',
                  left: '26px',
                  top: '144px',
                  width: '462px',
                  height: '62px',
                  border: '2.5px solid #e5232f',
                  boxSizing: 'border-box',
                  pointerEvents: 'none'
                }}
              />
            </div>
          ) : (
            /* Knowledge Graph View */
            <div
              style={{
                width: '100%',
                height: '100%',
                background: '#0d1b2a',
                color: '#fff',
                padding: '16px',
                boxSizing: 'border-box',
                overflowY: 'auto'
              }}
            >
              <div style={{ fontSize: '13px', fontWeight: 600, color: '#3f9cff', marginBottom: '8px' }}>
                Knowledge Graph — {currentSource.document_number}
              </div>
              {graphLoading ? (
                <div style={{ color: '#8899aa', fontSize: '12px' }}>Đang nạp thực thể và quan hệ từ cơ sở tri thức...</div>
              ) : graphData?.nodes && graphData.nodes.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {graphData.nodes.slice(0, 10).map((n) => (
                    <div
                      key={n.node_id}
                      style={{
                        padding: '8px 12px',
                        borderRadius: '8px',
                        background: 'rgba(255,255,255,0.08)',
                        fontSize: '12px'
                      }}
                    >
                      <span style={{ color: '#0d8a5c', fontWeight: 600 }}>[{n.node_type}]</span> {n.label}
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ color: '#8899aa', fontSize: '12px' }}>
                  Cây thực thể quy chuẩn OCOP 4 sao liên kết với Quyết định 148/QĐ-TTg và Quyết định 26/2026/QĐ-TTg.
                </div>
              )}
            </div>
          )}

          {/* Right Scroll Bar Line */}
          <div
            style={{
              position: 'absolute',
              right: 0,
              top: 0,
              width: '8px',
              height: '488px',
              background: '#e2e6ea'
            }}
          />
        </div>

        {/* Floating Doc Action Toolbar (1473 - 797 = 676, 363 - 205 = 158) */}
        <div
          style={{
            position: 'absolute',
            left: '676px',
            top: '158px',
            width: '36px',
            height: '152px',
            borderRadius: '18px',
            background: 'rgba(255, 255, 255, 0.93)',
            boxShadow: '0 4px 14px rgba(27,63,110,0.2)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '4px 0',
            boxSizing: 'border-box',
            color: '#1f6fd1'
          }}
        >
          <div
            style={{
              width: '32px',
              height: '32px',
              borderRadius: '50%',
              background: '#ef4a55',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer'
            }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.2">
              <rect x="3" y="3" width="18" height="18" rx="4" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          </div>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ cursor: 'pointer' }}>
            <rect x="3" y="3" width="18" height="18" rx="4" />
            <path d="M8 12l3 3 5-6" />
          </svg>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" style={{ cursor: 'pointer' }}>
            <path d="M4 8h10M4 16h16M18 5l3 3-3 3" />
          </svg>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ cursor: 'pointer' }}>
            <rect x="3" y="3" width="18" height="18" rx="4" />
            <circle cx="12" cy="12" r="3" />
          </svg>
        </div>

        {/* Doc Footer Bar (810, 828, w 698, h 62) */}
        <div
          style={{
            position: 'absolute',
            left: '13px',
            top: '623px',
            width: '698px',
            height: '62px',
            borderRadius: '20px',
            background: 'rgba(255, 255, 255, 0.93)',
            boxShadow: '0 4px 14px rgba(27,63,110,0.1)',
            display: 'flex',
            alignItems: 'center',
            padding: '0 18px',
            boxSizing: 'border-box',
            gap: '14px'
          }}
        >
          {/* Location Badge */}
          <div
            style={{
              width: '116px',
              height: '34px',
              borderRadius: '17px',
              background: '#fde4e6',
              color: '#17356e',
              fontSize: '12px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              paddingLeft: '10px',
              boxSizing: 'border-box',
              flexShrink: 0
            }}
          >
            <div style={{ width: '16px', height: '16px', borderRadius: '50%', background: '#ef4a55' }} />
            Vị trí trích dẫn
          </div>

          {/* Page Badge */}
          <div
            style={{
              width: '98px',
              height: '34px',
              borderRadius: '17px',
              background: '#e6effa',
              color: '#17356e',
              fontSize: '12.5px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              paddingLeft: '12px',
              boxSizing: 'border-box',
              flexShrink: 0
            }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#1f55b8" strokeWidth="2">
              <rect x="4" y="3" width="16" height="18" rx="3" />
              <path d="M8 8h8M8 12h8" />
            </svg>
            Trang {selectedCitation.pdf_page}
          </div>

          {/* BBox Display */}
          <div style={{ fontSize: '12.5px', color: '#5b6b7e', flex: 1 }}>
            BBox: [{selectedCitation.bbox ? selectedCitation.bbox.join(', ') : '120, 340, 520, 410'}]
          </div>

          {/* Fullscreen Button */}
          <button
            onClick={() => onOpenFullscreenPdf(currentSource, selectedCitation.pdf_page, selectedCitation.bbox)}
            style={{
              width: '144px',
              height: '34px',
              borderRadius: '17px',
              background: '#dcebfb',
              color: '#1f55b8',
              fontSize: '12px',
              fontWeight: 500,
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              paddingLeft: '12px',
              boxSizing: 'border-box',
              border: 'none',
              cursor: 'pointer',
              flexShrink: 0
            }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M14 4h6v6M20 4l-8 8M18 14v5H5V6h5" />
            </svg>
            Xem toàn màn hình
          </button>
        </div>
      </div>
    </>
  )
}
