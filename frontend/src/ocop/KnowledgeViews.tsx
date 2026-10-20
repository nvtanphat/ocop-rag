import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, ArrowDown, ArrowRight, BookMarked, ChevronLeft, ChevronRight, ExternalLink, FileSearch, FileText, Filter, Search, ShieldAlert } from 'lucide-react'
import { api } from './api'
import type { Criterion, FormCandidate, GraphData, Recognition, Source } from './api'
import { categoryOf, sourceTitle } from './catalog'

function useDebounce(value: string, ms = 250) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => { const id = window.setTimeout(() => setDebounced(value), ms); return () => clearTimeout(id) }, [value, ms])
  return debounced
}
export function CandidateBanner() { return <div className="ocop-notice"><ShieldAlert size={18}/><div><strong>Dữ liệu đang ở trạng thái trích xuất tự động</strong><p>Điểm số, dòng bảng và thông tin công nhận có thể sai do OCR. Đây không phải kết quả được xác minh hoặc phân hạng chính thức.</p></div></div> }

export function Sources({ sources, openPdf }: { sources: Source[]; openPdf: (s: Source, page?: number) => void }) {
  const [q, setQ] = useState('')
  const [category, setCategory] = useState('Tất cả')
  const categories = ['Tất cả', ...Array.from(new Set(sources.map(categoryOf)))]
  const data = sources.filter(s => (category === 'Tất cả' || categoryOf(s) === category) && `${sourceTitle(s)} ${s.document_number || ''} ${s.jurisdiction || ''}`.toLocaleLowerCase('vi').includes(q.toLocaleLowerCase('vi')))
  return <div className="ocop-view-scroll"><div className="ocop-page-heading"><div className="ocop-eyebrow">THƯ VIỆN TÀI LIỆU</div><h1>Văn bản & nguồn OCOP</h1><p>Truy cập PDF gốc, đối chiếu trang và xuất xứ từng tài liệu trong corpus.</p></div>
    <div className="ocop-toolbar"><label className="ocop-search"><Search size={17}/><input placeholder="Tìm văn bản, số hiệu, địa phương..." value={q} onChange={e => setQ(e.target.value)}/></label><div className="ocop-filter"><Filter size={16}/><select value={category} onChange={e => setCategory(e.target.value)} aria-label="Lọc loại văn bản">{categories.map(c => <option key={c}>{c}</option>)}</select></div></div>
    <div className="ocop-results-count">{data.length} tài liệu · các nguồn có bản PDF được đăng ký</div>
    <div className="ocop-sources-grid">{data.map(s => <button className="ocop-doc-card" key={s.source_id} onClick={() => openPdf(s)}>
      <div className="ocop-doc-top"><span className="ocop-doc-icon"><FileText size={20}/></span><span className="ocop-doc-category">{categoryOf(s)}</span><ExternalLink size={16}/></div>
      <h3>{sourceTitle(s)}</h3><p>{s.document_number || s.jurisdiction || 'Tài liệu OCOP'}</p>
      <div className="ocop-doc-footer"><span>{s.page_count} trang</span><span>{s.ocr_pages > 0 ? `${s.ocr_pages} trang OCR` : 'Có lớp văn bản'}</span><ArrowRight size={16}/></div>
    </button>)}</div>
    {data.length === 0 && <div className="ocop-empty">Không tìm thấy tài liệu phù hợp. Hãy thử từ khóa khác.</div>}
  </div>
}

function Pager({ offset, limit, total, setOffset }: { offset: number; limit: number; total: number; setOffset: (v: number) => void }) { return <div className="ocop-pager"><span>Hiển thị {total ? offset + 1 : 0}–{Math.min(total, offset + limit)} / {total}</span><button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))} aria-label="Trang trước"><ChevronLeft size={17}/></button><button disabled={offset + limit >= total} onClick={() => setOffset(offset + limit)} aria-label="Trang tiếp"><ChevronRight size={17}/></button></div> }

export function Criteria({ sources, openPdf }: { sources: Source[]; openPdf: (s: Source, page?: number) => void }) {
  const [q, setQ] = useState(''); const [sourceId, setSourceId] = useState(''); const [offset, setOffset] = useState(0)
  const [items, setItems] = useState<Criterion[]>([]); const [total, setTotal] = useState(0); const [error, setError] = useState(''); const [loading, setLoading] = useState(false)
  const keyword = useDebounce(q)
  useEffect(() => { let live = true; setLoading(true); setError(''); api.criteria({q:keyword,source_id:sourceId,offset,limit:25}).then(data => { if(live){setItems(data.items);setTotal(data.total)}}).catch(e => {if(live) setError(String(e))}).finally(() => { if(live)setLoading(false) }); return () => { live = false } }, [keyword, sourceId, offset])
  return <div className="ocop-view-scroll"><div className="ocop-page-heading"><div className="ocop-eyebrow">TRA CỨU CÓ CĂN CỨ</div><h1>Bộ tiêu chí đánh giá</h1><p>Khám phá các dòng bảng tiêu chí trích từ quyết định OCOP theo phiên bản.</p></div><CandidateBanner/>
    <div className="ocop-toolbar"><label className="ocop-search"><Search size={17}/><input value={q} onChange={e=>{setQ(e.target.value);setOffset(0)}} placeholder="Tìm trong nội dung tiêu chí..."/></label><div className="ocop-filter"><Filter size={16}/><select value={sourceId} onChange={e=>{setSourceId(e.target.value);setOffset(0)}} aria-label="Chọn văn bản"><option value="">Mọi văn bản</option>{sources.filter(s=>s.source_id.includes('OCOP')).map(s=><option key={s.source_id} value={s.source_id}>{s.document_number || s.source_id}</option>)}</select></div></div>
    {error && <div className="ocop-chat-error">{error}</div>}
    <div className="ocop-table-container"><table className="ocop-data-table"><thead><tr><th>TIÊU CHÍ / NỘI DUNG OCR</th><th>NGUỒN</th><th>TRẠNG THÁI KIỂM TRA</th><th>TRANG</th></tr></thead><tbody>
      {items.map(c => { const s=sources.find(s=>s.source_id===c.source_id); return <tr key={c.node_id}><td><div className="ocop-table-name">{c.label || '(Không đọc được nội dung)'}</div><div className="ocop-table-sub">{c.origin}</div></td><td><span className="ocop-text-muted">{s?.document_number || c.source_id}</span></td><td><span className="ocop-pill neutral">{c.check}</span></td><td><button className="ocop-text-link" disabled={!s} onClick={()=>s&&openPdf(s,c.citations?.[0]?.pdf_page)}>Tr.{c.citations?.[0]?.pdf_page} <ExternalLink size={13}/></button></td></tr>})}
    </tbody></table>{loading && <div className="ocop-loading-line">Đang tải dữ liệu...</div>}{!loading&&!items.length && <div className="ocop-empty">Chưa có kết quả phù hợp.</div>}</div><Pager offset={offset} limit={25} total={total} setOffset={setOffset}/>
  </div>
}

export function Recognitions({ sources, openPdf }: { sources: Source[]; openPdf: (s: Source, page?: number) => void }) {
  const [q, setQ] = useState(''); const [offset, setOffset] = useState(0); const [items, setItems] = useState<Recognition[]>([]); const [total, setTotal] = useState(0)
  const [error, setError] = useState(''); const keyword = useDebounce(q)
  useEffect(()=>{let live=true;setError(''); api.recognitions({q:keyword,offset,limit:20}).then(d=>{if(live){setItems(d.items);setTotal(d.total)}}).catch(e=>{if(live)setError(String(e))});return()=>{live=false}},[keyword,offset])
  return <div className="ocop-view-scroll"><div className="ocop-page-heading"><div className="ocop-eyebrow">DỮ LIỆU CÔNG NHẬN</div><h1>Sản phẩm OCOP đã công bố</h1><p>Các dòng ứng viên được trích từ quyết định công nhận tại Huế và Hải Phòng.</p></div><CandidateBanner/>
    <div className="ocop-toolbar"><label className="ocop-search"><Search size={17}/><input value={q} onChange={e=>{setQ(e.target.value);setOffset(0)}} placeholder="Tìm sản phẩm, chủ thể, địa phương..."/></label><div className="ocop-results-count">{total} dòng ứng viên công nhận</div></div>
    {error && <div className="ocop-chat-error">{error}</div>}
    <div className="ocop-table-container"><table className="ocop-data-table"><thead><tr><th>THÔNG TIN TRÍCH XUẤT TỪ BẢNG</th><th>QUYẾT ĐỊNH</th><th>TRẠNG THÁI KIỂM TRA</th><th>PDF</th></tr></thead><tbody>{items.map(r=>{const s=sources.find(s=>s.source_id===r.source_id);return <tr key={r.node_id}><td><div className="ocop-table-name">{r.linked_labels.join(' / ') || r.label}</div><div className="ocop-table-sub">{r.origin}</div></td><td className="ocop-text-muted">{s?.document_number || r.source_id}</td><td><span className="ocop-pill neutral">{r.check}</span></td><td><button disabled={!s} className="ocop-text-link" onClick={()=>s&&openPdf(s,r.citations?.[0]?.pdf_page)}>Tr.{r.citations?.[0]?.pdf_page} <ExternalLink size={13}/></button></td></tr>})}</tbody></table>{!items.length && <div className="ocop-empty">Không có ứng viên phù hợp.</div>}</div><Pager offset={offset} limit={20} total={total} setOffset={setOffset}/>
  </div>
}

export function KnowledgeGraph({ sources, openPdf }: { sources: Source[]; openPdf: (s: Source, page?: number) => void }) {
  const [q, setQ] = useState(''); const [type, setType] = useState(''); const [data, setData] = useState<GraphData>({nodes:[],edges:[],total_matches:0,kind:''}); const [selected, setSelected] = useState(''); const [error, setError] = useState('')
  const keyword = useDebounce(q)
  useEffect(()=>{let live=true;api.graph({q:keyword,node_type:type,limit:100}).then(d=>{if(live){setData(d);setSelected(prev=>d.nodes.some(n=>n.node_id===prev)?prev:(d.nodes[0]?.node_id||''));setError('')}}).catch(e=>{if(live)setError(String(e))});return()=>{live=false}},[keyword,type])
  const selectedNode = data.nodes.find(n=>n.node_id===selected)
  const neighbors = useMemo(()=>data.edges.filter(e=>(e.source_entity_id || e.source_id)===selected || (e.target_entity_id || e.target_id)===selected),[data.edges,selected])
  return <div className="ocop-view-scroll"><div className="ocop-page-heading"><div className="ocop-eyebrow">KNOWLEDGE GRAPH</div><h1>Đồ thị tri thức OCOP</h1><p>Khám phá các thực thể và quan hệ đã kiểm tra theo nguồn PDF.</p></div>
    <div className="ocop-toolbar"><label className="ocop-search"><Search size={17}/><input placeholder="Tìm thực thể trong graph..." value={q} onChange={e=>setQ(e.target.value)}/></label><div className="ocop-filter"><Filter size={16}/><select value={type} onChange={e=>setType(e.target.value)} aria-label="Loại node"><option value="">Nhóm node chính</option>{['SourceDocument','Criterion','Product','Organization','RecognitionDecision','ProductGroup','FormTemplate','EvidenceUnit'].map(t=><option key={t} value={t}>{t}</option>)}</select></div></div>
    {error && <div className="ocop-chat-error">{error}</div>}
    <div className="ocop-graph-layout"><div className="ocop-node-list"><div className="ocop-panel-heading">THỰC THỂ <span>{data.total_matches} tìm thấy</span></div>{data.nodes.map(node=><button key={node.node_id} onClick={()=>setSelected(node.node_id)} className={`ocop-node-row ${selected===node.node_id?'active':''}`}><span className="ocop-node-icon"><BookMarked size={16}/></span><span><strong>{node.label}</strong><small>{node.node_type}</small></span><ChevronRight size={16}/></button>)}{!data.nodes.length&&<div className="ocop-empty">Không có node phù hợp.</div>}</div>
      <div className="ocop-node-detail">{selectedNode ? <><div className="ocop-node-feature"><div className="ocop-eyebrow">NODE ĐANG CHỌN</div><span className="ocop-pill neutral">{selectedNode.node_type}</span><h2>{selectedNode.label}</h2><p>{selectedNode.validation?.status === 'source_grounded' ? 'Đã kiểm tra tự động theo nguồn. Trạng thái này không xác nhận hiệu lực pháp lý hoặc điểm, hạng sao.' : 'Chưa đủ căn cứ'}</p></div>
        <div className="ocop-panel-heading">QUAN HỆ TRONG TẬP ĐANG XEM <span>{neighbors.length}</span></div>{neighbors.length ? neighbors.map((edge,i)=><div className="ocop-relation-row" key={i}><span><ArrowDown size={15}/>{edge.relation_type || 'RELATED'}</span><strong>{data.nodes.find(n=>n.node_id===(edge.target_entity_id||edge.target_id) && n.node_id!==selected || n.node_id===(edge.source_entity_id||edge.source_id) && n.node_id!==selected)?.label || 'Thực thể liên quan'}</strong></div>) : <div className="ocop-graph-empty"><FileSearch size={30}/><p>Chưa có quan hệ trong tập node được tải. Tìm một node cụ thể hoặc xem nguồn PDF.</p></div>}
        {selectedNode.source_id&&sources.some(s=>s.source_id===selectedNode.source_id)&&<button className="ocop-secondary-action" onClick={()=>{const s=sources.find(s=>s.source_id===selectedNode.source_id);if(s)openPdf(s,selectedNode.citations?.[0]?.pdf_page)}}>Xem tài liệu gốc <ExternalLink size={15}/></button>}
      </> : <div className="ocop-empty">Chọn một thực thể để xem quan hệ.</div>}</div></div>
  </div>
}

export function Forms({ sources, openPdf }: { sources: Source[]; openPdf: (s: Source, page?: number) => void }) {
  const [items, setItems] = useState<FormCandidate[]>([])
  const [error, setError] = useState('')
  useEffect(() => { api.forms().then(d => setItems(d.items)).catch(e => setError(String(e))) }, [])
  return <div className="ocop-view-scroll"><div className="ocop-page-heading"><div className="ocop-eyebrow">PHỤ LỤC HỒ SƠ</div><h1>Biểu mẫu OCOP</h1><p>Tra cứu thông tin của các mẫu đã nhận diện từ PDF; đối chiếu với phụ lục gốc trước khi sử dụng.</p></div><CandidateBanner/>
    <div className="ocop-notice"><AlertTriangle size={18}/><div><strong>Danh mục biểu mẫu chưa đầy đủ</strong><p>Hiện chỉ có {items.length} ứng viên được parser nhận dạng; không suy diễn biểu mẫu còn thiếu từ số hiệu hoặc văn bản khác.</p></div></div>
    {error && <div className="ocop-chat-error">{error}</div>}
    <div className="ocop-forms-grid">{items.map(f => { const s = sources.find(s=>s.source_id === f.source_id); return <article className="ocop-form-card" key={f.node_id}><div className="ocop-form-icon"><FileText size={22}/></div><span className="ocop-eyebrow">BIỂU MẪU </span><h2>{f.label}</h2><p>{f.linked_labels.length} trường đã kiểm tra</p>{f.linked_labels.length>0 && <ul>{f.linked_labels.slice(0,5).map((field,i)=><li key={i}>{field}</li>)}</ul>}<button className="ocop-secondary-action" disabled={!s} onClick={()=>s&&openPdf(s,f.citations?.[0]?.pdf_page)}>Xem PDF trang {f.citations?.[0]?.pdf_page} <ExternalLink size={15}/></button></article>})}</div>
  </div>
}
