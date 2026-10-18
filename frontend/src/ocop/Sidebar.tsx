import { Activity, BookOpenText, ChevronLeft, ClipboardList, ScrollText, FileText, GitBranch, Leaf, MessageSquareText, PackageCheck, Plus, X } from 'lucide-react'
import type { Section } from './api'

const menu = [
  { id: 'overview', icon: BookOpenText, label: 'Tổng quan' },
  { id: 'chat', icon: MessageSquareText, label: 'Trợ lý OCOP' },
  { id: 'criteria', icon: ClipboardList, label: 'Bộ tiêu chí' },
  { id: 'forms', icon: ScrollText, label: 'Biểu mẫu hồ sơ' },
  { id: 'recognitions', icon: PackageCheck, label: 'Sản phẩm công nhận' },
  { id: 'documents', icon: FileText, label: 'Thư viện văn bản' },
  { id: 'graph', icon: GitBranch, label: 'Đồ thị tri thức' },
  { id: 'system', icon: Activity, label: 'Trạng thái hệ thống' },
] as const

export default function Sidebar({ section, onNavigate, onNewChat, open, onClose, healthy }: {
  section: Section; onNavigate: (section: Section) => void; onNewChat: () => void
  open: boolean; onClose: () => void; healthy: boolean
}) {
  const nav = (id: Section) => { onNavigate(id); onClose() }
  return <>
    <div className={`ocop-sidebar-overlay ${open ? 'show' : ''}`} onClick={onClose} />
    <aside className={`ocop-sidebar ${open ? 'is-open' : ''}`} aria-label="Điều hướng OCOP">
      <div className="ocop-brand">
        <div className="ocop-brand-mark"><Leaf size={24} strokeWidth={2.15} /></div>
        <div className="ocop-brand-text"><strong>OCOP<span> RAG</span></strong><small>Knowledge workspace</small></div>
        <button aria-label="Đóng menu" className="ocop-mobile-close" onClick={onClose}><X size={18} /></button>
      </div>
      <div className="ocop-workspace-label">KHÔNG GIAN TRI THỨC</div>
      <button className="ocop-new-btn" onClick={() => { onNewChat(); nav('chat') }}><Plus size={18}/> Hỏi một câu mới <span>↗</span></button>
      <nav className="ocop-menu">
        <div className="ocop-group-label">KHÁM PHÁ</div>
        {menu.slice(0, 6).map(item => <button key={item.id} className={`ocop-nav-item ${section === item.id ? 'selected' : ''}`} onClick={() => nav(item.id)}>
          <item.icon size={19} strokeWidth={1.8} /><span>{item.label}</span>{section === item.id && <span className="ocop-nav-dot"/>}
        </button>)}
        <div className="ocop-group-label ocop-group-advanced">NÂNG CAO</div>
        {menu.slice(6).map(item => <button key={item.id} className={`ocop-nav-item ${section === item.id ? 'selected' : ''}`} onClick={() => nav(item.id)}>
          <item.icon size={19} strokeWidth={1.8} /><span>{item.label}</span>{section === item.id && <span className="ocop-nav-dot"/>}
        </button>)}
      </nav>
      <div className="ocop-sidebar-bottom">
        <div className="ocop-data-mini"><div className="ocop-mini-orbit"><Leaf size={17}/></div><div><strong>Chương trình OCOP</strong><small>Mỗi xã một sản phẩm</small></div><ChevronLeft size={15}/></div>
        <div className="ocop-online"><span className={`ocop-status-dot ${healthy ? 'online' : 'offline'}`}/>{healthy ? 'Chỉ mục sẵn sàng' : 'Đang kiểm tra dữ liệu'}<span className="ocop-online-version">End-to-end</span></div>
      </div>
    </aside>
  </>
}
