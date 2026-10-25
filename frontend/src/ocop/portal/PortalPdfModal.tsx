import React from 'react'
import type { DocInfo, SrcItem } from './types'
import { PAGE18_HTML } from './utils'

interface PortalPdfModalProps {
  pdfOpen: boolean
  setPdfOpen: (open: boolean) => void
  pdfSrcId: string
  setPdfSrcId: (id: string) => void
  pdfPage: number
  setPdfPage: React.Dispatch<React.SetStateAction<number>>
  pdfZoom: number
  setPdfZoom: React.Dispatch<React.SetStateAction<number>>
  pdfHl: boolean
  setPdfHl: React.Dispatch<React.SetStateAction<boolean>>
  docsMap: Record<string, DocInfo>
  srcMap: Record<string, SrcItem>
  copyText: (text: string) => void
  openSrc: (sid: string, page?: number) => void
  toast: (msg: string) => void
}

export const PortalPdfModal: React.FC<PortalPdfModalProps> = ({
  pdfOpen,
  setPdfOpen,
  pdfSrcId,
  pdfPage,
  setPdfPage,
  pdfZoom,
  setPdfZoom,
  pdfHl,
  setPdfHl,
  docsMap,
  srcMap,
  copyText,
  openSrc,
  toast,
}) => {
  if (!pdfOpen) return null

  const sItem = srcMap[pdfSrcId]
  const docData = docsMap[sItem?.doc || '148']
  const title = docData?.title || sItem?.name || 'Tài liệu OCOP'
  const sub = docData?.sub || sItem?.sub || 'Văn bản quy định'
  const total = sItem?.total || 42

  return (
    <section className="cv glass pdf" id="pdf">
      <div className="pdf-head">
        <div className="pdfico">PDF</div>
        <div className="tt">
          <b id="docTitle">{title}</b>
          <span id="docSub">{sub}</span>
        </div>
        <div className="ctl">
          <span id="pgInfo">Trang {pdfPage} / {total}</span>
          <div className="zm">
            <button type="button" id="zOut" onClick={() => setPdfZoom((z) => Math.max(0.6, z - 0.1))}>−</button>
            <span id="zVal">{Math.round(pdfZoom * 100)}%</span>
            <button type="button" id="zIn" onClick={() => setPdfZoom((z) => Math.min(2.0, z + 0.1))}>+</button>
          </div>
          <button
            type="button"
            className="ib"
            id="btnFind"
            title="Tới vị trí trích dẫn"
            onClick={() => {
              setPdfPage(sItem?.page || 18)
              setPdfHl(true)
              toast('Đã chuyển tới vị trí trích dẫn')
            }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <circle cx="11" cy="11" r="7" />
              <path d="M16 16l5 5" />
            </svg>
          </button>
          <button
            type="button"
            className="ib"
            id="btnFs"
            title="Toàn màn hình"
            onClick={() => {
              try {
                if (!document.fullscreenElement) {
                  document.documentElement.requestFullscreen()
                } else {
                  document.exitFullscreen()
                }
              } catch {
                toast('Không hỗ trợ toàn màn hình')
              }
            }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
            </svg>
          </button>
          <button type="button" className="ib" id="btnClosePdf" title="Đóng PDF (Esc)" onClick={() => setPdfOpen(false)}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>
      </div>

      <div className="viewer">
        <div className="thumbs" id="thumbs">
          {Array.from({ length: 5 }).map((_, i) => {
            const first = Math.max(1, Math.min(pdfPage - 2, total - 4))
            const pNum = first + i
            if (pNum > total) return null
            return (
              <button
                key={pNum}
                type="button"
                className={`th ${pNum === pdfPage ? 'on' : ''} ${pNum === 18 && pdfSrcId === 'S1' ? 'p18' : ''}`}
                onClick={() => setPdfPage(pNum)}
              >
                <em>{pNum}</em>
              </button>
            )
          })}
        </div>

        <div className="scroller" id="scroller">
          <div
            className={`page ${pdfHl ? '' : 'nohl'}`}
            id="page"
            style={{ zoom: pdfZoom / 1.2 }}
          >
            {pdfSrcId === 'S1' && pdfPage === 18 ? (
              <div dangerouslySetInnerHTML={{ __html: PAGE18_HTML }} />
            ) : (
              <div>
                <div className="c">
                  <h5>{title}</h5>
                  <p className="it">Trang {pdfPage} (Bản xem trước minh họa)</p>
                </div>
                <div className="skel">
                  {Array.from({ length: 22 }).map((_, idx) => (
                    <i
                      key={idx}
                      style={{ width: `${70 + ((idx * 37) % 30)}%` }}
                      className={pdfHl && idx >= 7 && idx <= 9 ? 'h' : ''}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="tools">
          <button type="button" className={pdfHl ? 'on' : ''} id="tHl" title="Hiện/ẩn vị trí trích dẫn" onClick={() => setPdfHl((h) => !h)}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="4" y="4" width="16" height="16" rx="3" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          </button>
          <button
            type="button"
            id="tCopy"
            title="Sao chép trích dẫn"
            onClick={() => {
              copyText(`${sItem?.name}, trang ${pdfPage}, BBox ${sItem?.bbox}`)
            }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="8" y="8" width="12" height="12" rx="2" />
              <path d="M16 8V6a2 2 0 00-2-2H6a2 2 0 00-2 2v8a2 2 0 002 2h2" />
            </svg>
          </button>
          <button
            type="button"
            id="tNext"
            title="Nguồn tiếp theo"
            onClick={() => {
              const keys = Object.keys(srcMap)
              const nextIdx = (keys.indexOf(pdfSrcId) + 1) % keys.length
              openSrc(keys[nextIdx])
            }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M5 8h10M5 16h14M15 4l4 4-4 4" />
            </svg>
          </button>
          <button type="button" id="tFit" title="Về cỡ 120%" onClick={() => setPdfZoom(1.2)}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="5" y="5" width="14" height="14" rx="3" />
              <circle cx="12" cy="12" r="2.5" />
            </svg>
          </button>
        </div>
      </div>

      <div className="pdf-foot">
        <button type="button" className={`pill ${pdfHl ? '' : 'off'}`} id="pHl" onClick={() => setPdfHl((h) => !h)}>
          <svg width="16" height="16" viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="10" fill="#e0343c" />
            <circle cx="12" cy="12" r="3.5" fill="none" stroke="#fff" strokeWidth="2" />
          </svg>
          Vị trí trích dẫn
        </button>
        <span className="pill g">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="5" y="3" width="14" height="18" rx="2" />
          </svg>
          <span id="pPage">Trang {pdfPage}</span>
        </span>
        <span className="bb" id="bbox">
          BBox: {pdfPage === sItem?.page ? sItem?.bbox : '—'}
        </span>
        <button
          type="button"
          className="full"
          id="btnFull"
          onClick={() => {
            try {
              document.documentElement.requestFullscreen()
            } catch {
              toast('Không hỗ trợ toàn màn hình')
            }
          }}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M14 4h6v6M20 4l-8 8M10 20H4v-6" />
          </svg>
          Xem toàn màn hình
        </button>
      </div>
    </section>
  )
}
