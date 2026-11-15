import { useEffect, useRef, useState } from "react";
import type { AskResult, Citation, Source } from "../../api/client";
import assistantWelcome from "../../assets/assistant-welcome.png";
import assistantAvatar from "../../assets/assistant-avatar.png";
import { sourceTitle } from "../../app/sourceLabels";
import { Icon, type IconName } from "../../components/Icon";
import { CitationText } from "./CitationText";

export type Message = {
  id: string;
  time: string;
  question: string;
  answer?: AskResult;
  error?: string;
};
// The backend prefixes answers from a partial corpus with this line; the badge above the answer replaces it.
const PARTIAL_NOTICE = "[Corpus chưa đầy đủ";
const withoutPartialNotice = (text: string) =>
  text.startsWith(PARTIAL_NOTICE) ? text.slice(text.indexOf("\n") + 1).trimStart() : text;
const suggestions = [
  "Hồ sơ đăng ký OCOP gồm những gì?",
  "Quy trình đánh giá OCOP như thế nào?",
  "Tìm tiêu chí đánh giá sản phẩm",
  "Các biểu mẫu hồ sơ OCOP",
];
const followups: Array<[string, IconName]> = [
  ["Tóm tắt ngắn gọn", "list"],
  ["Giải thích chi tiết hơn", "info"],
  ["So sánh các văn bản liên quan", "compare"],
  ["Tìm thêm văn bản liên quan", "search"],
];

export function ChatView({
  messages,
  sources,
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
  sources: Source[];
  busy: boolean;
  question: string;
  setQuestion: (value: string) => void;
  useLlm: boolean;
  setUseLlm: (value: boolean) => void;
  onSend: (text?: string) => void;
  onOpen: (citation: Citation) => void;
  onGraph: (message: Message) => void;
}) {
  const convoRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [copyError, setCopyError] = useState("");
  const sourceOf = (citation: Citation) =>
    sources.find((source) => source.source_id === citation.source_id);

  useEffect(() => {
    const convo = convoRef.current;
    if (convo) convo.scrollTop = convo.scrollHeight;
  }, [messages, busy]);
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "26px";
      textarea.style.height = `${Math.min(textarea.scrollHeight, 120)}px`;
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
      setCopyError("Trình duyệt chưa cho phép sao chép. Bạn có thể chọn nội dung để sao chép.");
    }
  };

  return (
    <section
      className={`cv glass chatbox ${messages.length ? "" : "empty"}`}
      id="chatbox"
      aria-label="Hỏi đáp OCOP"
    >
      <div id="welcome">
        <img src={assistantWelcome} alt="Trợ lý OCOP" />
        <h2>Xin chào, tôi giúp gì cho bạn về OCOP?</h2>
        <p>Hỏi đáp từ tài liệu nguồn, kèm trích dẫn để đối soát PDF gốc</p>
        <div className="wsug">
          {suggestions.map((text) => (
            <button key={text} type="button" onClick={() => onSend(text)} disabled={busy}>
              {text}
            </button>
          ))}
        </div>
      </div>
      <div id="convo" ref={convoRef} aria-live="polite">
        {messages.map((message) => (
          <div key={message.id} id={`message-${message.id}`} style={{ display: "contents" }}>
            <div className="msg u">
              <div className="ub">
                <div className="bub">{message.question}</div>
                <time>{message.time}</time>
              </div>
              <Icon name="userSolid" size={30} className="uic" />
            </div>
            {(message.answer || message.error) && (
              <div className="msg b">
                <img className="rb" src={assistantAvatar} alt="" />
                <div className="body">
                  {message.error ? (
                    <div className="errbox" role="alert">
                      <b>Chưa thể nhận câu trả lời</b>
                      {message.error}
                    </div>
                  ) : (
                    message.answer && (
                      <>
                        <div className="tools2">
                          <button
                            type="button"
                            className={copied === message.id ? "on" : ""}
                            onClick={() => void copy(message)}
                            title="Sao chép câu trả lời"
                            aria-label="Sao chép câu trả lời"
                          >
                            <Icon name={copied === message.id ? "check" : "copy"} size={19} strokeWidth={1.8} />
                          </button>
                          <button
                            type="button"
                            onClick={() => onGraph(message)}
                            title="Xem đồ thị dẫn chứng"
                            aria-label="Xem đồ thị dẫn chứng"
                          >
                            <Icon name="graph" size={19} strokeWidth={1.8} />
                          </button>
                        </div>
                        {message.answer.status === "partial_debug_corpus" ? (
                          <span className="verify warn">Corpus chưa đầy đủ — kết quả chỉ để thử nghiệm</span>
                        ) : message.answer.status === "generated_claims_verified" ? (
                          <span className="verify">
                            Câu trả lời đã xác minh <Icon name="checkBadge" size={14} />
                          </span>
                        ) : (
                          message.answer.citations.length > 0 && (
                            <span className="verify warn">Có dẫn chứng, chưa xác minh từng ý</span>
                          )
                        )}
                        <CitationText
                          text={withoutPartialNotice(message.answer.answer)}
                          citations={message.answer.citations}
                          onOpen={onOpen}
                        />
                        {message.answer.citations.length > 0 && (
                          <div className="srcs">
                            <h4>
                              <Icon name="docs" size={18} strokeWidth={1.8} />
                              Nguồn tham khảo ({message.answer.citations.length})
                              <button type="button" className="glink" onClick={() => onGraph(message)}>
                                Xem đồ thị dẫn chứng
                              </button>
                            </h4>
                            {message.answer.citations.map((citation, index) => {
                              const source = sourceOf(citation);
                              return (
                                <button
                                  key={index}
                                  type="button"
                                  className="src"
                                  onClick={() => onOpen(citation)}
                                >
                                  <span className="fi k-pdf">PDF</span>
                                  <div className="t">
                                    <b>
                                      [S{index + 1}] {sourceTitle(source, citation.source_id)}
                                    </b>
                                    <span>
                                      {citation.review_status === "verified" || source
                                        ? "Nguồn đã xác minh"
                                        : "Nguồn chưa được duyệt"}
                                    </span>
                                  </div>
                                  <span className="pg">Trang {citation.pdf_page}</span>
                                  <span className="ext">
                                    <Icon name="external" size={18} strokeWidth={1.8} />
                                  </span>
                                </button>
                              );
                            })}
                          </div>
                        )}
                        <details>
                          <summary>Thông tin tra cứu</summary>
                          <p>
                            Trạng thái: {message.answer.status} · Corpus:{" "}
                            {message.answer.corpus_version || "chưa có"}
                          </p>
                          <p>
                            Công cụ: {message.answer.tools_used.join(", ") || "Không sử dụng công cụ"}
                          </p>
                        </details>
                      </>
                    )
                  )}
                </div>
              </div>
            )}
          </div>
        ))}
        {busy && (
          <div className="msg b">
            <img className="rb" src={assistantAvatar} alt="" />
            <div className="body">
              <div className="typing" role="status" aria-label="Đang tìm bằng chứng">
                <i />
                <i />
                <i />
                <span>Đang tìm bằng chứng…</span>
              </div>
            </div>
          </div>
        )}
      </div>
      <div id="follow">
        {messages.length > 0 &&
          followups.map(([text, icon]) => (
            <button key={text} type="button" disabled={busy} onClick={() => onSend(text)}>
              <Icon name={icon} size={16} strokeWidth={1.8} />
              {text}
            </button>
          ))}
      </div>
      {copyError && (
        <p className="gnote" role="status" style={{ padding: "0 30px 6px" }}>
          {copyError}
        </p>
      )}
      <form
        className="cmp"
        id="form"
        autoComplete="off"
        onSubmit={(event) => {
          event.preventDefault();
          onSend();
        }}
      >
        <span className="clip" aria-hidden="true">
          <Icon name="chat" size={21} strokeWidth={2} />
        </span>
        <label className="sr-only" htmlFor="q">
          Câu hỏi
        </label>
        <textarea
          ref={textareaRef}
          id="q"
          rows={1}
          maxLength={4000}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Nhập câu hỏi về quy định, tiêu chuẩn, thủ tục OCOP..."
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              onSend();
            }
          }}
        />
        <button
          type="submit"
          className="send hov"
          id="btnSend"
          disabled={busy || !question.trim()}
          aria-label="Gửi câu hỏi"
        >
          <Icon name="send" size={22} strokeWidth={2} style={{ color: "#fff" }} />
        </button>
        <div
          className={`seg ${useLlm ? "wide" : ""}`}
          role="switch"
          aria-checked={useLlm}
          tabIndex={0}
          title="Bật hoặc tắt sinh câu trả lời bằng mô hình ngôn ngữ"
          onClick={() => setUseLlm(!useLlm)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              setUseLlm(!useLlm);
            }
          }}
        >
          <div className="sw" />
          <span className={useLlm ? "" : "cur"}>Trích dẫn nguồn</span>
          <span className={useLlm ? "cur" : ""}>Trợ lý AI (có kiểm chứng)</span>
        </div>
        <div className="hint">Shift + Enter xuống dòng · nội dung có dẫn chứng</div>
      </form>
    </section>
  );
}
