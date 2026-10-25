import { useEffect, useRef, useState } from "react";
import type { AskResult, Citation } from "../../api/client";
import assistantWelcome from "../../assets/assistant-welcome.png";
import assistantAvatar from "../../assets/assistant-avatar.png";
import { Icon } from "../../components/Icon";
import { CitationText } from "./CitationText";

export type Message = {
  id: string;
  time: string;
  question: string;
  answer?: AskResult;
  error?: string;
};
const suggestions = [
  "Hồ sơ đăng ký OCOP gồm những gì?",
  "Quy trình đánh giá OCOP như thế nào?",
  "Tìm tiêu chí đánh giá sản phẩm",
  "Các biểu mẫu hồ sơ OCOP",
];
const followups = [
  "Tóm tắt ngắn gọn",
  "Giải thích chi tiết hơn",
  "Xem căn cứ trích dẫn",
  "Tìm văn bản liên quan",
];

export function ChatView({
  messages,
  busy,
  question,
  setQuestion,
  useLlm,
  setUseLlm,
  onSend,
  onOpen,
  onGraph,
}: {
  messages: Message[];
  busy: boolean;
  question: string;
  setQuestion: (value: string) => void;
  useLlm: boolean;
  setUseLlm: (value: boolean) => void;
  onSend: (text?: string) => void;
  onOpen: (citation: Citation) => void;
  onGraph: (message: Message) => void;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [copyError, setCopyError] = useState("");
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [messages, busy]);
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "28px";
      textarea.style.height = `${Math.min(textarea.scrollHeight, 118)}px`;
    }
  }, [question]);
  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(null), 2200);
    return () => window.clearTimeout(timer);
  }, [copied]);
  const copy = async (message: Message) => {
    try {
      await navigator.clipboard.writeText(message.answer?.answer || "");
      setCopied(message.id);
      setCopyError("");
    } catch {
      setCopyError(
        "Trình duyệt chưa cho phép sao chép. Bạn có thể chọn nội dung để sao chép.",
      );
    }
  };
  return (
    <section
      className={`chatbox panel ${messages.length ? "" : "chat-empty"}`}
      aria-label="Hỏi đáp OCOP"
    >
      {!messages.length ? (
        <div className="welcome">
          <img
            className="welcome-assistant"
            src={assistantWelcome}
            alt="Trợ lý OCOP"
          />
          <h1>Xin chào, tôi giúp gì cho bạn về OCOP?</h1>
          <p>Hỏi đáp từ tài liệu nguồn, kèm trích dẫn để đối soát PDF gốc</p>
          <div className="suggestions">
            {suggestions.map((text, i) => (
              <button key={text} onClick={() => onSend(text)} disabled={busy}>
                <span className={`suggestion-icon tone-${i}`}>
                  <Icon
                    name={
                      i === 0
                        ? "file"
                        : i === 1
                          ? "graph"
                          : i === 2
                            ? "criteria"
                            : "book"
                    }
                    size={20}
                  />
                </span>
                <span>{text}</span>
                <Icon name="arrow" size={16} />
              </button>
            ))}
          </div>
          <div className="welcome-note">
            <Icon name="leaf" size={14} />
            Mỗi câu trả lời, một căn cứ rõ ràng
          </div>
        </div>
      ) : (
        <div className="conversation" aria-live="polite">
          {messages.map((message) => (
            <article
              className="message-turn"
              id={`message-${message.id}`}
              key={message.id}
            >
              <div className="user-message">
                <div>
                  <p>{message.question}</p>
                  <time>{message.time}</time>
                </div>
                <span className="user-symbol">
                  <Icon name="user" size={22} />
                </span>
              </div>
              {(message.answer || message.error) && (
                <div className="assistant-message">
                  <img
                    src={assistantAvatar}
                    alt="Trợ lý OCOP"
                    className="assistant-avatar"
                  />
                  <div className="answer-body">
                    {message.error ? (
                      <div className="answer-error" role="alert">
                        <Icon name="info" size={20} />
                        <div>
                          <b>Chưa thể nhận câu trả lời</b>
                          <p>{message.error}</p>
                        </div>
                      </div>
                    ) : (
                      message.answer && (
                        <>
                          <div className="answer-toolbar">
                            <span
                              className={`answer-badge ${message.answer.status === "generated_claims_verified" ? "verified" : ""}`}
                            >
                              <Icon
                                name={
                                  message.answer.status ===
                                  "generated_claims_verified"
                                    ? "check"
                                    : "book"
                                }
                                size={14}
                              />
                              {message.answer.status ===
                              "generated_claims_verified"
                                ? "Câu trả lời đã xác minh"
                                : message.answer.citations.length
                                  ? "Câu trả lời có dẫn chứng"
                                  : "Trợ lý OCOP"}
                            </span>
                            <div className="answer-actions">
                              <button
                                onClick={() => void copy(message)}
                                title="Sao chép câu trả lời"
                                aria-label="Sao chép câu trả lời"
                              >
                                <Icon
                                  name={
                                    copied === message.id ? "check" : "copy"
                                  }
                                  size={17}
                                />
                              </button>
                              <button
                                onClick={() => onGraph(message)}
                                title="Xem đồ thị dẫn chứng"
                                aria-label="Xem đồ thị dẫn chứng"
                              >
                                <Icon name="graph" size={18} />
                              </button>
                            </div>
                          </div>
                          <div className="answer-text">
                            <CitationText
                              text={message.answer.answer}
                              citations={message.answer.citations}
                              onOpen={onOpen}
                            />
                          </div>
                          {!!message.answer.citations.length && (
                            <div className="citation-sources">
                              <h3>
                                <Icon name="file" size={16} />
                                Nguồn tham khảo{" "}
                                <span>({message.answer.citations.length})</span>
                                <button onClick={() => onGraph(message)}>
                                  Xem dẫn chứng <Icon name="graph" size={13} />
                                </button>
                              </h3>
                              {message.answer.citations.map((citation, i) => (
                                <button
                                  className="source-card"
                                  key={i}
                                  onClick={() => onOpen(citation)}
                                >
                                  <span className="file-badge">PDF</span>
                                  <span className="source-copy">
                                    <b>
                                      [S{i + 1}] {citation.source_id}
                                    </b>
                                    <small>
                                      {citation.review_status === "verified"
                                        ? "Nguồn đã xác minh"
                                        : "Nguồn chưa được duyệt"}
                                    </small>
                                  </span>
                                  <span className="source-page">
                                    Trang {citation.pdf_page}
                                  </span>
                                  <Icon name="external" size={15} />
                                </button>
                              ))}
                            </div>
                          )}
                          <details className="answer-details">
                            <summary>Thông tin tra cứu</summary>
                            <p>
                              Trạng thái: {message.answer.status} · Corpus:{" "}
                              {message.answer.corpus_version || "chưa có"}
                            </p>
                            <p>
                              Công cụ:{" "}
                              {message.answer.tools_used.join(", ") ||
                                "Không sử dụng công cụ"}
                            </p>
                          </details>
                        </>
                      )
                    )}
                  </div>
                </div>
              )}
            </article>
          ))}
          {busy && (
            <div className="assistant-message">
              <img src={assistantAvatar} alt="" className="assistant-avatar" />
              <div className="answer-body">
                <div
                  className="typing"
                  role="status"
                  aria-label="Đang tìm bằng chứng"
                >
                  <i />
                  <i />
                  <i />
                  <span>Đang tìm bằng chứng…</span>
                </div>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      )}
      {copyError && (
        <p className="copy-error" role="status">
          {copyError}
        </p>
      )}
      {!!messages.length && (
        <div className="followups">
          {followups.map((text, i) => (
            <button key={text} disabled={busy} onClick={() => onSend(text)}>
              <Icon
                name={
                  i === 0
                    ? "list"
                    : i === 1
                      ? "info"
                      : i === 2
                        ? "book"
                        : "search"
                }
                size={14}
              />
              {text}
            </button>
          ))}
        </div>
      )}
      <form
        className="composer"
        onSubmit={(event) => {
          event.preventDefault();
          onSend();
        }}
      >
        <span className="composer-icon" aria-hidden="true">
          <Icon name="chat" size={21} />
        </span>
        <label className="sr-only" htmlFor="question">
          Câu hỏi
        </label>
        <textarea
          ref={textareaRef}
          id="question"
          rows={1}
          maxLength={4000}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Nhập câu hỏi về quy định, tiêu chuẩn, thủ tục OCOP…"
          required
          onKeyDown={(event) => {
            if (
              event.key === "Enter" &&
              !event.shiftKey &&
              !event.nativeEvent.isComposing
            ) {
              event.preventDefault();
              onSend();
            }
          }}
        />
        <button
          className="send-button"
          type="submit"
          disabled={busy || !question.trim()}
          aria-label="Gửi câu hỏi"
        >
          <Icon name="send" size={23} />
        </button>
        <div className="composer-bottom">
          <button
            type="button"
            className={`answer-mode ${useLlm ? "ai-mode" : ""}`}
            role="switch"
            aria-checked={useLlm}
            onClick={() => setUseLlm(!useLlm)}
            title="Bật hoặc tắt sinh câu trả lời bằng mô hình ngôn ngữ"
          >
            <span className="toggle-track">
              <span />
            </span>
            <b>{useLlm ? "Trợ lý AI" : "Trích dẫn nguồn"}</b>
            <span>{useLlm ? "Có kiểm chứng" : "Không dùng LLM"}</span>
          </button>
          <span className="composer-hint">
            Shift + Enter xuống dòng · nội dung có dẫn chứng
          </span>
        </div>
      </form>
    </section>
  );
}
