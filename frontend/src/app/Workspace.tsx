import { useEffect, useRef, useState } from "react";
import {
  api,
  type Citation,
  type Health,
  type ReferenceResponse,
  type Source,
} from "../api/client";
import { ChatView, type Message } from "../features/chat/ChatView";
import { DocumentsView } from "../features/documents/DocumentsView";
import { ReferenceView } from "../features/references/ReferenceView";
import { EvidenceViewer } from "../features/pdf/EvidenceViewer";
import { EvidenceGraph } from "../features/graph/EvidenceGraph";
import { TopHeader } from "../components/TopHeader";
import { Sidebar } from "../components/Sidebar";
import { RightSidebar } from "../components/RightSidebar";
import { Backdrop } from "../components/Backdrop";
import { Icon } from "../components/Icon";
import type { View } from "./navigation";
import "../styles/workspace.css";

const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "Không tải được dữ liệu OCOP.";
export default function Workspace() {
  const [view, setView] = useState<View>("chat");
  const [health, setHealth] = useState<Health | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [criteria, setCriteria] = useState<ReferenceResponse | null>(null);
  const [products, setProducts] = useState<ReferenceResponse | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [useLlm, setUseLlm] = useState(false);
  const [selected, setSelected] = useState<Citation | null>(null);
  const [graphOpen, setGraphOpen] = useState(false);
  const [graphMessage, setGraphMessage] = useState<Message | null>(null);
  const [help, setHelp] = useState(false);
  const [dark, setDark] = useState(false);
  const [search, setSearch] = useState("");
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID());
  const searchRef = useRef<HTMLInputElement>(null);

  const load = async () => {
    setLoading(true);
    const [h, s, c, p] = await Promise.allSettled([
      api.health(),
      api.sources(),
      api.criteria(),
      api.products(),
    ]);
    const nextErrors: Record<string, string> = {};
    if (h.status === "fulfilled") setHealth(h.value);
    else {
      setHealth(null);
      nextErrors.health = errorText(h.reason);
    }
    if (s.status === "fulfilled") setSources(s.value);
    else {
      setSources([]);
      nextErrors.documents = errorText(s.reason);
    }
    if (c.status === "fulfilled") setCriteria(c.value);
    else {
      setCriteria(null);
      nextErrors.criteria = errorText(c.reason);
    }
    if (p.status === "fulfilled") setProducts(p.value);
    else {
      setProducts(null);
      nextErrors.products = errorText(p.reason);
    }
    setErrors(nextErrors);
    setLoading(false);
  };
  useEffect(() => {
    void load();
  }, []);
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        searchRef.current?.focus();
      }
      if (event.key === "Escape") {
        setSelected(null);
        setGraphOpen(false);
        setHelp(false);
      }
    };
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, []);

  const send = async (suggested?: string) => {
    const text = (suggested ?? question).trim();
    if (busy || !text) return;
    setQuestion("");
    setBusy(true);
    setView("chat");
    const id = crypto.randomUUID();
    const time = new Date().toLocaleTimeString("vi-VN", {
      hour: "2-digit",
      minute: "2-digit",
    });
    setMessages((previous) => [...previous, { id, time, question: text }]);
    try {
      const answer = await api.ask({
        query: text,
        session_id: sessionId,
        retrieval_mode: "sparse",
        use_llm: useLlm,
      });
      setMessages((previous) =>
        previous.map((message) =>
          message.id === id ? { ...message, answer } : message,
        ),
      );
    } catch (error) {
      setMessages((previous) =>
        previous.map((message) =>
          message.id === id ? { ...message, error: errorText(error) } : message,
        ),
      );
    } finally {
      setBusy(false);
    }
  };
  const navigate = (next: View) => {
    setView(next);
    setSearch("");
    setSelected(null);
    setGraphOpen(false);
  };
  const openCitation = (citation: Citation) => {
    setSelected(citation);
    setGraphOpen(false);
  };
  const openDocument = (source: Source) =>
    openCitation({
      source_id: source.source_id,
      pdf_page: 1,
      evidence_unit_id: null,
    });
  const openGraph = (message?: Message) => {
    setGraphMessage(
      message ||
        [...messages].reverse().find((item) => item.answer?.citations.length) ||
        null,
    );
    setGraphOpen(true);
    setSelected(null);
  };
  const newChat = () => {
    setMessages([]);
    setQuestion("");
    setSessionId(crypto.randomUUID());
    navigate("chat");
  };
  const replay = (message: Message) => {
    navigate("chat");
    window.setTimeout(
      () =>
        document
          .getElementById(`message-${message.id}`)
          ?.scrollIntoView({ behavior: "smooth", block: "start" }),
      0,
    );
  };
  const reference = view === "criteria" ? criteria : products;
  const detailed = !!selected || graphOpen;

  return (
    <div className="workspace" data-theme={dark ? "dark" : "light"}>
      <Backdrop />
      <TopHeader
        health={health}
        loading={loading}
        error={errors.health}
        onReload={() => void load()}
        search={search}
        onSearch={setSearch}
        onSubmit={() => {
          if (view === "chat" && search.trim()) {
            void send(search);
            setSearch("");
          }
        }}
        searchRef={searchRef}
        dark={dark}
        onTheme={() => setDark(!dark)}
      />
      <Sidebar
        view={view}
        onNavigate={navigate}
        onNew={newChat}
        busy={busy}
        dark={dark}
        onTheme={() => setDark(!dark)}
        onHelp={() => setHelp(true)}
      />
      <main
        className={`workspace-main ${view === "chat" ? "chat-layout" : "browse-layout"} ${detailed ? "with-detail" : ""}`}
      >
        {view === "chat" ? (
          <ChatView
            messages={messages}
            busy={busy}
            question={question}
            setQuestion={setQuestion}
            useLlm={useLlm}
            setUseLlm={setUseLlm}
            onSend={(text) => void send(text)}
            onOpen={openCitation}
            onGraph={openGraph}
          />
        ) : (
          <section
            className="browse-view panel"
            aria-label={
              view === "documents"
                ? "Thư viện văn bản"
                : view === "history"
                  ? "Lịch sử hội thoại"
                  : view === "criteria"
                    ? "Tiêu chí OCOP"
                    : "Sản phẩm OCOP"
            }
          >
            {loading && view !== "history" && (
              <div className="view-loading" role="status">
                <span className="loading-ring" />
                Đang tải dữ liệu…
              </div>
            )}
            {errors[view] && (
              <p role="alert" className="view-error">
                <Icon name="info" size={18} />
                {errors[view]}
              </p>
            )}
            {view === "documents" ? (
              <DocumentsView
                sources={sources}
                search={search}
                setSearch={setSearch}
                loaded={!loading && !errors.documents}
                onOpen={openDocument}
              />
            ) : view === "history" ? (
              <>
                <div className="view-header">
                  <div className="view-icon">
                    <Icon name="history" size={28} />
                  </div>
                  <div className="view-title">
                    <h1>Lịch sử hội thoại</h1>
                    <p>Các câu hỏi trong phiên tra cứu hiện tại</p>
                  </div>
                  <button
                    className="primary-button"
                    onClick={newChat}
                    disabled={busy}
                  >
                    <Icon name="plus" size={16} />
                    Chat mới
                  </button>
                </div>
                <div className="history-list">
                  {!messages.length ? (
                    <div className="empty-state">
                      <Icon name="history" size={42} />
                      <h2>Chưa có cuộc trò chuyện</h2>
                      <p>Bắt đầu một câu hỏi để tra cứu tri thức OCOP.</p>
                      <button
                        className="primary-button"
                        onClick={() => navigate("chat")}
                      >
                        Bắt đầu hỏi đáp
                        <Icon name="arrow" size={15} />
                      </button>
                    </div>
                  ) : (
                    messages
                      .filter((message) =>
                        message.question
                          .toLocaleLowerCase()
                          .includes(search.toLocaleLowerCase()),
                      )
                      .map((message) => (
                        <button
                          key={message.id}
                          onClick={() => replay(message)}
                        >
                          <span className="history-icon">
                            <Icon name="chat" size={20} />
                          </span>
                          <span>
                            <b>{message.question}</b>
                            <small>
                              {message.answer
                                ? `${message.answer.citations.length} trích dẫn`
                                : message.error
                                  ? "Yêu cầu chưa thành công"
                                  : "Đang xử lý"}
                            </small>
                          </span>
                          <time>{message.time}</time>
                          <Icon name="right" size={16} />
                        </button>
                      ))
                  )}
                </div>
              </>
            ) : (
              <ReferenceView
                data={reference}
                search={search}
                setSearch={setSearch}
                loaded={!loading && !errors[view]}
                kind={view}
                onOpen={openCitation}
              />
            )}
          </section>
        )}
        {selected ? (
          <EvidenceViewer
            key={`${selected.source_id}:${selected.pdf_page}:${selected.evidence_unit_id}`}
            citation={selected}
            source={sources.find(
              (source) => source.source_id === selected.source_id,
            )}
            onClose={() => setSelected(null)}
          />
        ) : graphOpen ? (
          <EvidenceGraph
            message={graphMessage}
            onOpen={openCitation}
            onClose={() => setGraphOpen(false)}
          />
        ) : view === "chat" ? (
          <RightSidebar
            sources={sources}
            products={products}
            loading={loading}
            sourceError={errors.documents}
            productError={errors.products}
            onNavigate={navigate}
            onDocument={openDocument}
            onCitation={openCitation}
            onGraph={() => openGraph()}
          />
        ) : null}
      </main>
      {help && (
        <div className="help-backdrop" onClick={() => setHelp(false)}>
          <section
            className="help-dialog panel"
            role="dialog"
            aria-modal="true"
            aria-label="Hướng dẫn sử dụng"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              className="icon-button help-close"
              onClick={() => setHelp(false)}
              aria-label="Đóng hướng dẫn"
            >
              <Icon name="close" />
            </button>
            <span className="help-emblem">
              <Icon name="book" size={32} />
            </span>
            <h2>Tra cứu OCOP có căn cứ</h2>
            <p>
              Đặt câu hỏi ở khung chat. Bấm vào ký hiệu [S…] hoặc thẻ nguồn để
              xem đúng trang và vùng trích dẫn trên PDF gốc.
            </p>
            <p>
              Thông tin chưa được duyệt sẽ có nhãn riêng. Tiêu chí và sản phẩm
              chỉ hiển thị khi có dữ liệu xác minh.
            </p>
            <span className="keyboard-tip">
              <kbd>Ctrl K</kbd>Tìm kiếm nhanh<kbd>Esc</kbd>Đóng bảng đang mở
            </span>
          </section>
        </div>
      )}
    </div>
  );
}
