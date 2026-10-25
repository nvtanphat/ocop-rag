import React, { useState, useEffect, useRef, useCallback } from 'react'
import { IMAGES } from '../ocop/assets'
import type {
  ActiveView,
  DocInfo,
  SrcItem,
  BotAnswer,
  ChatMessage,
  DocRecord,
  CritRecord,
  ProdRecord,
} from '../ocop/portal/types'
import {
  INITIAL_DOCS,
  INITIAL_SRC,
  INITIAL_LIB,
  generateBaseCriteria,
  generateBaseProducts,
} from '../ocop/portal/data'
import { nowTime, formatMd, esc } from '../ocop/portal/utils'
import { LeftSidebar } from '../ocop/portal/LeftSidebar'
import { TopHeader } from '../ocop/portal/TopHeader'
import { PortalChat } from '../ocop/portal/PortalChat'
import { PortalDocuments } from '../ocop/portal/PortalDocuments'
import { PortalCriteria } from '../ocop/portal/PortalCriteria'
import { PortalProducts } from '../ocop/portal/PortalProducts'
import { PortalPdfModal } from '../ocop/portal/PortalPdfModal'
import { PortalGraphModal } from '../ocop/portal/PortalGraphModal'

export default function OcopPortal() {
  // Navigation & theme
  const [activeView, setActiveView] = useState<ActiveView>('chat')
  const [isDark, setIsDark] = useState(false)
  const [toastMsg, setToastMsg] = useState('')
  const toastTimer = useRef<number | null>(null)

  // Document Registry & Sources
  const [docsMap, setDocsMap] = useState<Record<string, DocInfo>>(INITIAL_DOCS)
  const [srcMap, setSrcMap] = useState<Record<string, SrcItem>>(INITIAL_SRC)

  // PDF Viewer Modal state
  const [pdfOpen, setPdfOpen] = useState(false)
  const [pdfSrcId, setPdfSrcId] = useState('S1')
  const [pdfPage, setPdfPage] = useState(18)
  const [pdfZoom, setPdfZoom] = useState(1.2)
  const [pdfHl, setPdfHl] = useState(true)

  // Graph Modal state
  const [graphOpen, setGraphOpen] = useState(false)
  const [graphTab, setGraphTab] = useState<'ev' | 'doc'>('ev')
  const [activeAns, setActiveAns] = useState<BotAnswer | null>(null)

  // Chat State
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [inputQ, setInputQ] = useState('')
  const [searchMode, setSearchMode] = useState<'exact' | 'wide'>('exact')
  const [isBusy, setIsBusy] = useState(false)
  const convoRef = useRef<HTMLDivElement | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  // Global Search
  const [globalSearch, setGlobalSearch] = useState('')

  // Documents View State
  const [libDocs] = useState<DocRecord[]>(INITIAL_LIB)
  const [docCat, setDocCat] = useState('ALL')
  const [docQ, setDocQ] = useState('')
  const [docOrg, setDocOrg] = useState('')
  const [docYear, setDocYear] = useState('')
  const [docPage, setDocPage] = useState(1)
  const [docPer, setDocPer] = useState(8)
  const [docIsList, setDocIsList] = useState(false)

  // Criteria View State
  const [crMap] = useState<Record<string, CritRecord[]>>(generateBaseCriteria)
  const [critDoc, setCritDoc] = useState<'148' | '26'>('148')
  const [critQ, setCritQ] = useState('')
  const [critPage, setCritPage] = useState(1)
  const [critPer, setCritPer] = useState(25)
  const [critChecked, setCritChecked] = useState<Record<string, boolean>>({})

  // Products View State
  const [prodList] = useState<ProdRecord[]>(generateBaseProducts)
  const [prodQ, setProdQ] = useState('')
  const [prodLoc, setProdLoc] = useState('')
  const [prodStar, setProdStar] = useState('')
  const [prodPage, setProdPage] = useState(1)
  const [prodPer, setProdPer] = useState(20)
  const [prodIsTable, setProdIsTable] = useState(false)

  // Toast Function
  const toast = useCallback((msg: string) => {
    setToastMsg(msg)
    if (toastTimer.current) clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(() => setToastMsg(''), 1800)
  }, [])

  // Switch Theme
  const toggleTheme = useCallback(() => {
    setIsDark((prev) => {
      const next = !prev
      if (next) {
        document.body.classList.add('dark')
      } else {
        document.body.classList.remove('dark')
      }
      return next
    })
  }, [])

  // Register Dynamic Source
  const registerSource = useCallback(
    (id: string, name: string, sub: string, total = 20) => {
      setSrcMap((prev) => {
        if (prev[id]) return prev
        return {
          ...prev,
          [id]: {
            doc: id,
            page: 1,
            bbox: '[0, 0, 0, 0]',
            total,
            kind: 'pdf',
            name,
            sub,
          },
        }
      })
      setDocsMap((prev) => {
        if (prev[id]) return prev
        return {
          ...prev,
          [id]: { title: name, sub },
        }
      })
    },
    []
  )

  // Open PDF Source
  const openSrc = useCallback(
    (sid: string, page?: number) => {
      const item = srcMap[sid]
      if (!item) {
        toast(`Chưa có dữ liệu PDF cho mã ${sid}`)
        return
      }
      setPdfSrcId(sid)
      setPdfPage(page || item.page || 1)
      setPdfOpen(true)
      setGraphOpen(false)
      setPdfHl(true)
    },
    [srcMap, toast]
  )

  // Open Knowledge Graph Modal
  const openGraph = useCallback((tab: 'ev' | 'doc', ansOverride?: BotAnswer | null) => {
    setPdfOpen(false)
    setGraphOpen(true)
    setGraphTab(tab)
    if (ansOverride) {
      setActiveAns(ansOverride)
    }
  }, [])

  // Copy text helper
  const copyText = useCallback(
    (text: string) => {
      navigator.clipboard.writeText(text).then(
        () => toast('Đã sao chép vào bộ nhớ tạm'),
        () => toast('Không thể sao chép')
      )
    },
    [toast]
  )

  // Like / Dislike / Save handlers
  const toggleLike = useCallback(
    (idx: number) => {
      setMessages((prev) =>
        prev.map((m, i) => (i === idx ? { ...m, liked: !m.liked, disliked: false } : m))
      )
      toast('Đã ghi nhận góp ý của bạn')
    },
    [toast]
  )

  const toggleDislike = useCallback(
    (idx: number) => {
      setMessages((prev) =>
        prev.map((m, i) => (i === idx ? { ...m, disliked: !m.disliked, liked: false } : m))
      )
      toast('Đã ghi nhận góp ý của bạn')
    },
    [toast]
  )

  const toggleSave = useCallback(
    (idx: number) => {
      setMessages((prev) =>
        prev.map((m, i) => {
          if (i !== idx) return m
          const next = !m.saved
          toast(next ? 'Đã lưu câu trả lời' : 'Đã bỏ lưu')
          return { ...m, saved: next }
        })
      )
    },
    [toast]
  )

  // Clear Chat History
  const clearConvo = useCallback(() => {
    setMessages([])
    toast('Đã làm mới cuộc hội thoại')
  }, [toast])

  // Scroll Chat to Bottom
  const scrollConvo = () => {
    setTimeout(() => {
      if (convoRef.current) {
        convoRef.current.scrollTop = convoRef.current.scrollHeight
      }
    }, 40)
  }

  // Ask Backend API
  const askBackend = useCallback(
    async (q: string, mode: 'exact' | 'wide'): Promise<BotAnswer> => {
      try {
        const resp = await fetch('/api/ocop/query', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            query: q,
            retrieval_mode: mode === 'wide' ? 'hybrid' : 'sparse',
            use_llm: true,
          }),
        })
        if (resp.ok) {
          const data = await resp.json()
          const rawAnswer = data.answer || data.response || ''
          const srcKeys: string[] = []
          if (Array.isArray(data.citations) && data.citations.length > 0) {
            data.citations.forEach((c: { source_id?: string; pdf_page?: number; title?: string; doc_name?: string; snippet?: string; bbox?: number[] }) => {
              const sid = c.source_id || 'S1'
              const docTitle = c.title || c.doc_name || `Văn bản ${sid}`
              const docSub = c.snippet || 'Trích đoạn quy định OCOP liên quan'
              setSrcMap((prev) => ({
                ...prev,
                [sid]: {
                  doc: c.source_id || '148',
                  page: c.pdf_page || 1,
                  bbox: c.bbox ? JSON.stringify(c.bbox) : '[120, 340, 520, 410]',
                  total: 42,
                  kind: 'pdf',
                  name: docTitle,
                  sub: docSub.length > 75 ? docSub.slice(0, 72) + '…' : docSub,
                },
              }))
              setDocsMap((prev) => ({
                ...prev,
                [c.source_id || '148']: {
                  title: docTitle,
                  sub: docSub.length > 90 ? docSub.slice(0, 87) + '…' : docSub,
                },
              }))
              srcKeys.push(sid)
            })
          }
          if (!srcKeys.length) srcKeys.push('S1')
          let claims: Array<[string, Array<[string, number]>]> | undefined = undefined
          if (Array.isArray(data.claims) && data.claims.length > 0) {
            claims = data.claims
          } else if (Array.isArray(data.citations) && data.citations.length > 0) {
            claims = data.citations.slice(0, 3).map((c: { snippet?: string }, i: number) => {
              const snip = c.snippet ? (c.snippet.length > 55 ? c.snippet.slice(0, 52) + '…' : c.snippet) : `Ý căn cứ ${i + 1}`
              return [snip, [['C' + (i + 1), 0.92]]]
            })
          }
          return {
            verified: data.verified !== false && !data.unverified,
            html: formatMd(rawAnswer),
            sources: srcKeys,
            claims,
          }
        }
      } catch {
        // Fallback for offline or local preview
      }

      // Offline responsive fallback
      await new Promise((r) => setTimeout(r, 600))
      if (/4 sao/i.test(q) && /tiêu chí|đáp ứng/i.test(q)) {
        return {
          verified: true,
          html:
            '<p>Sản phẩm OCOP đạt <b>4 sao</b> phải đáp ứng các tiêu chí theo Bộ tiêu chí OCOP giai đoạn 2021–2025 ban hành tại <b>Quyết định số 148/QĐ-TTg</b>, bao gồm 3 nhóm tiêu chí chính với tổng 100 điểm:</p>' +
            '<ol><li><span class="n">1.</span><div><b>Chất lượng sản phẩm (40 điểm)</b><span>Nguồn gốc, tiêu chuẩn, chất lượng, an toàn thực phẩm, hàm lượng dinh dưỡng...</span></div></li>' +
            '<li><span class="n">2.</span><div><b>Khả năng thương mại (40 điểm)</b><span>Bao bì, nhãn mác, thị trường, kênh phân phối, khả năng mở rộng...</span></div></li>' +
            '<li><span class="n">3.</span><div><b>Năng lực cộng đồng (20 điểm)</b><span>Tác động xã hội, môi trường, bảo tồn giá trị địa phương...</span></div></li></ol>' +
            '<p>Để đạt 4 sao, sản phẩm phải đạt từ 70 điểm đến dưới 90 điểm theo thang điểm quy định.</p>',
          sources: ['S1', 'S2'],
        }
      } else if (/cấp huyện/i.test(q) && /4 sao|công nhận/i.test(q)) {
        return {
          verified: true,
          html:
            '<p><b>Không.</b> <b>UBND cấp huyện không có thẩm quyền công nhận sản phẩm OCOP 4 sao.</b></p>' +
            '<p>Theo quy định tại <a class="lnk" data-src="S1">Quyết định 148/QĐ-TTg</a> ngày 24/02/2023, thẩm quyền đánh giá, phân hạng sản phẩm OCOP được quy định như sau:</p>' +
            '<ul><li><b>UBND cấp huyện:</b> tổ chức đánh giá, phân hạng sản phẩm OCOP đạt 3 sao trở xuống.</li><li><b>UBND cấp tỉnh:</b> tổ chức đánh giá, phân hạng sản phẩm OCOP đạt 4 sao.</li><li><b>Bộ Nông nghiệp và Phát triển nông thôn:</b> tổ chức đánh giá, phân hạng sản phẩm OCOP đạt 5 sao.</li></ul>' +
            '<p>Như vậy, UBND cấp huyện chỉ có thẩm quyền công nhận sản phẩm OCOP 3 sao, không có thẩm quyền công nhận 4 sao.</p>',
          sources: ['S1', 'S3', 'S4'],
          claims: [
            ['UBND cấp huyện: đánh giá từ 3 sao trở xuống', [['S1', 0.93], ['S3', 0.81]]],
            ['UBND cấp tỉnh: đánh giá 4 sao', [['S1', 0.91], ['S4', 0.78]]],
            ['Bộ NN&PTNT: đánh giá 5 sao', [['S1', 0.89], ['S3', 0.74]]],
          ],
        }
      } else if (/hồ sơ|thủ tục/i.test(q)) {
        return {
          verified: true,
          html:
            '<p><b>Hồ sơ đề xuất đánh giá sản phẩm OCOP gồm các thành phần chính sau:</b></p>' +
            '<ol><li><span class="n">1.</span><div><b>Đơn đăng ký tham gia chương trình OCOP</b><span>Theo mẫu quy định tại Quyết định 148/QĐ-TTg.</span></div></li>' +
            '<li><span class="n">2.</span><div><b>Phương án sản xuất, kinh doanh</b><span>Kế hoạch phát triển sản phẩm, dự toán kinh phí và kế hoạch doanh thu.</span></div></li>' +
            '<li><span class="n">3.</span><div><b>Giấy tờ pháp lý của chủ thể OCOP</b><span>Giấy chứng nhận ĐKKD/HTX, giấy phép môi trường, kiểm nghiệm ATTP.</span></div></li>' +
            '<li><span class="n">4.</span><div><b>Minh chứng tiêu chuẩn và chất lượng</b><span>Công bố chất lượng, mã số mã vạch, chứng nhận ISO/HACCP/VietGAP.</span></div></li></ol>',
          sources: ['S1', 'S2'],
        }
      } else if (/an toàn thực phẩm|attp/i.test(q)) {
        return {
          verified: true,
          html:
            '<p><b>Tiêu chuẩn An toàn thực phẩm đối với sản phẩm OCOP 4 sao:</b></p>' +
            '<ul><li>Bắt buộc có <b>Giấy chứng nhận cơ sở đủ điều kiện an toàn thực phẩm</b> hoặc các chứng chỉ tương đương được công nhận quốc tế như <b>HACCP, ISO 22000, FSSC 22000</b>.</li>' +
            '<li>Sản phẩm phải có kết quả kiểm nghiệm định kỳ các chỉ tiêu vi sinh, kim loại nặng đạt chuẩn QCVN/TCVN tương ứng.</li>' +
            '<li>Hệ thống tem nhãn đầy đủ thông tin truy xuất nguồn gốc nguồn nguyên liệu và nhật ký sản xuất.</li></ul>',
          sources: ['S1', 'S2', 'S3'],
        }
      } else {
        return {
          verified: false,
          html:
            `<p>Hệ thống đã tiếp nhận câu hỏi <b>“${esc(q)}”</b> (${mode === 'exact' ? 'chế độ tìm kiếm chính xác' : 'chế độ tìm kiếm mở rộng'}).</p>` +
            '<p>Để tra cứu quy định chính xác, bạn có thể tham khảo các câu hỏi mẫu như <b>“UBND cấp huyện có quyền công nhận 4 sao không?”</b> hoặc <b>“Bộ tiêu chí đánh giá OCOP 4 sao gồm những gì?”</b> hoặc kiểm tra tại Thư viện Văn bản OCOP.</p>',
          sources: ['S1'],
        }
      }
    },
    []
  )

  // Send message
  const handleSend = useCallback(
    async (text: string) => {
      const q = text.trim()
      if (!q || isBusy) return
      setIsBusy(true)
      setInputQ('')
      if (textareaRef.current) {
        textareaRef.current.style.height = '26px'
      }

      const userMsg: ChatMessage = {
        id: 'u-' + Date.now(),
        sender: 'u',
        text: q,
        time: nowTime(),
      }
      setMessages((prev) => [...prev, userMsg])
      scrollConvo()

      const ans = await askBackend(q, searchMode)
      const botMsg: ChatMessage = {
        id: 'b-' + Date.now(),
        sender: 'b',
        text: ans.html.replace(/<[^>]+>/g, ''),
        html: ans.html,
        time: nowTime(),
        verified: ans.verified,
        sources: ans.sources,
        ans,
      }
      setMessages((prev) => [...prev, botMsg])
      setActiveAns(ans)
      setIsBusy(false)
      scrollConvo()
    },
    [isBusy, searchMode, askBackend]
  )

  // Global search submit handler
  const handleGlobalSearchSubmit = useCallback(
    (query: string) => {
      const trimmed = query.trim()
      if (!trimmed) return
      if (activeView === 'chat') {
        handleSend(trimmed)
      } else if (activeView === 'docs') {
        setDocQ(trimmed)
      } else if (activeView === 'crit') {
        setCritQ(trimmed)
      } else if (activeView === 'prod') {
        setProdQ(trimmed)
      }
      setGlobalSearch('')
    },
    [activeView, handleSend]
  )

  // Export product CSV
  const exportProdCsv = useCallback(() => {
    try {
      const rows = [
        ['ID', 'Tên sản phẩm', 'Chủ thể', 'Địa phương', 'Xếp hạng sao', 'Số quyết định'],
        ...prodList.map((p) => [p.id, p.name, p.owner, p.loc, `${p.stars} sao`, p.code]),
      ]
      const csvContent =
        'data:text/csv;charset=utf-8,\uFEFF' +
        rows.map((e) => e.map((x) => `"${String(x).replace(/"/g, '""')}"`).join(',')).join('\n')
      const encodedUri = encodeURI(csvContent)
      const link = document.createElement('a')
      link.setAttribute('href', encodedUri)
      link.setAttribute('download', 'ocop_products.csv')
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      toast('Đã xuất danh sách sản phẩm OCOP')
    } catch {
      toast('Trình duyệt chặn tải xuống ở đây')
    }
  }, [prodList, toast])

  // Global keyboard listeners
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        document.getElementById('gsearch')?.focus()
      } else if (e.key === 'Escape') {
        if (pdfOpen) setPdfOpen(false)
        if (graphOpen) setGraphOpen(false)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [pdfOpen, graphOpen])

  // Sync active view to body attribute
  useEffect(() => {
    document.body.setAttribute('data-view', activeView)
  }, [activeView])

  return (
    <>
      {/* Background visual layers */}
      <div id="bgfx">
        <div className="b-terr" />
        <div className="b-haze" />
        <div className="b-hero" />
        <img className="leaf l1" src={IMAGES.leaf1} alt="" />
        <img className="leaf l2" src={IMAGES.leaf2} alt="" />
        <img className="leaf l3" src={IMAGES.leaf3} alt="" />
      </div>

      {/* Top Header */}
      <TopHeader
        activeView={activeView}
        globalSearch={globalSearch}
        setGlobalSearch={setGlobalSearch}
        onSearchSubmit={handleGlobalSearchSubmit}
        isDark={isDark}
        toggleTheme={toggleTheme}
        toast={toast}
      />

      {/* Left Rail Navigation */}
      <LeftSidebar
        activeView={activeView}
        setActiveView={setActiveView}
        clearConvo={clearConvo}
        toast={toast}
      />

      {/* Main Container */}
      <main id="main">
        {activeView === 'chat' && (
          <PortalChat
            messages={messages}
            convoRef={convoRef}
            isBusy={isBusy}
            inputQ={inputQ}
            setInputQ={setInputQ}
            textareaRef={textareaRef}
            searchMode={searchMode}
            setSearchMode={setSearchMode}
            handleSend={handleSend}
            copyText={copyText}
            toggleLike={toggleLike}
            toggleDislike={toggleDislike}
            toggleSave={toggleSave}
            openGraph={openGraph}
            openSrc={openSrc}
            srcMap={srcMap}
            setActiveView={setActiveView}
            toast={toast}
          />
        )}

        {/* PDF Modal Viewer */}
        <PortalPdfModal
          pdfOpen={pdfOpen}
          setPdfOpen={setPdfOpen}
          pdfSrcId={pdfSrcId}
          setPdfSrcId={setPdfSrcId}
          pdfPage={pdfPage}
          setPdfPage={setPdfPage}
          pdfZoom={pdfZoom}
          setPdfZoom={setPdfZoom}
          pdfHl={pdfHl}
          setPdfHl={setPdfHl}
          docsMap={docsMap}
          srcMap={srcMap}
          copyText={copyText}
          openSrc={openSrc}
          toast={toast}
        />

        {/* Knowledge Graph Modal */}
        <PortalGraphModal
          graphOpen={graphOpen}
          setGraphOpen={setGraphOpen}
          graphTab={graphTab}
          setGraphTab={setGraphTab}
          activeAns={activeAns}
          srcMap={srcMap}
        />

        {/* Documents Tab */}
        {activeView === 'docs' && (
          <PortalDocuments
            libDocs={libDocs}
            docCat={docCat}
            setDocCat={setDocCat}
            docQ={docQ}
            setDocQ={setDocQ}
            docOrg={docOrg}
            setDocOrg={setDocOrg}
            docYear={docYear}
            setDocYear={setDocYear}
            docPage={docPage}
            setDocPage={setDocPage}
            docPer={docPer}
            setDocPer={setDocPer}
            docIsList={docIsList}
            setDocIsList={setDocIsList}
            openSrc={openSrc}
            registerSource={registerSource}
            toast={toast}
          />
        )}

        {/* Criteria Tab */}
        {activeView === 'crit' && (
          <PortalCriteria
            crMap={crMap}
            critDoc={critDoc}
            setCritDoc={setCritDoc}
            critQ={critQ}
            setCritQ={setCritQ}
            critPage={critPage}
            setCritPage={setCritPage}
            critPer={critPer}
            setCritPer={setCritPer}
            critChecked={critChecked}
            setCritChecked={setCritChecked}
            setActiveView={setActiveView}
            openSrc={openSrc}
          />
        )}

        {/* Products Tab */}
        {activeView === 'prod' && (
          <PortalProducts
            prodList={prodList}
            prodQ={prodQ}
            setProdQ={setProdQ}
            prodLoc={prodLoc}
            setProdLoc={setProdLoc}
            prodStar={prodStar}
            setProdStar={setProdStar}
            prodPage={prodPage}
            setProdPage={setProdPage}
            prodPer={prodPer}
            setProdPer={setProdPer}
            prodIsTable={prodIsTable}
            setProdIsTable={setProdIsTable}
            exportProdCsv={exportProdCsv}
            registerSource={registerSource}
            setActiveView={setActiveView}
            openSrc={openSrc}
          />
        )}
      </main>

      {/* Toast Notification */}
      <div className={`toast ${toastMsg ? 'show' : ''}`} id="toast">
        {toastMsg}
      </div>
    </>
  )
}
