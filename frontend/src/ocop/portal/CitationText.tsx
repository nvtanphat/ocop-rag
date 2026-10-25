import ReactMarkdown from 'react-markdown'
import type { Citation } from '../api/client'

export function CitationText({ text, citations, onOpen }: {
  text: string; citations: Citation[]; onOpen: (citation: Citation) => void
}) {
  // Markdown is rendered without raw HTML. Only existing markers become buttons.
  const linked = text.replace(/\[S(\d+)\]/g, (marker, n: string) =>
    citations[Number(n) - 1] ? `[${marker}](#citation-${n})` : marker)
  return <ReactMarkdown components={{ a: ({ href, children }) => {
    const match = /^#citation-(\d+)$/.exec(href || '')
    const citation = match && citations[Number(match[1]) - 1]
    return citation
      ? <button className="citation" onClick={() => onOpen(citation)}>{children}</button>
      : <span>{children}</span>
  } }}>{linked}</ReactMarkdown>
}
