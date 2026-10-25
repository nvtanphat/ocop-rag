export type ActiveView = 'chat' | 'docs' | 'crit' | 'prod'

export interface DocInfo {
  title: string
  sub: string
}

export interface SrcItem {
  doc: string
  page: number
  bbox: string
  total: number
  kind: 'pdf' | 'sheet' | 'doc'
  name: string
  sub: string
}

export interface BotAnswer {
  verified: boolean
  html: string
  sources: string[]
  claims?: Array<[string, Array<[string, number]>]>
}

export interface ChatMessage {
  id: string
  sender: 'u' | 'b'
  text: string
  html?: string
  time: string
  verified?: boolean
  sources?: string[]
  ans?: BotAnswer
  liked?: boolean
  disliked?: boolean
  saved?: boolean
}

export interface DocRecord {
  id: string
  code: string
  badge: string
  col: string
  desc: string
  org: string
  scope: string
  pages: number
  cat: string
  year: number
  src?: string
}

export interface CritRecord {
  n: number
  t: string
  doc: string
  src: string
  page: number
}

export interface ProdRecord {
  id: number
  name: string
  owner: string
  loc: string
  stars: number
  kind: string
  code: string
}
