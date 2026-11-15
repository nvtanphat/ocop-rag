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
    <aside id="side" className="glass">
      <nav id="rail" style={{ display: "contents" }} aria-label="Điều hướng">
        {navigation.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`ni ${view === item.id ? "on" : ""}`}
            aria-current={view === item.id ? "page" : undefined}
            onClick={() => onNavigate(item.id)}
            title={item.title}
          >
            <Icon name={item.icon} />
            {item.label}
          </button>
        ))}
      </nav>
      <div className="sdiv" />
      <button
        type="button"
        className={`ni ${view === "history" ? "on" : ""}`}
        onClick={() => onNavigate("history")}
        title="Lịch sử"
      >
        <Icon name="history" />
        Lịch sử
      </button>
      <button
        type="button"
        className="ni dash"
        onClick={onNew}
        disabled={busy}
        title="Cuộc trò chuyện mới"
      >
        <Icon name="plus" />
        Chat mới
      </button>
      <div className="sp" />
      <button
        type="button"
        className="ni sm"
        onClick={onTheme}
        title={dark ? "Giao diện sáng" : "Giao diện tối"}
        aria-label="Đổi giao diện"
      >
        <Icon name={dark ? "moon" : "sun"} />
      </button>
      <button
        type="button"
        className="ni sm"
        onClick={onHelp}
        title="Trợ giúp"
        aria-label="Trợ giúp"
      >
        <Icon name="help" />
      </button>
    </aside>
  );
}
