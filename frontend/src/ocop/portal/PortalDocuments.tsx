import React, { useMemo } from 'react'
import type { DocRecord } from './types'
import { norm } from './utils'

interface PortalDocumentsProps {
  libDocs: DocRecord[]
  docCat: string
  setDocCat: (cat: string) => void
  docQ: string
  setDocQ: (q: string) => void
  docOrg: string
  setDocOrg: (org: string) => void
  docYear: string
  setDocYear: (year: string) => void
  docPage: number
  setDocPage: React.Dispatch<React.SetStateAction<number>>
  docPer: number
  setDocPer: (n: number) => void
  docIsList: boolean
  setDocIsList: (b: boolean) => void
  openSrc: (sid: string, page?: number) => void
  registerSource: (id: string, name: string, sub: string, total: number) => void
  toast: (msg: string) => void
}

export const PortalDocuments: React.FC<PortalDocumentsProps> = ({
  libDocs,
  docCat,
  setDocCat,
  docQ,
  setDocQ,
  docOrg,
  setDocOrg,
  docYear,
  setDocYear,
  docPage,
  setDocPage,
  docPer,
  setDocPer,
  docIsList,
  setDocIsList,
  openSrc,
  registerSource,
  toast,
}) => {
  const filtDocs = useMemo(() => {
    return libDocs.filter((d) => {
      if (docCat !== 'ALL' && d.cat !== docCat) return false
      if (docOrg && d.org !== docOrg) return false
      if (docYear && String(d.year) !== docYear) return false
      if (docQ) {
        const nq = norm(docQ)
        return norm(d.code).includes(nq) || norm(d.desc).includes(nq) || norm(d.org).includes(nq)
      }
      return true
    })
  }, [libDocs, docCat, docOrg, docYear, docQ])

  const docPages = Math.max(1, Math.ceil(filtDocs.length / docPer))
  const pagedDocs = filtDocs.slice((docPage - 1) * docPer, docPage * docPer)

  return (
    <section className="glass view" data-v="docs" id="v-docs">
      <div className="vhead">
        <div className="vico" style={{ background: '#e0ecff', color: '#2a6fdb' }}>
          <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor">
            <path d="M4 4a2 2 0 012-2h12a2 2 0 012 2v16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" />
          </svg>
        </div>
        <div className="vt">
          <h2>Thư viện văn bản pháp quy OCOP</h2>
          <p id="dSub">{libDocs.length} văn bản chính thống được sử dụng trong hệ thống</p>
        </div>
        <div className="vtools">
          <label className="fld" style={{ width: 240 }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <circle cx="11" cy="11" r="7" />
              <path d="M16 16l5 5" />
            </svg>
            <input
              id="dQ"
              type="text"
              placeholder="Tìm theo tên, số hiệu..."
              autoComplete="off"
              value={docQ}
              onChange={(e) => {
                setDocQ(e.target.value)
                setDocPage(1)
              }}
            />
          </label>
          <select
            className="sel"
            id="dOrg"
            value={docOrg}
            onChange={(e) => {
              setDocOrg(e.target.value)
              setDocPage(1)
            }}
          >
            <option value="">Cơ quan ban hành</option>
            {Array.from(new Set(libDocs.map((d) => d.org))).map((org) => (
              <option key={org} value={org}>{org}</option>
            ))}
          </select>
          <select
            className="sel"
            id="dYear"
            value={docYear}
            onChange={(e) => {
              setDocYear(e.target.value)
              setDocPage(1)
            }}
          >
            <option value="">Năm ban hành</option>
            {Array.from(new Set(libDocs.map((d) => d.year)))
              .sort((a, b) => b - a)
              .map((yr) => (
                <option key={yr} value={String(yr)}>{yr}</option>
              ))}
          </select>
        </div>
      </div>

      <div className="chiprow">
        <div id="dChips" style={{ display: 'flex', gap: 10 }}>
          {[
            ['ALL', 'Tất cả', null],
            ['QC', 'Quy chuẩn Quốc gia', '#e8453c'],
            ['DP', 'Quyết định Địa phương', '#f09a1a'],
            ['LN', 'Luật & Nghị định Ngành', '#e8453c'],
          ].map(([cat, label, col]) => {
            const count = cat === 'ALL' ? libDocs.length : libDocs.filter((d) => d.cat === cat).length
            return (
              <button
                key={cat as string}
                type="button"
                className={`chip ${docCat === cat ? 'on' : ''}`}
                onClick={() => {
                  setDocCat(cat as string)
                  setDocPage(1)
                }}
              >
                {col && <i style={{ background: col as string }} />}
                {label} ({count})
              </button>
            )
          })}
        </div>
        <div className="seg2">
          <button
            type="button"
            id="dGridB"
            className={!docIsList ? 'on' : ''}
            title="Dạng lưới"
            onClick={() => {
              setDocIsList(false)
              setDocPer(8)
              setDocPage(1)
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="4" y="4" width="6" height="6" rx="1" />
              <rect x="14" y="4" width="6" height="6" rx="1" />
              <rect x="4" y="14" width="6" height="6" rx="1" />
              <rect x="14" y="14" width="6" height="6" rx="1" />
            </svg>
          </button>
          <button
            type="button"
            id="dListB"
            className={docIsList ? 'on' : ''}
            title="Dạng danh sách"
            onClick={() => {
              setDocIsList(true)
              setDocPer(6)
              setDocPage(1)
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M5 7h14M5 12h14M5 17h14" />
            </svg>
          </button>
        </div>
      </div>

      <div className={`dgrid ${docIsList ? 'list' : ''}`} id="dGrid">
        {pagedDocs.length === 0 ? (
          <div className="empty">Không có văn bản phù hợp bộ lọc.</div>
        ) : (
          pagedDocs.map((d) => (
            <article key={d.id} className="dcard">
              <div className="dtop">
                <div className="dbadge" style={{ background: d.col }}>{d.badge}</div>
                <div>
                  <b>{d.code}</b>
                  <span>{d.desc}</span>
                </div>
              </div>
              <div className="dmeta">
                <div>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="8" r="4" />
                    <path d="M5 21c0-4 3-6 7-6s7 2 7 6" />
                  </svg>
                  {d.org}
                </div>
                <div>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="9" />
                    <path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18" />
                  </svg>
                  {d.scope}
                </div>
                <div className="two">
                  <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <rect x="5" y="3" width="14" height="18" rx="2" />
                    </svg>
                    {d.pages} trang
                  </span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <rect x="4" y="4" width="16" height="16" rx="3" />
                      <path d="M8 12l3 3 5-6" />
                    </svg>
                    Bản text điện tử
                  </span>
                </div>
              </div>
              <div className="dact">
                <button
                  type="button"
                  className="rd"
                  onClick={() => {
                    if (d.src) {
                      openSrc(d.src)
                    } else {
                      registerSource(d.id, d.code, d.desc, d.pages)
                      openSrc(d.id, 1)
                    }
                  }}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <rect x="5" y="3" width="14" height="18" rx="2" />
                    <path d="M9 8h6M9 12h6" />
                  </svg>
                  Đọc PDF
                </button>
                <button type="button" className="dl" onClick={() => toast(`Tải xuống ${d.code}: Chưa kết nối kho tệp trong bản demo`)}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                    <path d="M12 4v11M7 10l5 5 5-5M5 20h14" />
                  </svg>
                  Tải xuống
                </button>
              </div>
            </article>
          ))
        )}
      </div>

      <div className="pager" id="dPager">
        <button type="button" disabled={docPage <= 1} onClick={() => setDocPage((p) => Math.max(1, p - 1))}>‹</button>
        {Array.from({ length: docPages }).map((_, i) => (
          <button
            key={i + 1}
            type="button"
            className={docPage === i + 1 ? 'on' : ''}
            onClick={() => setDocPage(i + 1)}
          >
            {i + 1}
          </button>
        ))}
        <button type="button" disabled={docPage >= docPages} onClick={() => setDocPage((p) => Math.min(docPages, p + 1))}>›</button>
      </div>
      <div className="demo">Dữ liệu chính thống và trích đoạn đối soát</div>
    </section>
  )
}
