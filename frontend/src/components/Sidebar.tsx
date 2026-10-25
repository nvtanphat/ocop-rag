import { navigation, type View } from "../app/navigation";
import { Icon } from "./Icon";

export function Sidebar({
  view,
  onNavigate,
  onNew,
  busy,
  dark,
  onTheme,
  onHelp,
}: {
  view: View;
  onNavigate: (view: View) => void;
  onNew: () => void;
  busy: boolean;
  dark: boolean;
  onTheme: () => void;
  onHelp: () => void;
}) {
  return (
    <aside className="sidebar panel">
      <nav aria-label="Điều hướng">
        {navigation.map((item) => (
          <button
            key={item.id}
            className={`nav-item ${view === item.id ? "active" : ""}`}
            aria-current={view === item.id ? "page" : undefined}
            onClick={() => onNavigate(item.id)}
            title={item.label}
          >
            <Icon name={item.icon} size={24} />
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
      <div className="rail-divider" />
      <button
        className="nav-item new-chat"
        onClick={onNew}
        disabled={busy}
        title="Cuộc trò chuyện mới"
        aria-label="Cuộc trò chuyện mới"
      >
        <Icon name="plus" size={23} />
        <span>Chat mới</span>
      </button>
      <div className="rail-bottom">
        <button
          className="rail-tool"
          onClick={onTheme}
          title={dark ? "Giao diện sáng" : "Giao diện tối"}
          aria-label="Đổi giao diện"
        >
          <Icon name={dark ? "moon" : "sun"} size={23} />
        </button>
        <button
          className="rail-tool"
          onClick={onHelp}
          title="Hướng dẫn sử dụng"
          aria-label="Hướng dẫn sử dụng"
        >
          <Icon name="help" size={23} />
        </button>
      </div>
    </aside>
  );
}
