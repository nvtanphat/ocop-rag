// Request fields mirror AskRequest; flexible dictionaries mirror AgentResponse.
export type JsonObject = Record<string, unknown>
export type Box = [number, number, number, number]
export interface SourceSpan {
  pdf_page: number
  printed_page?: string | null
  bbox?: Box | null
  table_bbox?: Box | null
  block_id?: string | null
  table_id?: string | null
  cell_id?: string | null
  source_sha256?: string | null
}
export interface Citation extends SourceSpan {
  source_id: string
  evidence_unit_id: string | null
  source_spans?: SourceSpan[]
  context_source_spans?: SourceSpan[]
  review_status?: string
}
export interface AskRequest {
  query: string
  session_id?: string | null
  retrieval_mode?: 'sparse' | 'dense' | 'hybrid'
  use_llm?: boolean
}
export interface Route {
  intent: string
  strategy: string
  retrieval_path: string
  slots: JsonObject
  required_tools: string[]
  secondary_tools: string[]
  secondary_intents: string[]
  capabilities: string[]
  needs_clarification: boolean
  missing_slots: string[]
  reason_codes: string[]
  confidence: number | null
  dialogue: { acts: string[]; action: string; method: string }
}
export interface AskResult {
  answer: string
  intent: string
  status: string
  citations: Citation[]
  tools_used: string[]
  tools_skipped: string[]
  tool_trace: JsonObject[]
  evidence_coverage: JsonObject
  evidence_grade: JsonObject
  claim_verification: JsonObject
  generation_diagnostics: JsonObject
  evidence_fusion: JsonObject
  workflow_engine: string
  corpus_version: string | null
  standalone_query: string | null
  route: Route
}
export interface Source {
  source_id: string
  document_number: string | null
  source_kind: string | null
  jurisdiction: string | null
  source_verification: string | null
  page_count: number
  ocr_pages: number
  filename: string
}
export interface RetrievalProfile {
  profile: 'sparse' | 'hybrid'
  ready: boolean
  missing: string[]
}
export interface Health {
  status: string
  retrieval_profile?: RetrievalProfile
  answer_llm?: boolean
  pipeline: JsonObject
  sources_registered: number
  pages: number
  index_status: string
  dense_ready: boolean
  graph_status: string
  corpus_version: string | null
}
export interface ReferenceItem {
  id: string
  label: string
  group?: string | null
  points?: number | null
  citations: Array<Citation & { evidence_unit_id: string; source_sha256: string; bbox: Box }>
}
export interface ReferenceResponse {
  corpus_version: string | null
  status: 'verified' | 'no_verified_data'
  items: ReferenceItem[]
}

export interface SubgraphCitation {
  source_id: string
  pdf_page: number
  bbox: Box | null
  evidence_unit_id: string | null
  source_sha256: string | null
}
export interface SubgraphNode {
  node_id: string
  node_type: string
  label: string
  check: string
  review_status: string
  source_id: string | null
  evidence_unit_ids: string[]
  citations: SubgraphCitation[]
}
export interface SubgraphEdge {
  edge_id: string
  relation_type: string
  source: string
  target: string
  check: string
  review_status: string
}
export interface Subgraph {
  status: 'ok' | 'no_seed' | 'no_graph'
  graph_version: string | null
  seed_ids: string[]
  nodes: SubgraphNode[]
  edges: SubgraphEdge[]
  truncated: boolean
}
export type SubgraphSeed = { evidenceUnitId: string } | { nodeId: string }

export class ApiError extends Error {
  constructor(message: string, public readonly status?: number) { super(message) }
}

const BASE = '/api/ocop'
// A reranked answer from a live model can take well over a minute; the deployment, not the page, bounds the work.
export const ASK_TIMEOUT_MS = 180000

/** The deployment owns the retrieval profile: use hybrid exactly when the backend reports it ready, else sparse. */
export function retrievalModeFor(health: Health | null | undefined): 'sparse' | 'hybrid' {
  const profile = health?.retrieval_profile
  return profile?.profile === 'hybrid' && profile.ready ? 'hybrid' : 'sparse'
}
export async function request<T>(path: string, init?: RequestInit, timeoutMs = 90000): Promise<T> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const response = await fetch(`${BASE}${path}`, { ...init, signal: controller.signal })
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      const detail = body?.detail
      const message = typeof detail === 'string' ? detail : detail?.message
      throw new ApiError(message || `Dịch vụ OCOP trả lỗi HTTP ${response.status}.`, response.status)
    }
    return await response.json() as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (controller.signal.aborted) throw new ApiError('Yêu cầu OCOP quá thời gian chờ. Vui lòng thử lại.')
    throw new ApiError('Không kết nối được dịch vụ OCOP. Kiểm tra backend rồi thử lại.')
  } finally { clearTimeout(timeout) }
}

export const api = {
  health: () => request<Health>('/health'),
  sources: () => request<Source[]>('/sources'),
  criteria: () => request<ReferenceResponse>('/criteria'),
  products: () => request<ReferenceResponse>('/products'),
  ask: (body: AskRequest) => request<AskResult>('/query', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }, ASK_TIMEOUT_MS),
  subgraph: (seed: SubgraphSeed, hops = 1, limit = 50) => {
    const params = new URLSearchParams({ hops: String(hops), limit: String(limit) })
    if ('evidenceUnitId' in seed) params.set('evidence_unit_id', seed.evidenceUnitId)
    else params.set('node_id', seed.nodeId)
    return request<Subgraph>(`/graph/subgraph?${params}`)
  },
  pdf: (sourceId: string, page = 1) => `${BASE}/sources/${encodeURIComponent(sourceId)}/pdf#page=${page}`,
  evidence: (citation: Citation, page = citation.pdf_page, highlight = true) => {
    const params = new URLSearchParams()
    if (citation.source_sha256) params.set('sha', citation.source_sha256)
    const spans = citation.source_spans?.length ? citation.source_spans : [citation]
    if (highlight) {
      for (const span of spans.filter(s => s.pdf_page === page)) {
        const box = span.bbox || span.table_bbox
        if (box) params.append('box', box.join(','))
      }
      for (const span of citation.context_source_spans || []) {
        if (span.pdf_page === page && span.bbox) params.append('context', span.bbox.join(','))
      }
    }
    return `${BASE}/sources/${encodeURIComponent(citation.source_id)}/pages/${page}/evidence.png?${params}`
  },
}
