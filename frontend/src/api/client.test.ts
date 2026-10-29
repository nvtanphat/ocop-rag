import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, request, retrievalModeFor, type Citation, type Health } from './client'

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

describe('OCOP API client', () => {
  it('uses the public request fields and the OCOP namespace', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ answer: 'answer' })))
    vi.stubGlobal('fetch', fetch)
    const body = { query: 'question', session_id: 'session', retrieval_mode: 'sparse' as const, use_llm: false }
    expect(await api.ask(body)).toEqual({ answer: 'answer' })
    expect(fetch.mock.calls[0][0]).toBe('/api/ocop/query')
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual(body)
  })

  it.each([400, 404, 422, 500, 503])('reports HTTP %s without fake fallback data', async status => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: { message: 'Unavailable' } }), { status })))
    await expect(api.sources()).rejects.toMatchObject({ message: 'Unavailable', status })
  })

  it('asks for hybrid retrieval only when the backend reports that profile ready', () => {
    const health = (profile: 'sparse' | 'hybrid', ready: boolean) =>
      ({ retrieval_profile: { profile, ready, missing: ready ? [] : ['qdrant_unreachable'] } }) as Health
    expect(retrievalModeFor(health('hybrid', true))).toBe('hybrid')
    expect(retrievalModeFor(health('hybrid', false))).toBe('sparse')
    expect(retrievalModeFor(health('sparse', true))).toBe('sparse')
    expect(retrievalModeFor(null)).toBe('sparse')
    expect(retrievalModeFor({} as Health)).toBe('sparse')
  })

  it('gives a reranked answer more time than an ordinary request', async () => {
    vi.useFakeTimers()
    const fetch = vi.fn((_url, { signal }: RequestInit) => new Promise((resolve, reject) => {
      signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
      setTimeout(() => resolve(new Response(JSON.stringify({ answer: 'late but valid' }))), 120000)
    }))
    vi.stubGlobal('fetch', fetch)
    const result = api.ask({ query: 'q', retrieval_mode: 'hybrid', use_llm: true })
    await vi.advanceTimersByTimeAsync(120000)
    await expect(result).resolves.toEqual({ answer: 'late but valid' })
  })

  it('reports an unreachable backend', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('connection refused')))
    await expect(api.health()).rejects.toThrow('Không kết nối được dịch vụ OCOP')
  })

  it('aborts timed out requests', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn((_url, { signal }: RequestInit) => new Promise((_resolve, reject) => {
      signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    })))
    const result = request('/health', undefined, 25)
    const failure = expect(result).rejects.toThrow('quá thời gian chờ')
    await vi.advanceTimersByTimeAsync(25)
    await failure
  })

  it('preserves source identity, page, SHA and all evidence regions in URLs', () => {
    const citation: Citation = {
      source_id: 'source/a', evidence_unit_id: 'evidence', pdf_page: 7,
      bbox: [10, 20, 30, 40], source_sha256: 'a'.repeat(64),
      source_spans: [{ pdf_page: 7, bbox: [10, 20, 30, 40] }, { pdf_page: 7, bbox: [50, 60, 70, 80] }, { pdf_page: 8, bbox: [1, 2, 3, 4] }],
    }
    expect(api.pdf(citation.source_id, 7)).toBe('/api/ocop/sources/source%2Fa/pdf#page=7')
    const url = new URL(api.evidence(citation), 'http://localhost')
    expect(url.pathname).toBe('/api/ocop/sources/source%2Fa/pages/7/evidence.png')
    expect(url.searchParams.get('sha')).toBe(citation.source_sha256)
    expect(url.searchParams.getAll('box')).toEqual(['10,20,30,40', '50,60,70,80'])
    expect(citation.evidence_unit_id).toBe('evidence')
  })

  it('retains a useful status when the server returns non-JSON errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('bad gateway', { status: 502 })))
    await expect(api.products()).rejects.toBeInstanceOf(ApiError)
  })
})
