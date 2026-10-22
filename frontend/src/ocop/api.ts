export type Section = 'overview' | 'chat' | 'criteria' | 'forms' | 'recognitions' | 'documents' | 'graph' | 'system' | 'review'

export interface Source {
  source_id: string
  filename: string
  document_number: string | null
  source_kind: string
  jurisdiction: string | null
  source_verification: string
  page_count: number
  ocr_pages: number
}
export interface Overview {
  sources: number
  pages: { pages?: number; ocr_executed?: number; needs_review?: number; tables_detected?: number }
  knowledge: { units?: number; criterion_candidates?: number; recognition_candidates?: number; form_candidates?: number }
  index: { corpus_version?: string; status?: string; counts?: { chunks?: number }; dense?: { enabled?: boolean } }
  graph: { status?: string; counts?: { nodes?: number; edges?: number }; checks?: { nodes: CheckCounts; edges: CheckCounts }; neo4j?: { enabled?: boolean } }
  verification: string
}
export interface Citation {
  source_id: string
  pdf_page: number
  evidence_unit_id: string | null
  bbox?: [number, number, number, number] | null
  table_bbox?: [number, number, number, number] | null
  source_sha256?: string | null
  context_source_spans?: Array<{ pdf_page: number; bbox?: [number, number, number, number] | null }>
  source_spans?: Array<{
    pdf_page: number
    bbox?: [number, number, number, number] | null
    table_bbox?: [number, number, number, number] | null
    block_id?: string
    table_id?: string
    cell_id?: string
    source_sha256?: string
  }>
  review_status?: string
}
export interface AskResult {
  answer: string
  intent: string
  status: string
  citations: Citation[]
  tools_used: string[]
  tools_skipped?: string[]
  workflow_engine: string
  corpus_version?: string | null
  route?: { strategy?: string; slots?: Record<string, unknown>; reason_codes?: string[] }
  tool_trace?: Array<Record<string, unknown>>
  evidence_coverage?: { status?: string; missing_tools?: string[] }
  evidence_grade?: { uncovered_parts?: string[]; missing_tools?: string[] }
  claim_verification?: { supported?: number; unsupported?: number; claims?: Array<{ claim: string; tier?: string }> }
  generation_diagnostics?: { missing_from_source?: string[]; rejected?: Array<{ claim: string; reasons: string[] }> }
}
export interface Criterion extends GraphNode { linked_labels: string[] }
export interface Recognition extends GraphNode { linked_labels: string[] }
export interface FormCandidate extends GraphNode { linked_labels: string[] }
export interface GraphNode {
  node_id: string
  check: "passed" | "human_verified"
  origin: string
  node_type: string
  label: string
  source_id?: string
  review_status?: string
  evidence_unit_ids?: string[]
  validation?: { status: string; legal_verified: boolean }
  citations?: Array<{ pdf_page: number; source_sha256?: string }>
}
export interface GraphEdge {
  source_entity_id?: string
  target_entity_id?: string
  source_id?: string
  target_id?: string
  relation_type?: string
  review_status?: string
}
export interface Page<T> { items: T[]; total: number; kind: string }
export interface GraphData { nodes: GraphNode[]; edges: GraphEdge[]; total_matches: number; kind: string }
export interface Health { status: string; sources_registered: number; pages: number; index_status: string; dense_ready: boolean; graph_status: string; corpus_version?: string }

const BASE = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '') + '/ocop'
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init)
  if (!response.ok) {
    const data = await response.json().catch(() => ({})) as { detail?: string | { message?: string; code?: string } }
    const detail = typeof data.detail === 'string' ? data.detail : data.detail?.message
    throw new Error(detail || `Yêu cầu thất bại (HTTP ${response.status})`)
  }
  return response.json() as Promise<T>
}
export const api = {
  reviewQueue: (priority: string, offset = 0, includeDecided = false) => request<{items: ReviewItem[]; total: number}>(`/review/queue?priority=${priority}&offset=${offset}&limit=30&include_decided=${includeDecided}`),
  reviewItem: (id: string) => request<ReviewItem>(`/review/items/${encodeURIComponent(id)}`),
  reviewStats: () => request<{total: number; by_priority: Record<string, number>; by_state: Record<string, number>}>('/review/stats'),
  reviewDecide: (body: object, token: string) => request<{review: {verified_nodes: number; verified_edges: number}}>('/review/decisions', {
    method: 'POST', headers: {'Content-Type': 'application/json', ...(token ? {Authorization: `Bearer ${token}`} : {})}, body: JSON.stringify(body),
  }),
  health: () => request<Health>('/health'),
  overview: () => request<Overview>('/overview'),
  sources: () => request<Source[]>('/sources'),
  criteria: (params: { q?: string; source_id?: string; offset?: number; limit?: number }) =>
    request<Page<Criterion>>('/criteria?' + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== '').map(([k, v]) => [k, String(v)])).toString()),
  recognitions: (params: { q?: string; offset?: number; limit?: number }) =>
    request<Page<Recognition>>('/recognitions?' + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)])).toString()),
  forms: () => request<{ items: FormCandidate[] }>('/forms'),
  graph: (params: { q?: string; node_type?: string; limit?: number }) =>
    request<GraphData>('/graph?' + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== '').map(([k, v]) => [k, String(v)])).toString()),
  ask: (query: string, retrieval_mode: 'sparse' | 'hybrid' | 'dense', use_llm: boolean, session_id?: string, signal?: AbortSignal) =>
    request<AskResult>('/query', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, retrieval_mode, use_llm, session_id }), signal }),
  pdf: (sourceId: string, page = 1) => `${BASE}/sources/${encodeURIComponent(sourceId)}/pdf#page=${Math.max(1, page)}`,
}

export interface ReviewItem {
  check?: 'passed' | 'failed' | 'human_verified'; check_reason?: string; origin?: string
  latest_decision: {decision: string; reviewer: string; timestamp: string; notes: string; correction?: object} | null
  dependencies: Array<{target_id: string; label: string | null; type: string; review_status: string}>
  target_id: string; content_hash: string; type: string; label: string | null; source_id: string
  priority: string; state: string; reasons: string[]; review_status: string; properties: Record<string, unknown>
  citations: Array<{source_id: string; pdf_page: number; bbox: number[] | null; quote: string; source_sha256: string; crop_url?: string}>
}

interface CheckCounts { passed: number; failed: number; human_verified: number }
