import { useEffect, useState } from 'react'
import { api, type ReviewItem } from './api'

export default function Review() {
  const [priority, setPriority] = useState('P1')
  const [includeDecided, setIncludeDecided] = useState(false)
  const [offset, setOffset] = useState(0)
  const [items, setItems] = useState<ReviewItem[]>([])
  const [total, setTotal] = useState(0)
  const [item, setItem] = useState<ReviewItem | null>(null)
  const [reviewer, setReviewer] = useState('')
  const [token, setToken] = useState('')
  const [notes, setNotes] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [checked, setChecked] = useState(false)
  const [label, setLabel] = useState('')
  const [field, setField] = useState('')
  const [value, setValue] = useState('')
  const [edits, setEdits] = useState<Record<string, unknown>>({})
  const reload = () => api.reviewQueue(priority, offset, includeDecided).then(r => {setItems(r.items); setTotal(r.total)})
  useEffect(() => {setItem(null); reload().catch(e => setError(e.message))}, [priority, offset, includeDecided])
  const select = async (target: ReviewItem) => {
    try {
      const current = await api.reviewItem(target.target_id)
      setItem(current); setLabel(current.label || ''); setField(''); setValue(''); setEdits({}); setChecked(false); setNotes(''); setError(''); setMessage('')
    } catch (e) {setError(e instanceof Error ? e.message : 'Không tải được mục duyệt')}
  }
  const parsedField = (): unknown => {
    const original = item?.properties[field]
    if (value === 'null') return null
    if (typeof original === 'boolean') {
      if (!['true','false'].includes(value)) throw new Error('Giá trị phải là true hoặc false')
      return value === 'true'
    }
    if (typeof original === 'number' || original === null && /points|score|star|deadline/.test(field)) {
      if (!value.trim() || !Number.isFinite(Number(value))) throw new Error('Cần nhập một số hợp lệ')
      return Number(value)
    }
    return value
  }
  const addEdit = () => {
    try {if (field) {setEdits({...edits,[field]:parsedField()}); setField(''); setValue(''); setError('')}}
    catch (e) {setError(e instanceof Error ? e.message : 'Giá trị sửa không hợp lệ')}
  }
  const decide = async (decision: 'approve' | 'reject' | 'correct') => {
    if (!item || !reviewer.trim() || !checked) return
    setBusy(true); setError('')
    try {
      const correction: {label?: string; properties?: Record<string, unknown>} = {}
      if (decision === 'correct') {
        if (label !== (item.label || '')) correction.label = label
        const values = {...edits,...(field ? {[field]:parsedField()} : {})}
        if (Object.keys(values).length) correction.properties = values
        if (!Object.keys(correction).length) throw new Error('Hãy nhập giá trị sửa trước khi gửi')
      }
      await api.reviewDecide({target_id: item.target_id, content_hash: item.content_hash, decision, reviewer,
        notes, ...(decision === 'correct' ? {correction} : {})}, token)
      setItem(null); setChecked(false); setMessage('Đã ghi quyết định. Mục chỉ được xác minh khi bằng chứng và các mục liên quan đã được duyệt.'); await reload()
    } catch (e) {setError(e instanceof Error ? e.message : 'Không ghi được quyết định')}
    finally {setBusy(false)}
  }
  return <div className="ocop-review">
    <div className="ocop-review-intro"><h2>Đối chiếu nguồn, xác nhận từng mục</h2><p>Ứng viên máy trích chưa phải thông tin đã xác minh. Duyệt điểm, sao và hiệu lực trước; đọc cả điều kiện và chú thích trong nguồn.</p></div>
    <div className="ocop-review-controls">
      <label>Ưu tiên <select value={priority} onChange={e => {setPriority(e.target.value); setOffset(0)}}>
        <option value="P1">P1 · Điểm, sao, hiệu lực</option><option value="P2">P2 · Hồ sơ, trách nhiệm, cần kiểm tra</option><option value="P3">P3 · Cấu trúc và danh mục</option>
      </select></label>
      <label>Người duyệt <input value={reviewer} onChange={e => setReviewer(e.target.value)} autoComplete="name"/></label>
      <label><input type="checkbox" checked={includeDecided} onChange={e => {setIncludeDecided(e.target.checked); setOffset(0)}}/> Hiện cả mục đã duyệt</label>
      <label>Mã truy cập (nếu được cấp) <input type="password" value={token} onChange={e => setToken(e.target.value)} autoComplete="off"/></label>
    </div>
    {error && <p role="alert" className="ocop-notice">{error}</p>}{message && <p role="status">{message}</p>}
    <div className="ocop-review-columns"><aside>
      <p>{total.toLocaleString('vi-VN')} mục đang chờ trong nhóm {priority}</p>
      {items.map(row => <button className={`ocop-review-row ${item?.target_id === row.target_id ? 'selected' : ''}`} key={row.target_id} onClick={() => select(row)}>
        <small>{row.type} · {row.source_id}</small><strong>{row.label || row.type}</strong>
        {row.state === 'stale_content_needs_review' && <em>Cần duyệt lại · Nội dung đã thay đổi</em>}
        {row.state.startsWith('waiting_') && <em>Đang chờ bằng chứng hoặc đầu cạnh</em>}
      </button>)}
      <div className="ocop-review-paging"><button disabled={offset === 0} onClick={() => setOffset(Math.max(0,offset-30))}>Trước</button><button disabled={offset+30 >= total} onClick={() => setOffset(offset+30)}>Tiếp</button></div>
    </aside><section aria-live="polite">
      {!item ? <p>Chọn một mục để xem giá trị ứng viên và ảnh nguồn.</p> : <>
        <h3>{item.label || item.type}</h3><p>{item.type} · {item.source_id}</p>
        <p>{item.priority} · {item.review_status}</p>
        <p>{item.check} · {item.origin}{item.check_reason && ` · ${item.check_reason}`}</p>
        <ul>{item.reasons.map(reason => <li key={reason}>{({score_star_or_temporal_assertion:'Điểm, sao hoặc hiệu lực cần xác nhận',document_role_or_responsibility:'Giấy tờ đầu vào hoặc trách nhiệm cần đối chiếu',source_structure_or_other_candidate:'Cấu trúc nguồn hoặc danh mục cần xác nhận',quality_mismatch_requires_review:'Kiểm số học hoặc chứng cứ chưa đủ',missing_ocr_value:'OCR chưa đọc được giá trị',needs_rereview:'Nội dung đã đổi, cần duyệt lại'} as Record<string,string>)[reason] || reason}</li>)}</ul>
        {item.latest_decision && <details><summary>Quyết định gần nhất</summary><p>{item.latest_decision.reviewer} · {item.latest_decision.timestamp} · {item.latest_decision.decision}</p><p>{item.latest_decision.notes}</p>{item.latest_decision.correction && <pre>{JSON.stringify(item.latest_decision.correction,null,2)}</pre>}</details>}
        <details open><summary>Giá trị máy trích</summary><pre>{JSON.stringify(item.properties,null,2)}</pre></details>
        <h4>Các mục cần duyệt riêng</h4>
        {item.dependencies.map(dep => <button key={dep.target_id} onClick={() => select({target_id: dep.target_id} as ReviewItem)}>
          {dep.type} · {dep.label || dep.target_id} · {dep.review_status}
        </button>)}
        <h4>Bằng chứng gốc ({item.citations.length})</h4>
        {item.citations.map((ref,i) => <figure key={i}><figcaption>{ref.source_id} · Trang {ref.pdf_page} · Bbox {ref.bbox?.join(', ')}
          {' '}<a href={`/api/ocop/sources/${encodeURIComponent(ref.source_id)}/pdf#page=${ref.pdf_page}`} target="_blank" rel="noreferrer">Mở trang PDF</a></figcaption>
          <blockquote>{ref.quote}</blockquote><img loading="lazy" src={ref.crop_url} alt={`Vùng nguồn trang ${ref.pdf_page}, bằng chứng ${i+1}`}/>
          <details><summary>SHA-256 nguồn</summary><code>{ref.source_sha256}</code></details></figure>)}
        <div className="ocop-review-edit"><h4>Sửa khẳng định khi cần</h4><p>Giá trị OCR gốc luôn được giữ. Giá trị sửa được ghi riêng dưới tên người duyệt.</p>
          {item.label !== null && <label>Nhãn <input value={label} onChange={e => setLabel(e.target.value)}/></label>}
          {item.type !== 'EvidenceUnit' && <><label>Thuộc tính cần sửa <select value={field} onChange={e => {setField(e.target.value); setValue(String(item.properties[e.target.value] ?? ''))}}>
            <option value="">Không sửa thuộc tính</option>{Object.entries(item.properties).filter(([,v]) => v === null || ['string','number','boolean'].includes(typeof v)).map(([key]) => <option key={key}>{key}</option>)}</select></label>
            {field && <><label>Giá trị xác nhận <input value={value} onChange={e => setValue(e.target.value)}/></label><button onClick={addEdit}>Thêm giá trị sửa</button></>}
            <ul>{Object.entries(edits).map(([key,val]) => <li key={key}>{key}: {String(val)} <button onClick={() => setEdits(Object.fromEntries(Object.entries(edits).filter(([k]) => k !== key)))}>Bỏ</button></li>)}</ul></>}
          <label>Ghi chú <textarea value={notes} onChange={e => setNotes(e.target.value)} rows={3}/></label>
          <label className="ocop-review-confirm"><input type="checkbox" checked={checked} onChange={e => setChecked(e.target.checked)}/>Tôi đã đọc toàn bộ bằng chứng và điều kiện của mục này.</label>
          <div className="ocop-review-actions"><button disabled={busy || !checked || !reviewer.trim()} onClick={() => decide('approve')}>Xác nhận giá trị máy trích</button>
            <button disabled={busy || !checked || !reviewer.trim() || item.type === 'EvidenceUnit'} onClick={() => decide('correct')}>Ghi giá trị sửa</button>
            <button disabled={busy || !checked || !reviewer.trim()} onClick={() => decide('reject')}>Loại ứng viên</button></div>
        </div>
      </>}
    </section></div>
  </div>
}
