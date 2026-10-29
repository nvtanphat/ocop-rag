import { useEffect, useRef, useState } from "react";
import {
  api,
  retrievalModeFor,
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
import { Icon, type IconName } from "../components/Icon";
import type { View } from "./navigation";
import "../styles/workspace.css";

const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "Không tải được dữ liệu OCOP.";
const placeholders: Record<View, string> = {
  chat: "Khám phá tri thức OCOP...",
  documents: "Tìm văn bản pháp quy...",
  criteria: "Tìm tiêu chí chấm điểm...",
  products: "Tìm sản phẩm OCOP...",
  history: "Tìm trong lịch sử...",
};

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
  // The shared stylesheet keys its layout off body state.
  useEffect(() => {
    const body = document.body;
    body.dataset.view = view === "chat" ? "chat" : view;
    body.classList.toggle("dark", dark);
    body.classList.toggle("pdf-open", view === "chat" && !!selected);
    body.classList.toggle("graph-open", view === "chat" && graphOpen);
  }, [view, dark, selected, graphOpen]);

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
        retrieval_mode: retrievalModeFor(health),
        use_llm: useLlm,
      });
      setMessages((previous) =>
        previous.map((message) => (message.id === id ? { ...message, answer } : message)),
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
    setView("chat");
    setSelected(citation);
    setGraphOpen(false);
  };
  const openDocument = (source: Source) =>
    openCitation({ source_id: source.source_id, pdf_page: 1, evidence_unit_id: null });
  const openGraph = (message?: Message) => {
    setView("chat");
    setGraphMessage(
      message || [...messages].reverse().find((item) => item.answer?.citations.length) || null,
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

  const viewState = (name: string) =>
    errors[name] ? (
      <div className="vstate err" role="alert">
        <h3>Không tải được dữ liệu</h3>
        <p>{errors[name]}</p>
        <button type="button" onClick={() => void load()}>
          Thử lại
        </button>
      </div>
    ) : null;
  const heading = (icon: IconName, title: string, text: string) => (
    <div className="vhead">
      <div className="vico" style={{ background: "#eef0ed", color: "#2f6b52" }}>
        <Icon name={icon} size={28} strokeWidth={1.8} />
      </div>
      <div className="vt">
        <h2>{title}</h2>
        <p>{text}</p>
      </div>
    </div>
  );

  return (
    <>
      <Backdrop />
      <TopHeader
        health={health}
        loading={loading}
        error={errors.health}
        onReload={() => void load()}
        search={search}
        placeholder={placeholders[view]}
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
      <main id="main">
        {view === "chat" && (
          <>
            <ChatView
              messages={messages}
              sources={sources}
              busy={busy}
              question={question}
              setQuestion={setQuestion}
              useLlm={useLlm}
              setUseLlm={setUseLlm}
              onSend={(text) => void send(text)}
              onOpen={openCitation}
              onGraph={openGraph}
            />
            {selected ? (
              <EvidenceViewer
                key={`${selected.source_id}:${selected.pdf_page}:${selected.evidence_unit_id}`}
                citation={selected}
                source={sources.find((source) => source.source_id === selected.source_id)}
                onClose={() => setSelected(null)}
              />
            ) : graphOpen ? (
              <EvidenceGraph
                key={graphMessage?.id}
                message={graphMessage}
                sources={sources}
                onOpen={openCitation}
                onClose={() => setGraphOpen(false)}
              />
            ) : (
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
            )}
          </>
        )}
        {view === "documents" && (
          <section className="glass view" aria-label="Thư viện văn bản">
            {viewState("documents") || (
              <DocumentsView
                sources={sources}
                search={search}
                setSearch={setSearch}
                loaded={!loading}
                onOpen={openDocument}
              />
            )}
          </section>
        )}
        {(view === "criteria" || view === "products") && (
          <section
            className="glass view"
            aria-label={view === "criteria" ? "Tiêu chí OCOP" : "Sản phẩm OCOP"}
          >
            {viewState(view) || (
              <ReferenceView
                key={view}
                kind={view}
                data={view === "criteria" ? criteria : products}
                sources={sources}
                search={search}
                setSearch={setSearch}
                loaded={!loading}
                onOpen={openCitation}
              />
            )}
          </section>
        )}
        {view === "history" && (
          <section className="glass view" aria-label="Lịch sử hội thoại">
            {heading("history", "Lịch sử hội thoại", "Các câu hỏi trong phiên tra cứu hiện tại")}
            {!messages.length ? (
              <div className="vstate">
                <h3>Chưa có cuộc trò chuyện</h3>
                <p>Bắt đầu một câu hỏi để tra cứu tri thức OCOP.</p>
                <button type="button" onClick={() => navigate("chat")}>
                  Bắt đầu hỏi đáp
                </button>
              </div>
            ) : (
              <div className="hist">
                {messages
                  .filter((message) =>
                    message.question.toLocaleLowerCase().includes(search.toLocaleLowerCase()),
                  )
                  .map((message) => (
                    <button key={message.id} type="button" onClick={() => replay(message)}>
                      <Icon name="chat" size={22} />
                      <span className="t">
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
                    </button>
                  ))}
              </div>
            )}
          </section>
        )}
      </main>
      {help && (
        <div className="help-backdrop" onClick={() => setHelp(false)}>
          <section
            className="help-dialog"
            role="dialog"
            aria-modal="true"
            aria-label="Hướng dẫn sử dụng"
            onClick={(event) => event.stopPropagation()}
          >
            <h2>Tra cứu OCOP có căn cứ</h2>
            <p>
              Đặt câu hỏi ở khung chat. Bấm vào ký hiệu [S…] hoặc thẻ nguồn để xem đúng trang và
              vùng trích dẫn trên PDF gốc.
            </p>
            <p>
              Thông tin chưa được duyệt sẽ có nhãn riêng. Tiêu chí và sản phẩm chỉ hiển thị khi có
              dữ liệu xác minh.
            </p>
            <p className="gnote">
              <kbd>Ctrl K</kbd> tìm kiếm nhanh · <kbd>Esc</kbd> đóng bảng đang mở
            </p>
            <button type="button" onClick={() => setHelp(false)}>
              Đã hiểu
            </button>
          </section>
        </div>
      )}
    </>
  );
}
