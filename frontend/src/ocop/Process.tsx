import { Route } from 'lucide-react'
import type { AskResult } from './api'

const PATH_LABEL: Record<string, string> = {
  TEXT: 'Tìm văn bản', PINPOINT: 'Tra cứu chính xác', GRAPH: 'Quan hệ trong đồ thị', HYBRID_GRAPH: 'Đồ thị + văn bản',
  AGENTIC: 'Công cụ nghiệp vụ', NONE: 'Không cần truy xuất',
}

const text = (value: unknown) => (typeof value === 'string' ? value : '')

/** What the system really did for this answer, read from the response trace: nothing here is inferred or invented. */
export default function Process({ result }: { result: AskResult }) {
  const trace = result.tool_trace ?? []
  const path = text(trace.find(step => step.step === 'retrieval_strategy')?.retrieval_path)
  const steps = trace.filter(step => step.step === 'tool' || step.step === 'recovery')
  const gaps = [
    ...(result.generation_diagnostics?.missing_from_source ?? []),
    ...(result.evidence_grade?.uncovered_parts ?? []).map(part => `Chưa tìm thấy bằng chứng cho phần: “${part}”`),
  ]
  const rejected = result.generation_diagnostics?.rejected ?? []
  if (!path && !steps.length && !gaps.length && !rejected.length) return null
  return <details className="ocop-process">
    <summary><Route size={14}/> Cách hệ thống tìm câu trả lời{path && <span className="ocop-subtle-chip">{PATH_LABEL[path] ?? path}</span>}</summary>
    {steps.length > 0 && <ol className="ocop-process-steps">{steps.map((step, i) => <li key={i}>
      <strong>{text(step.name)}</strong>{step.step === 'recovery' && <em> · tìm bổ sung</em>}
      <small>{String(step.hits ?? 0)} kết quả · {text(step.status) || 'ok'}</small>
    </li>)}</ol>}
    {gaps.length > 0 && <div className="ocop-process-gaps"><strong>Phần nguồn chưa trả lời</strong><ul>{gaps.map((gap, i) => <li key={i}>{gap}</li>)}</ul></div>}
    {rejected.length > 0 && <div className="ocop-process-gaps"><strong>{rejected.length} ý bị loại vì chưa qua kiểm tra bằng chứng</strong>
      <ul>{rejected.map((item, i) => <li key={i}>{item.claim} <small>({item.reasons.join(', ')})</small></li>)}</ul></div>}
  </details>
}
