import React, { useMemo } from 'react'
import { IMAGES } from '../assets'
import type { ProdRecord, ActiveView } from './types'
import { norm } from './utils'
import { KINDS_MAP } from './data'

interface PortalProductsProps {
  prodList: ProdRecord[]
  prodQ: string
  setProdQ: (q: string) => void
  prodLoc: string
  setProdLoc: (loc: string) => void
  prodStar: string
  setProdStar: (star: string) => void
  prodPage: number
  setProdPage: React.Dispatch<React.SetStateAction<number>>
  prodPer: number
  setProdPer: (n: number) => void
  prodIsTable: boolean
  setProdIsTable: (b: boolean) => void
  exportProdCsv: () => void
  registerSource: (id: string, name: string, sub: string, total: number) => void
  setActiveView: (view: ActiveView) => void
  openSrc: (sid: string, page?: number) => void
}

export const PortalProducts: React.FC<PortalProductsProps> = ({
  prodList,
  prodQ,
  setProdQ,
  prodLoc,
  setProdLoc,
  prodStar,
  setProdStar,
  prodPage,
  setProdPage,
  prodPer,
  setProdPer,
  prodIsTable,
  setProdIsTable,
  exportProdCsv,
  registerSource,
  setActiveView,
  openSrc,
}) => {
  const filteredProds = useMemo(() => {
    return prodList.filter((p) => {
      if (prodLoc && p.loc !== prodLoc) return false
      if (prodStar && String(p.stars) !== prodStar) return false
      if (prodQ) {
        const q = norm(prodQ)
        return norm(p.name).includes(q) || norm(p.owner).includes(q) || norm(p.loc).includes(q)
      }
      return true
    })
  }, [prodList, prodLoc, prodStar, prodQ])

  const prodPages = Math.max(1, Math.ceil(filteredProds.length / prodPer))
  const pagedProds = filteredProds.slice((prodPage - 1) * prodPer, prodPage * prodPer)

  const renderGlyph = (kind: string) => {
    const c = KINDS_MAP[kind]?.[1] || '#c4623b'
    switch (kind) {
      case 'bottle':
        return <svg width="84" height="84" viewBox="0 0 64 64" fill="none"><rect x="24" y="22" width="16" height="34" rx="4" fill="#fff" opacity=".9"/><rect x="28" y="10" width="8" height="12" rx="2" fill="#fff"/><rect x="24" y="32" width="16" height="12" fill={c}/></svg>
      case 'tea':
        return <svg width="84" height="84" viewBox="0 0 64 64" fill="none"><path d="M14 26h30v10a15 15 0 01-30 0z" fill="#fff"/><path d="M44 28h6a5 5 0 010 10h-6" stroke="#fff" strokeWidth="3"/><path d="M22 18c0-4 4-4 4-8M32 18c0-4 4-4 4-8" stroke="#fff" strokeWidth="2.5" strokeLinecap="round"/></svg>
      case 'rice':
        return <svg width="84" height="84" viewBox="0 0 64 64" fill="none"><ellipse cx="32" cy="42" rx="22" ry="12" fill="#fff"/><path d="M12 42c4-14 36-14 40 0z" fill="#fff" opacity=".85"/><circle cx="24" cy="36" r="2" fill={c}/><circle cx="34" cy="33" r="2" fill={c}/><circle cx="42" cy="38" r="2" fill={c}/></svg>
      case 'fish':
        return <svg width="84" height="84" viewBox="0 0 64 64" fill="none"><ellipse cx="28" cy="32" rx="18" ry="11" fill="#fff"/><path d="M44 32l14-10v20z" fill="#fff"/><circle cx="20" cy="29" r="2.4" fill={c}/></svg>
      case 'jar':
        return <svg width="84" height="84" viewBox="0 0 64 64" fill="none"><rect x="16" y="22" width="32" height="32" rx="7" fill="#fff"/><rect x="14" y="14" width="36" height="10" rx="3" fill="#fff" opacity=".9"/><rect x="22" y="32" width="20" height="12" rx="3" fill={c} opacity=".7"/></svg>
      case 'leaf':
        return <svg width="84" height="84" viewBox="0 0 64 64" fill="none"><path d="M12 50C12 24 28 12 54 12c0 26-12 42-38 42z" fill="#fff"/><path d="M14 50L42 22" stroke={c} strokeWidth="2.5"/></svg>
      case 'noodle':
        return <svg width="84" height="84" viewBox="0 0 64 64" fill="none"><path d="M10 32h44a22 18 0 01-44 0z" fill="#fff"/><path d="M18 28c4-8 8 8 12 0s8 8 12 0" stroke="#fff" strokeWidth="3" strokeLinecap="round"/></svg>
      case 'hat':
        return <svg width="84" height="84" viewBox="0 0 64 64" fill="none"><path d="M32 10L6 44h52z" fill="#fff"/><path d="M14 44c10 6 26 6 36 0" stroke={c} strokeWidth="3"/></svg>
      case 'oil':
        return <svg width="84" height="84" viewBox="0 0 64 64" fill="none"><rect x="22" y="26" width="20" height="28" rx="5" fill="#fff"/><rect x="27" y="14" width="10" height="12" rx="2" fill="#fff"/><circle cx="32" cy="40" r="5" fill={c}/></svg>
      default:
        return <svg width="84" height="84" viewBox="0 0 64 64" fill="none"><rect x="16" y="22" width="32" height="32" rx="7" fill="#fff"/><rect x="14" y="14" width="36" height="10" rx="3" fill="#fff" opacity=".9"/><rect x="22" y="32" width="20" height="12" rx="3" fill={c} opacity=".7"/></svg>
    }
  }

  const renderStars = (n: number) => {
    return Array.from({ length: 5 }).map((_, i) => (
      <svg key={i} width="15" height="15" viewBox="0 0 24 24">
        <path
          d="M12 2l3 7 7.5.6-5.7 5 1.8 7.4L12 18l-6.6 4 1.8-7.4-5.7-5L9 9z"
          fill={i < n ? '#f5b301' : '#d5dde2'}
        />
      </svg>
    ))
  }

  return (
    <section className="glass view" data-v="prod" id="v-prod">
      <div className="vhead">
        <div className="vico" style={{ background: '#d9f1e5', color: '#2f6b52' }}>
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <rect x="5" y="3" width="14" height="18" rx="2" />
            <path d="M9 12l2 2 4-4" />
          </svg>
        </div>
        <div className="vt">
          <h2>Danh mục Sản phẩm Đạt chuẩn OCOP</h2>
          <p>Tra cứu sản phẩm OCOP đã được UBND cấp tỉnh công nhận (Hải Phòng, Thừa Thiên Huế)</p>
        </div>
      </div>

      <div className="crow">
        <label className="fld">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <circle cx="11" cy="11" r="7" />
            <path d="M16 16l5 5" />
          </svg>
          <input
            id="pQ"
            type="text"
            placeholder="Tìm tên sản phẩm, cơ sở sản xuất..."
            autoComplete="off"
            value={prodQ}
            onChange={(e) => {
              setProdQ(e.target.value)
              setProdPage(1)
            }}
          />
        </label>
        <select
          className="sel"
          id="pLoc"
          style={{ width: 190 }}
          value={prodLoc}
          onChange={(e) => {
            setProdLoc(e.target.value)
            setProdPage(1)
          }}
        >
          <option value="">Tất cả địa phương</option>
          <option value="Hải Phòng">Hải Phòng</option>
          <option value="Thừa Thiên Huế">Thừa Thiên Huế</option>
        </select>
        <select
          className="sel"
          id="pStar"
          style={{ width: 190 }}
          value={prodStar}
          onChange={(e) => {
            setProdStar(e.target.value)
            setProdPage(1)
          }}
        >
          <option value="">Tất cả xếp hạng sao</option>
          <option value="3">3 sao</option>
          <option value="4">4 sao</option>
          <option value="5">5 sao</option>
        </select>
        <button type="button" className="btn-b" id="pExp" onClick={exportProdCsv}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M12 4v11M7 10l5 5 5-5M5 20h14" />
          </svg>
          Xuất danh sách
        </button>
      </div>

      <div className="cinfo">
        <span className="chip green" id="pTotal">Tổng {filteredProds.length} sản phẩm</span>
        <span id="pShow">Hiển thị {pagedProds.length} / {filteredProds.length} kết quả</span>
        <span style={{ marginLeft: 'auto' }}>Hiển thị</span>
        <select
          className="sel"
          id="pPer"
          value={prodPer}
          onChange={(e) => {
            setProdPer(+e.target.value)
            setProdPage(1)
          }}
        >
          <option value={8}>8</option>
          <option value={20}>20</option>
          <option value={40}>40</option>
        </select>
        <span>/ trang</span>

        <div className="seg2" style={{ marginLeft: 12 }}>
          <button
            type="button"
            id="pGridB"
            className={!prodIsTable ? 'on' : ''}
            onClick={() => setProdIsTable(false)}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="4" y="4" width="6" height="6" rx="1" />
              <rect x="14" y="4" width="6" height="6" rx="1" />
              <rect x="4" y="14" width="6" height="6" rx="1" />
              <rect x="14" y="14" width="6" height="6" rx="1" />
            </svg>
            Dạng lưới
          </button>
          <button
            type="button"
            id="pTblB"
            className={prodIsTable ? 'on' : ''}
            onClick={() => setProdIsTable(true)}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M4 6h16M4 12h16M4 18h16" />
            </svg>
            Dạng bảng
          </button>
        </div>
      </div>

      <div className={`pgrid ${prodIsTable ? 'table' : ''}`} id="pGrid">
        {pagedProds.length === 0 ? (
          <div className="empty">Không có sản phẩm phù hợp bộ lọc.</div>
        ) : prodIsTable ? (
          <table>
            <thead>
              <tr>
                <th>Sản phẩm</th>
                <th>Chủ thể</th>
                <th>Địa phương</th>
                <th>Xếp hạng</th>
                <th>Quyết định</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {pagedProds.map((p) => (
                <tr key={p.id}>
                  <td><b>{p.name}</b></td>
                  <td>{p.owner}</td>
                  <td>{p.loc}</td>
                  <td>
                    <span className="stars">
                      {renderStars(p.stars)}
                      <em>{p.stars} sao</em>
                    </span>
                  </td>
                  <td>{p.code}</td>
                  <td>
                    <button
                      type="button"
                      className="xem"
                      onClick={() => {
                        registerSource('P' + p.id, p.code, p.name + ' (' + p.owner + ')', 8)
                        setActiveView('chat')
                        openSrc('P' + p.id, 1)
                      }}
                    >
                      Xem quyết định
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          pagedProds.map((p) => {
            const k = KINDS_MAP[p.kind] || ['#f2b18a', '#c4623b']
            return (
              <article key={p.id} className="pcard">
                <div className="pimg" style={{ background: `linear-gradient(150deg,${k[0]},${k[1]})` }}>
                  {p.kind === 'honey' ? (
                    <img src={IMAGES.prodHoney} alt="" />
                  ) : p.kind === 'coffee' ? (
                    <img src={IMAGES.prodCoffee} alt="" />
                  ) : p.kind === 'gift' ? (
                    <img src={IMAGES.prodGift} alt="" />
                  ) : (
                    renderGlyph(p.kind)
                  )}
                </div>
                <div className="pbody">
                  <b>{p.name}</b>
                  <span className="own">{p.owner}</span>
                  <div className="stars">
                    {renderStars(p.stars)}
                    <em>{p.stars} sao</em>
                    <small>{p.code}</small>
                  </div>
                  <button
                    type="button"
                    className="pbtn"
                    onClick={() => {
                      registerSource('P' + p.id, p.code, p.name + ' (' + p.owner + ')', 8)
                      setActiveView('chat')
                      openSrc('P' + p.id, 1)
                    }}
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <rect x="5" y="3" width="14" height="18" rx="2" />
                      <path d="M9 8h6M9 12h6" />
                    </svg>
                    Xem quyết định
                  </button>
                </div>
              </article>
            )
          })
        )}
      </div>

      <div className="pager" id="pPager">
        <button type="button" disabled={prodPage <= 1} onClick={() => setProdPage((p) => Math.max(1, p - 1))}>‹</button>
        {Array.from({ length: prodPages }).map((_, i) => (
          <button
            key={i + 1}
            type="button"
            className={prodPage === i + 1 ? 'on' : ''}
            onClick={() => setProdPage(i + 1)}
          >
            {i + 1}
          </button>
        ))}
        <button type="button" disabled={prodPage >= prodPages} onClick={() => setProdPage((p) => Math.min(prodPages, p + 1))}>›</button>
      </div>
      <div className="demo">Dữ liệu và ảnh sản phẩm OCOP chính thống</div>
    </section>
  )
}
