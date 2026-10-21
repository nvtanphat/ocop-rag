import { useEffect, useState, type ComponentType } from 'react'
import { Activity, ArrowRight, BookOpen, Check, ChevronRight, ClipboardList, ExternalLink, FileText, GitBranch, Leaf, Menu, RefreshCcw, ShieldAlert, Sparkles, X } from 'lucide-react'
import { api } from '../ocop/api'
import type { Health, Overview, Section, Source } from '../ocop/api'
import { samplePrompts, sourceTitle } from '../ocop/catalog'
import Sidebar from '../ocop/Sidebar'
import Chat, { type Message } from '../ocop/Chat'
import { Criteria, Forms, KnowledgeGraph, Recognitions, Sources } from '../ocop/KnowledgeViews'
import Review from '../ocop/Review'

const headings: Record<Section, string> = { overview: 'Tổng quan', chat: 'Trợ lý OCOP', criteria: 'Bộ tiêu chí', forms: 'Biểu mẫu OCOP', recognitions: 'Sản phẩm công nhận', documents: 'Thư viện văn bản', graph: 'Đồ thị tri thức', system: 'Trạng thái hệ thống', review: 'Người duyệt' }

function CountCard({ label, value, note, icon: Icon }: { label: string; value: number | string; note: string; icon: ComponentType<{ size?: number } > }) {
  return <div className="ocop-count-card"><div className="ocop-count-header"><span>{label}</span><span className="ocop-count-icon"><Icon size={19}/></span></div><strong>{typeof value==='number' ? value.toLocaleString('vi-VN') : value}</strong><small>{note}</small></div>
}

function OverviewView({ overview, sources, onNavigate, openPdf, askPrompt }: {
  overview: Overview | null; sources: Source[]; onNavigate: (v: Section)=>void; openPdf:(source:Source,page?:number)=>void; askPrompt:(q:string)=>void
}) {
  const featured = sources.find(s=>s.source_id==='VN.OCOP.QD26.2026') || sources[0]
  return <div className="ocop-view-scroll ocop-overview-view">
    <div className="ocop-hero"><div className="ocop-hero-content"><div className="ocop-hero-badge"><span/> NỀN TẢNG TRA CỨU OCOP</div><h1>Tra cứu dễ hơn.<br/><em>Hiểu OCOP sâu hơn.</em></h1><p>Khám phá bộ tiêu chí, quy trình đánh giá và văn bản liên quan trong một không gian tri thức có dẫn nguồn.</p><div className="ocop-hero-actions"><button className="ocop-hero-primary" onClick={()=>onNavigate('chat')}><Sparkles size={18}/> Bắt đầu hỏi đáp <ArrowRight size={17}/></button><button className="ocop-hero-secondary" onClick={()=>onNavigate('documents')}>Khám phá tài liệu <ArrowRight size={16}/></button></div></div>
      <div className="ocop-hero-art" aria-hidden="true"><div className="ocop-art-circle one"/><div className="ocop-art-circle two"/><div className="ocop-art-circle three"/><div className="ocop-art-stem"/><div className="ocop-art-leaf l1"/><div className="ocop-art-leaf l2"/><div className="ocop-art-leaf l3"/><div className="ocop-art-caption">ONE COMMUNE · ONE PRODUCT</div></div>
    </div>
    <div className="ocop-section-line"><div><div className="ocop-eyebrow">KHO DỮ LIỆU</div><h2>Tri thức trong hệ thống</h2></div><span className="ocop-fact-label">Số liệu từ artifact hiện có</span></div>
    <div className="ocop-stats-grid"><CountCard label="Tài liệu nguồn" value={overview?.sources ?? '—'} note="PDF đã đăng ký" icon={BookOpen}/><CountCard label="Trang đã xử lý" value={overview?.pages.pages ?? '—'} note={`${overview?.pages.ocr_executed ?? '—'} trang chạy OCR`} icon={FileText}/><CountCard label="Dòng tiêu chí ứng viên" value={overview?.knowledge.criterion_candidates ?? '—'} note="Đang chờ kiểm chứng" icon={ClipboardList}/><CountCard label="Liên kết graph" value={((overview?.graph.checks?.edges.passed ?? 0) + (overview?.graph.checks?.edges.human_verified ?? 0))} note="Quan hệ từ dữ liệu trích xuất" icon={GitBranch}/></div>
    <div className="ocop-overview-columns"><div className="ocop-overview-main"><div className="ocop-section-line compact"><div><div className="ocop-eyebrow">TRUY VẤN NHANH</div><h2>Bạn đang quan tâm đến...</h2></div><button className="ocop-link" onClick={()=>onNavigate('chat')}>Mở trợ lý <ArrowRight size={15}/></button></div>
      <div className="ocop-quick-grid">{samplePrompts.map((p,i)=><button className="ocop-quick-action" onClick={()=>askPrompt(p.detail)} key={p.title}><span className="ocop-quick-count">0{i+1}</span><strong>{p.title}</strong><p>{p.detail}</p><ArrowRight size={17}/></button>)}</div>
    </div><div className="ocop-overview-aside"><div className="ocop-section-line compact"><div><div className="ocop-eyebrow">NGUỒN THAM CHIẾU</div><h2>Văn bản trọng tâm</h2></div></div>
      {featured&&<button className="ocop-featured-source" onClick={()=>openPdf(featured)}><div className="ocop-featured-top"><span><FileText size={18}/></span><span>OCOP 2026</span></div><h3>{sourceTitle(featured)}</h3><p>Quy định, phân loại sản phẩm, bảng tiêu chí và các biểu mẫu.</p><div className="ocop-featured-footer">Mở PDF · {featured.page_count} trang <ExternalLink size={16}/></div></button>}
      <div className="ocop-side-notice"><ShieldAlert size={18}/><p>Hệ thống đang sử dụng dữ liệu trích xuất tự động. Đối chiếu PDF trước khi áp dụng điểm số hoặc kết luận pháp lý.</p></div>
    </div></div>
  </div>
}

function SystemView({ overview, health, refresh, refreshing }: { overview: Overview | null; health: Health | null; refresh: ()=>void; refreshing: boolean }) {
  const features = [
    ['Corpus nguồn', `${overview?.sources ?? '—'} PDF / ${overview?.pages.pages ?? '—'} trang`, !!overview?.pages.pages],
    ['OCR và xử lý PDF', `${overview?.pages.ocr_executed ?? '—'} trang OCR`, !!overview?.pages.pages],
    ['BM25 Index', `${overview?.index.counts?.chunks ?? '—'} chunks`, overview?.index.status === 'sparse_ready' || overview?.index.status === 'published'],
    ['Dense Qdrant', overview?.index.dense?.enabled ? 'Đã có vector' : 'Chưa tạo embeddings', !!overview?.index.dense?.enabled],
    ['Knowledge Graph', `${((overview?.graph.checks?.nodes.passed ?? 0) + (overview?.graph.checks?.nodes.human_verified ?? 0))} nodes · ${((overview?.graph.checks?.edges.passed ?? 0) + (overview?.graph.checks?.edges.human_verified ?? 0))} edges`, !!((overview?.graph.checks?.nodes.passed ?? 0) + (overview?.graph.checks?.nodes.human_verified ?? 0))],
    ['Neo4j server', overview?.graph.neo4j?.enabled ? 'Đã bật' : 'Chưa kết nối thực tế', !!overview?.graph.neo4j?.enabled],
    ['Bằng chứng xác minh', 'Ứng viên chưa kiểm định thủ công', false],
  ] as const
  return <div className="ocop-view-scroll"><div className="ocop-page-heading"><div className="ocop-eyebrow">VẬN HÀNH DỮ LIỆU</div><h1>Trạng thái hệ thống</h1><p>Theo dõi các thành phần đang có thực trong corpus và dịch vụ.</p></div>
    <div className="ocop-section-line compact"><h2>Tổng quan hệ thống</h2><button className="ocop-button-quiet" onClick={refresh} disabled={refreshing}><RefreshCcw size={16} className={refreshing?'ocop-spinning':''}/> Làm mới</button></div>
    <div className="ocop-health-banner"><span className={`ocop-status-dot ${health?.status==='ready'?'online':'offline'}`}/><div><strong>{health?.status==='ready'?'Chỉ mục dữ liệu OCOP sẵn sàng':'Không thể xác nhận trạng thái chỉ mục'}</strong><p>Corpus version: {overview?.index.corpus_version || 'Chưa có'} · Chế độ kiểm tra dữ liệu ứng viên</p></div></div>
    <div className="ocop-component-list">{features.map(([name,detail,ok])=><div className="ocop-component" key={name}><span className={`ocop-component-icon ${ok?'healthy':''}`}>{ok?<Check size={17}/>:<Activity size={17}/>}</span><div><strong>{name}</strong><small>{detail}</small></div><span className={`ocop-pill ${ok?'good':'neutral'}`}>{ok?'Có dữ liệu':'Chưa sẵn sàng'}</span></div>)}</div>
    <div className="ocop-notice"><ShieldAlert size={18}/><div><strong>Chưa phải hệ thống được nghiệm thu hoàn chỉnh</strong><p>Dense retrieval, Neo4j và LLM diễn giải chưa được khẳng định hoạt động từ bảng điều khiển này. Trạng thái OCR là ứng viên, không có hiệu lực xác nhận pháp lý.</p></div></div>
  </div>
}

export default function Dashboard() {
  const [section, setSection] = useState<Section>('overview')
  const [mobileOpen, setMobileOpen] = useState(false)
  const [sources, setSources] = useState<Source[]>([])
  const [overview, setOverview] = useState<Overview | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [chatEpoch, setChatEpoch] = useState(0)
  const [chatPrefill, setChatPrefill] = useState('')
  const [pdf, setPdf] = useState<{ source: Source; page: number } | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  useEffect(() => { document.title = 'OCOP RAG — Không gian tri thức OCOP' }, [])
  const refresh = () => {
    setRefreshing(true)
    Promise.allSettled([api.overview(), api.sources(), api.health()]).then(([o,s,h])=>{
      if(o.status==='fulfilled')setOverview(o.value)
      if(s.status==='fulfilled')setSources(s.value)
      if(h.status==='fulfilled'){setHealth(h.value);setError('')}
      else setError('Không thể kết nối tới API OCOP. Hãy khởi động backend trên cổng 8000.')
    }).finally(()=>setRefreshing(false))
  }
  useEffect(()=>{refresh()},[])
  const go = (s: Section) => { setSection(s); setMobileOpen(false) }
  const ask = (text: string) => { setChatPrefill(text); go('chat') }
  return <div className="ocop-app">
    <Sidebar section={section} onNavigate={go} open={mobileOpen} onClose={()=>setMobileOpen(false)} healthy={health?.status==='ready'} onNewChat={()=>{setMessages([]);setChatPrefill('');setChatEpoch(n=>n+1)}}/>
    <main className="ocop-main"><header className="ocop-header"><div className="ocop-header-left"><button aria-label="Mở điều hướng" className="ocop-menu-toggle" onClick={()=>setMobileOpen(true)}><Menu size={21}/></button><span className="ocop-header-breadcrumb">KHÔNG GIAN OCOP <ChevronRight size={14}/></span><strong>{headings[section]}</strong></div><div className="ocop-header-right"><span className="ocop-header-live"><span className={`ocop-status-dot ${health?.status==='ready'?'online':'offline'}`}/>{health?.status==='ready'?'Dữ liệu sẵn sàng':'Đang chờ kết nối'}</span><div className="ocop-header-avatar"><Leaf size={17}/></div></div></header>
      {error && <div className="ocop-api-banner"><ShieldAlert size={16}/>{error}<button onClick={refresh}>Thử lại</button></div>}
      <div className="ocop-main-content">
        {section==='overview'&&<OverviewView overview={overview} sources={sources} onNavigate={go} openPdf={(source,page=1)=>setPdf({source,page})} askPrompt={ask}/>} 
        {section==='chat'&&<Chat key={chatEpoch} prefill={chatPrefill} clearPrefill={()=>setChatPrefill('')} messages={messages} setMessages={setMessages} sources={sources} denseReady={!!overview?.index.dense?.enabled} openPdf={(source,page=1)=>setPdf({source,page})}/>}
        {section==='criteria'&&<Criteria sources={sources} openPdf={(source,page=1)=>setPdf({source,page})}/>}
        {section==='forms'&&<Forms sources={sources} openPdf={(source,page=1)=>setPdf({source,page})}/>}
        {section==='recognitions'&&<Recognitions sources={sources} openPdf={(source,page=1)=>setPdf({source,page})}/>}
        {section==='documents'&&<Sources sources={sources} openPdf={(source,page=1)=>setPdf({source,page})}/>}
        {section==='graph'&&<KnowledgeGraph sources={sources} openPdf={(source,page=1)=>setPdf({source,page})}/>}
        {section==='system'&&<SystemView overview={overview} health={health} refresh={refresh} refreshing={refreshing}/>}
        {section==='review'&&<Review/>}
      </div>
    </main>
    {pdf&&<div className="ocop-modal-backdrop" role="presentation" onMouseDown={e=>{if(e.target===e.currentTarget)setPdf(null)}}><div className="ocop-pdf-modal" role="dialog" aria-modal="true" aria-label={`PDF ${sourceTitle(pdf.source)}`}><div className="ocop-pdf-header"><div><span className="ocop-eyebrow">PDF GỐC · TRANG {pdf.page}</span><strong>{sourceTitle(pdf.source)}</strong></div><div><a href={api.pdf(pdf.source.source_id,pdf.page)} rel="noreferrer" target="_blank" className="ocop-text-link"><ExternalLink size={15}/> Mở tab mới</a><button aria-label="Đóng PDF" onClick={()=>setPdf(null)}><X size={20}/></button></div></div><iframe title={`${sourceTitle(pdf.source)} – trang ${pdf.page}`} src={api.pdf(pdf.source.source_id,pdf.page)}/></div></div>}
  </div>
}
