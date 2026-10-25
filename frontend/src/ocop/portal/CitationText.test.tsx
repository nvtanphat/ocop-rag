import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { CitationText } from './CitationText'
import type { Citation } from '../api/client'

const citation: Citation = { source_id: 'SOURCE', pdf_page: 3, bbox: [10, 20, 30, 40], evidence_unit_id: 'unit', source_sha256: 'a'.repeat(64) }
describe('citation rendering', () => {
  it('renders existing markers as accessible buttons', () => {
    const html = renderToStaticMarkup(<CitationText text="Grounded [S1]" citations={[citation]} onOpen={() => {}} />)
    expect(html).toContain('<button class="citation">[S1]</button>')
    expect(html).not.toContain('href=')
  })
  it('does not invent evidence for out-of-range markers', () => {
    const html = renderToStaticMarkup(<CitationText text="Unknown [S9]" citations={[citation]} onOpen={() => {}} />)
    expect(html).toContain('[S9]')
    expect(html).not.toContain('<button')
  })
  it('does not execute HTML received from the model', () => {
    const html = renderToStaticMarkup(<CitationText text={'<img src=x onerror="alert(1)"> [S1]'} citations={[citation]} onOpen={() => {}} />)
    expect(html).not.toContain('<img')
    expect(html).toContain('&lt;img')
  })
})
