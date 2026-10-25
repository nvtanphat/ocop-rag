import React, { useEffect, useRef, useState } from 'react'
import { d3 } from '../d3-bundle'
import type { BotAnswer, SrcItem } from './types'

interface PortalGraphModalProps {
  graphOpen: boolean
  setGraphOpen: (open: boolean) => void
  graphTab: 'ev' | 'doc'
  setGraphTab: (tab: 'ev' | 'doc') => void
  activeAns: BotAnswer | null
  srcMap: Record<string, SrcItem>
}

export const PortalGraphModal: React.FC<PortalGraphModalProps> = ({
  graphOpen,
  setGraphOpen,
  graphTab,
  setGraphTab,
  activeAns,
  srcMap,
}) => {
  const svgRef = useRef<SVGSVGElement | null>(null)
  const [selectedNodeText, setSelectedNodeText] = useState('Chọn một nút để xem chi tiết.')

  useEffect(() => {
    if (!graphOpen || !svgRef.current) return

    const svgEl = svgRef.current
    const sel = d3.select(svgEl)
    sel.selectAll('*').remove()

    const defs = sel.append('defs')
    defs
      .append('marker')
      .attr('id', 'arr')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 10)
      .attr('refY', 0)
      .attr('markerWidth', 7)
      .attr('markerHeight', 7)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-4L10,0L0,4')
      .attr('fill', '#8d9a94')

    const g = sel.append('g')
    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.5, 3])
      .on('zoom', (e: { transform: unknown }) => {
        g.attr('transform', e.transform as string)
      })
    sel.call(zoom).on('dblclick.zoom', null)

    const W = 460
    const H = 420

    if (graphTab === 'ev') {
      const a = activeAns
      if (!a) {
        g.append('text')
          .attr('x', W / 2)
          .attr('y', H / 2)
          .attr('text-anchor', 'middle')
          .attr('fill', '#8d9a94')
          .text('Chưa có câu trả lời để hiển thị')
        return
      }

      const claims = a.claims || [
        ['Quy định thẩm quyền UBND cấp huyện', [['S1', 0.93], ['S3', 0.81]]],
        ['Thẩm quyền đánh giá OCOP 4 sao thuộc tỉnh', [['S1', 0.91], ['S4', 0.78]]],
        ['Sản phẩm OCOP 5 sao do Trung ương đánh giá', [['S1', 0.89], ['S3', 0.74]]],
      ]

      type GNode = { id: string; t: string; kind: string; x?: number; y?: number; fx?: number | null; fy?: number | null; sub?: string }
      type GLink = { source: string | GNode; target: string | GNode; w?: number }

      const nodes: GNode[] = [{ id: 'q', t: 'Câu hỏi của bạn', kind: 'q', fx: W / 2, fy: 48 }]
      const links: GLink[] = []

      claims.forEach((c, i) => {
        const cid = 'c' + i
        const cx = (W / (claims.length + 1)) * (i + 1)
        nodes.push({ id: cid, t: c[0], kind: 'c', fx: cx, fy: 175 })
        links.push({ source: 'q', target: cid })

        c[1].forEach((s) => {
          const sid = s[0]
          if (!nodes.some((n) => n.id === sid)) {
            const srcItem = srcMap[sid]
            nodes.push({ id: sid, t: srcItem?.name || sid, kind: 's', sub: srcItem?.sub || 'Trích đoạn' })
          }
          links.push({ source: cid, target: sid, w: s[1] })
        })
      })

      const sim = d3
        .forceSimulation(nodes as d3.SimulationNodeDatum[])
        .force('link', d3.forceLink(links).id((d: any) => d.id).distance(80))
        .force('charge', d3.forceManyBody().strength(-200))
        .force('center', d3.forceCenter(W / 2, 280))

      const link = g
        .append('g')
        .selectAll('line')
        .data(links)
        .join('line')
        .attr('stroke', '#8d9a94')
        .attr('stroke-width', 1.8)
        .attr('marker-end', 'url(#arr)')

      const node = g
        .append('g')
        .selectAll('g')
        .data(nodes)
        .join('g')
        .call(
          d3
            .drag<SVGGElement, any>()
            .on('start', (event, d) => {
              if (!event.active) sim.alphaTarget(0.3).restart()
              d.fx = d.x
              d.fy = d.y
            })
            .on('drag', (event, d) => {
              d.fx = event.x
              d.fy = event.y
            })
            .on('end', (event, d) => {
              if (!event.active) sim.alphaTarget(0)
              d.fx = null
              d.fy = null
            })
        )
        .on('click', (_e, d) => {
          setSelectedNodeText(`${d.t} (${d.kind === 'q' ? 'Câu hỏi' : d.kind === 'c' ? 'Ý trả lời' : 'Nguồn căn cứ'})`)
        })

      node
        .append('circle')
        .attr('r', (d) => (d.kind === 'q' ? 18 : d.kind === 'c' ? 14 : 12))
        .attr('fill', (d) => (d.kind === 'q' ? '#2f6b52' : d.kind === 'c' ? '#a8832f' : '#4b6b94'))
        .attr('stroke', '#fff')
        .attr('stroke-width', 2)

      node
        .append('text')
        .attr('dy', 24)
        .attr('text-anchor', 'middle')
        .attr('font-size', '10px')
        .attr('fill', 'var(--ink)')
        .text((d) => (d.t.length > 20 ? d.t.slice(0, 18) + '…' : d.t))

      sim.on('tick', () => {
        link
          .attr('x1', (d: any) => d.source.x)
          .attr('y1', (d: any) => d.source.y)
          .attr('x2', (d: any) => d.target.x)
          .attr('y2', (d: any) => d.target.y)

        node.attr('transform', (d: any) => `translate(${d.x},${d.y})`)
      })
    } else {
      // Document Relationship Graph
      const docs = [
        { id: '148', t: 'QĐ 148/QĐ-TTg', col: '#e8453c' },
        { id: '26', t: 'QĐ 26/BNN', col: '#2a6fdb' },
        { id: 'attp', t: 'Luật ATTP', col: '#13a06a' },
        { id: '15', t: 'NĐ 15/2018', col: '#8a5bd6' },
        { id: '43', t: 'NĐ 43/2017', col: '#8a5bd6' },
        { id: '525', t: 'QĐ 525/HP', col: '#f09a1a' },
      ]
      const dlinks = [
        { source: '148', target: '26' },
        { source: '148', target: 'attp' },
        { source: 'attp', target: '15' },
        { source: '148', target: '43' },
        { source: '148', target: '525' },
      ]

      const sim = d3
        .forceSimulation(docs as d3.SimulationNodeDatum[])
        .force('link', d3.forceLink(dlinks).id((d: any) => d.id).distance(90))
        .force('charge', d3.forceManyBody().strength(-300))
        .force('center', d3.forceCenter(W / 2, H / 2))

      const link = g
        .append('g')
        .selectAll('line')
        .data(dlinks)
        .join('line')
        .attr('stroke', '#8d9a94')
        .attr('stroke-width', 2)

      const node = g
        .append('g')
        .selectAll('g')
        .data(docs)
        .join('g')
        .on('click', (_e, d) => {
          setSelectedNodeText(`${d.t}: Văn bản căn cứ pháp lý trong hệ thống OCOP.`)
        })

      node
        .append('circle')
        .attr('r', 16)
        .attr('fill', (d) => d.col)
        .attr('stroke', '#fff')
        .attr('stroke-width', 2)

      node
        .append('text')
        .attr('dy', 26)
        .attr('text-anchor', 'middle')
        .attr('font-size', '10px')
        .attr('fill', 'var(--ink)')
        .text((d) => d.t)

      sim.on('tick', () => {
        link
          .attr('x1', (d: any) => d.source.x)
          .attr('y1', (d: any) => d.source.y)
          .attr('x2', (d: any) => d.target.x)
          .attr('y2', (d: any) => d.target.y)

        node.attr('transform', (d: any) => `translate(${d.x},${d.y})`)
      })
    }
  }, [graphOpen, graphTab, activeAns, srcMap])

  if (!graphOpen) return null

  return (
    <section className="cv glass" id="gpanel">
      <div className="gh">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
          <circle cx="5" cy="6" r="2.2" />
          <circle cx="19" cy="6" r="2.2" />
          <circle cx="12" cy="18" r="2.2" />
          <path d="M7 7l4 9M17 7l-4 9M7.2 6h9.6" />
        </svg>
        <b>{graphTab === 'ev' ? 'Đồ thị dẫn chứng' : 'Quan hệ giữa các văn bản'}</b>
        <button type="button" className="gx" id="gClose" aria-label="Đóng" onClick={() => setGraphOpen(false)}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>
      <div className="gtabs">
        <button type="button" className={graphTab === 'ev' ? 'on' : ''} onClick={() => setGraphTab('ev')}>
          Dẫn chứng câu trả lời
        </button>
        <button type="button" className={graphTab === 'doc' ? 'on' : ''} onClick={() => setGraphTab('doc')}>
          Quan hệ văn bản
        </button>
      </div>
      <div id="glegend" style={{ display: 'flex' }}>
        {graphTab === 'ev' ? (
          <>
            <span><i style={{ background: '#2f6b52' }} />Câu hỏi</span>
            <span><i style={{ background: '#a8832f' }} />Ý trả lời</span>
            <span><i style={{ background: '#4b6b94' }} />Đoạn trích nguồn</span>
          </>
        ) : (
          <>
            <span><i style={{ background: '#e8453c' }} />Quy chuẩn</span>
            <span><i style={{ background: '#f09a1a' }} />Địa phương</span>
            <span><i style={{ background: '#2a6fdb' }} />Bộ ngành</span>
          </>
        )}
      </div>
      <svg id="gsvg" ref={svgRef} viewBox="0 0 460 420" preserveAspectRatio="xMidYMid meet" />
      <div id="gdet">{selectedNodeText}</div>
    </section>
  )
}
