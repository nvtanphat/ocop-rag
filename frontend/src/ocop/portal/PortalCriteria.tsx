import React, { useMemo } from 'react'
import type { CritRecord, ActiveView } from './types'
import { norm, esc } from './utils'

interface PortalCriteriaProps {
  crMap: Record<string, CritRecord[]>
  critDoc: '148' | '26'
  setCritDoc: (doc: '148' | '26') => void
  critQ: string
  setCritQ: (q: string) => void
  critPage: number
  setCritPage: React.Dispatch<React.SetStateAction<number>>
  critPer: number
  setCritPer: (n: number) => void
  critChecked: Record<string, boolean>
  setCritChecked: React.Dispatch<React.SetStateAction<Record<string, boolean>>>
  setActiveView: (view: ActiveView) => void
  openSrc: (sid: string, page?: number) => void
}

export const PortalCriteria: React.FC<PortalCriteriaProps> = ({
  crMap,
  critDoc,
  setCritDoc,
  critQ,
  setCritQ,
  critPage,
  setCritPage,
  critPer,
  setCritPer,
  critChecked,
  setCritChecked,
  setActiveView,
  openSrc,
}) => {
  const filteredCrit = useMemo(() => {
    const list = crMap[critDoc] || []
    if (!critQ) return list
    const q = norm(critQ)
    return list.filter((r) => norm(r.t).includes(q))
  }, [crMap, critDoc, critQ])

  const critPages = Math.max(1, Math.ceil(filteredCrit.length / critPer))
  const pagedCrit = filteredCrit.slice((critPage - 1) * critPer, critPage * critPer)

  return (
    <section className="glass view" data-v="crit" id="v-crit">
      <div className="vhead">
        <div className="vico" style={{ background: '#fff0d6', color: '#e8930c' }}>
          <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor">
            <rect x="4" y="11" width="4" height="9" rx="1" />
            <rect x="10" y="6" width="4" height="14" rx="1" />
            <rect x="16" y="13" width="4" height="7" rx="1" />
          </svg>
        </div>
        <div className="vt">
          <h2>Bảng Tiêu chí Chấm điểm OCOP</h2>
          <p>Tra cứu toàn bộ tiêu chí kỹ thuật và thang điểm phân hạng sản phẩm (Quyết định 148/QĐ-TTg)</p>
        </div>
      </div>

      <div className="crow">
        <label className="fld">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <circle cx="11" cy="11" r="7" />
            <path d="M16 16l5 5" />
          </svg>
          <input
            id="cQ"
            type="text"
            placeholder="Tìm kiếm nội dung tiêu chí (ví dụ: an toàn thực phẩm, bao bì...)"
            autoComplete="off"
            value={critQ}
            onChange={(e) => {
              setCritQ(e.target.value)
              setCritPage(1)
            }}
          />
        </label>
        <select
          className="sel"
          id="cDoc"
          style={{ width: 300 }}
          value={critDoc}
          onChange={(e) => {
            setCritDoc(e.target.value as '148' | '26')
            setCritPage(1)
          }}
        >
          <option value="148">Quyết định 148/QĐ-TTg (mặc định)</option>
          <option value="26">Quyết định 26/QĐ-BNN-VPĐP</option>
        </select>
        <button type="button" className="btn-g" id="cGo" onClick={() => setCritPage(1)}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round">
            <circle cx="11" cy="11" r="7" />
            <path d="M16 16l5 5" />
          </svg>
          Tìm kiếm
        </button>
      </div>

      <div className="cinfo">
        <span className="chip green" id="cTotal">Tổng {filteredCrit.length} tiêu chí</span>
        <span id="cShow">Hiển thị {pagedCrit.length} / {filteredCrit.length} kết quả</span>
        <span style={{ marginLeft: 'auto' }}>Hiển thị</span>
        <select
          className="sel"
          id="cPer"
          value={critPer}
          onChange={(e) => {
            setCritPer(+e.target.value)
            setCritPage(1)
          }}
        >
          <option value={25}>25</option>
          <option value={50}>50</option>
          <option value={100}>100</option>
        </select>
        <span>/ trang</span>
      </div>

      <div className="tbl2" id="cWrap">
        <table>
          <thead>
            <tr>
              <th style={{ width: 44 }}>
                <input
                  type="checkbox"
                  id="cAll"
                  checked={pagedCrit.length > 0 && pagedCrit.every((r) => critChecked[`${critDoc}-${r.n}`])}
                  onChange={(e) => {
                    const checked = e.target.checked
                    setCritChecked((prev) => {
                      const next = { ...prev }
                      pagedCrit.forEach((r) => {
                        next[`${critDoc}-${r.n}`] = checked
                      })
                      return next
                    })
                  }}
                />
              </th>
              <th style={{ width: 60 }}>#</th>
              <th>Nội dung tiêu chí</th>
              <th style={{ width: 200 }}>Căn cứ văn bản</th>
              <th style={{ width: 100 }}>Trang PDF</th>
              <th style={{ width: 130 }}>Hành động</th>
            </tr>
          </thead>
          <tbody>
            {pagedCrit.length === 0 ? (
              <tr>
                <td colSpan={6} style={{ textAlign: 'center', padding: 40, color: 'var(--muted)' }}>
                  Không tìm thấy tiêu chí phù hợp.
                </td>
              </tr>
            ) : (
              pagedCrit.map((r) => {
                const key = `${critDoc}-${r.n}`
                return (
                  <tr key={r.n}>
                    <td>
                      <input
                        type="checkbox"
                        checked={!!critChecked[key]}
                        onChange={(e) => {
                          const checked = e.target.checked
                          setCritChecked((prev) => ({ ...prev, [key]: checked }))
                        }}
                      />
                    </td>
                    <td className="n">{r.n}</td>
                    <td>
                      {critQ ? (
                        <span
                          dangerouslySetInnerHTML={{
                            __html: esc(r.t).replace(
                              new RegExp(`(${esc(critQ)})`, 'gi'),
                              '<mark>$1</mark>'
                            ),
                          }}
                        />
                      ) : (
                        r.t
                      )}
                    </td>
                    <td>{r.doc}</td>
                    <td>{r.page}</td>
                    <td>
                      <button
                        type="button"
                        className="xem"
                        onClick={() => {
                          setActiveView('chat')
                          openSrc(r.src, r.page)
                        }}
                      >
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <rect x="5" y="3" width="14" height="18" rx="2" />
                          <path d="M9 8h6M9 12h6" />
                        </svg>
                        Xem PDF
                      </button>
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="pager" id="cPager">
        <button type="button" disabled={critPage <= 1} onClick={() => setCritPage((p) => Math.max(1, p - 1))}>‹</button>
        {Array.from({ length: critPages }).map((_, i) => (
          <button
            key={i + 1}
            type="button"
            className={critPage === i + 1 ? 'on' : ''}
            onClick={() => setCritPage(i + 1)}
          >
            {i + 1}
          </button>
        ))}
        <button type="button" disabled={critPage >= critPages} onClick={() => setCritPage((p) => Math.min(critPages, p + 1))}>›</button>
      </div>
      <div className="demo">Dữ liệu trích xuất từ Phụ lục I - QĐ 148/QĐ-TTg</div>
    </section>
  )
}
