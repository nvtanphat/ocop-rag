# Nghiên cứu mã nguồn router trong các dự án tham chiếu

Ngày khảo sát: 2026-11-02. Phạm vi: đọc mã nguồn cục bộ trong `reference/`, đối chiếu hợp đồng OCOP; không sửa runtime, không chạy benchmark của dự án khác, không sửa PDF. Các số dòng dưới đây tính từ đầu file tại checkout được khảo sát. Đây là bằng chứng về cơ chế, không phải bằng chứng rằng cơ chế đó làm tăng điểm trên OCOP.

## Kết luận chính

Không có căn cứ từ các đường mã được khảo sát để kết luận rằng thay router OCOP bằng một router tham chiếu sẽ nâng chất lượng. Các dự án giải những bài toán khác nhau: phân lớp ngữ nghĩa, chọn nhánh workflow, chọn công cụ bằng LLM, hoặc chỉ chuyển chế độ truy hồi. OCOP đã có phân lớp bằng embedding, nhãn nghiệp vụ, capabilities, công cụ bắt buộc/tùy chọn và kiểm soát hội thoại riêng: `ai_core/orchestration/ocop/semantic_route.py:29`, `ai_core/orchestration/ocop/contracts.py:26`, `ai_core/orchestration/ocop/contracts.py:47`.

Điểm đáng học nhất là mô tả ranh giới nhãn thật rõ, dùng lịch sử có cấu trúc, lưu trace theo từng quyết định, và đánh giá riêng ý định, đối tượng/thời điểm, công cụ cần thiết, truy hồi bằng chứng và câu trả lời. Việc chỉ chấm một nhãn `lane` làm mất thông tin: trong OCOP nhãn này được suy ra từ toàn bộ công cụ, kể cả tùy chọn, theo thứ tự ưu tiên graph → pinpoint → text; bản thân module gọi nó là thông tin quan sát. Nguồn: `ai_core/orchestration/ocop/router.py:1056`, `ai_core/orchestration/ocop/retrieval_strategy.py:1`, `ai_core/orchestration/ocop/retrieval_strategy.py:21`.

## Nguồn và phiên bản

Đọc trực tiếp source và tests tại các đường dẫn được trích bên dưới. Remote và HEAD lấy bằng `git remote get-url origin` / `git rev-parse HEAD`. Các repo trong bảng không có thay đổi tracked khi khảo sát; không kiểm tra toàn bộ untracked artifacts. Không coi HEAD cục bộ là phiên bản upstream mới nhất.

| Thư mục trong `reference/` | Upstream origin | HEAD |
|---|---|---|
| `ragflow` | https://github.com/infiniflow/ragflow.git | `12d9a38e24bf3fb8573b83bc41a2fe75dcd2c281` |
| `R2R` | https://github.com/SciPhi-AI/R2R.git | `9c5a94d151f90876bd7eb860f300a8fd662dc481` |
| `LightRAG` | https://github.com/HKUDS/LightRAG.git | `aaebfe1bb8d55deb6a4304d357a3bf4c92fcd40a` |
| `graphrag` | https://github.com/microsoft/graphrag.git | `c600ff80b77b9b62c47d539a3ac9569e95d8949b` |
| `Agentic-RAG` | https://github.com/Akiyue/Agentic-RAG.git | `d420d1817acb8146d42e14359f0d6a29cf5ebb39` |
| `Legal-RAG` | https://github.com/ngnam1104/Legal-RAG.git | `0b4ca6fe9a445c52e0612664b561221acaeace41` |
| `JuanLUJoanne-agentic-rag` | https://github.com/JuanLUJoanne/agentic-rag.git | `5c07a5667aea283c8bf5c0ff77eb3f65c431d79c` |
| `Vietnamese-GraphRAG-Demo` | https://github.com/Thanhngo0812/Vietnamese-GraphRAG-Demo.git | `2ecf76e9296447894e881eebb082200aef80c1c2` |
| `ViHERMES` | https://github.com/ura-hcmut/ViHERMES.git | `9cdbdb91b61f4552f10fe9642530a1afe6497f2f` |
| `vn-legal-rag` | https://github.com/hienlh/vn-legal-rag.git | `4e1a6c1be320afe7ec5d3aef2ef54b87c47e65d2` |
| `luatdo` | https://github.com/tamnd/luatdo.git | `42cd4817b41ae9bbe4c889e79d892a02160a0c5f` |

Đã đọc hướng dẫn gốc của workspace và `AGENTS.md` của ragflow, LightRAG, vn-legal-rag. GitNexus được vn-legal-rag yêu cầu cho điều hướng nhưng công cụ đó không có trong phiên này; khảo sát dùng source trực tiếp và không chỉnh sửa symbol nào. Không suy luận từ README thay cho implementation.

## 1. Agentic-RAG: semantic routing thật, bằng centroid mẫu

`reference/Agentic-RAG/app/retrieval/router.py:19` định nghĩa bốn nhánh `vector`, `sql`, `graph`, `small_talk`. Mỗi nhánh có ba câu mẫu tiếng Anh (`:26`); vector mẫu được lấy trung bình, chuẩn hóa thành centroid (`:68`). Query được chuẩn hóa rồi so tích vô hướng với từng centroid; chọn điểm cao nhất, dưới ngưỡng mặc định 0.35 thì chuyển sang VECTOR (`:57`, `:77`). Không có margin giữa hai lớp trong hàm này, không có nhãn clarification, và chỉ trả một nhánh.

Đây là phân lớp dựa trên embedding của mẫu, không phải router được huấn luyện riêng trên tập OCOP. OCOP hiện dùng điểm mẫu gần nhất theo từng nhãn rồi kiểm tra cả score lẫn margin: `ai_core/orchestration/ocop/semantic_route.py:35`, `ai_core/orchestration/ocop/router.py:672`. Vì vậy thêm centroid routing không giải quyết một năng lực đang hoàn toàn thiếu. Centroid và nearest-example cần được so sánh trên cùng tập phát triển nếu muốn thử; không có cơ sở chọn centroid chỉ vì repo gọi nó là semantic router.

Tests tham chiếu dùng `FakeEmbedder` với từ khóa và vector giả lập, thay exemplar cho khớp chính bộ từ khóa ấy (`reference/Agentic-RAG/tests/test_router.py:8`, `:36`), rồi kiểm tra SQL và greeting (`:50`). Chúng xác nhận phép chọn nhánh, không đo khả năng hiểu paraphrase tiếng Việt, câu nhiều ý hay ngoài miền.

## 2. RAGFlow: classifier và agent chọn công cụ là hai đường riêng

Checkout này có hướng triển khai Go trong `internal/agent`; không lấy Python legacy làm đại diện runtime hiện tại, theo `reference/ragflow/AGENTS.md`.

`Categorize` nhận danh mục, mô tả, ví dụ, default và cửa sổ lịch sử (`reference/ragflow/internal/agent/component/categorize.go:29`). Prompt yêu cầu chọn đúng một danh mục, ưu tiên danh mục cụ thể, có thể kèm mô tả và ví dụ (`:185`). Kết quả được ánh xạ sang downstream handle qua `CategoryRoutes` (`:124`). Cơ chế này là LLM classification để điều khiển workflow, không phải tự suy ra toàn bộ kế hoạch công cụ.

Một điểm rất dễ đọc nhầm: output `scores` là one-hot 1.0/0.0, không phải xác suất đã hiệu chỉnh (`:98`, `:180`). Với driver `SystemOne`, code hỏi mô hình decision xác suất cho từng danh mục và lấy lớn nhất (`reference/ragflow/internal/agent/component/categorize_decision.go:12`), nhưng wrapper vẫn xuất one-hot. Không được dùng số 1.0 này để so chất lượng/confidence với cosine của OCOP.

Đường agent khác dùng ReAct của Eino với công cụ đã build, `ToolsConfig`, recorder và ngân sách round (`reference/ragflow/internal/agent/component/agent.go:166`). Khi hết round, model bị cấm gọi thêm tool và được yêu cầu trả lời bằng bằng chứng đã có, nêu phần thiếu (`:272`). Bài học áp dụng được là trace công cụ và trạng thái hết ngân sách rõ ràng; không suy ra rằng tự do ReAct tốt hơn kế hoạch OCOP.

Giới hạn bằng chứng: tests classifier kiểm tra kết quả/fallback qua `stubInvoker` (`reference/ragflow/internal/agent/component/categorize_test.go:17`, `:55`). Chúng không chứng minh routing accuracy trên OCOP. Ngân sách round/node của ReAct cũng không mặc nhiên tương đương giới hạn năm lần gọi công cụ.

## 3. R2R: LLM lựa công cụ từ registry, lặp theo kết quả

RAG agent tạo công cụ được yêu cầu trong config qua `ToolRegistry`, tên không tìm thấy chỉ được log (`reference/R2R/py/core/agent/rag.py:72`). Lúc dispatch, tên phải khớp công cụ đã đăng ký (`reference/R2R/py/core/base/agent/agent.py:127`, `:174`). Agent gửi lịch sử cho LLM, nhận tool calls, lưu kết quả và lặp (`reference/R2R/py/core/agent/base.py:104`, `:168`). Đây là chọn công cụ bằng mô hình, không phải classifier cố định với một nhãn ý định nghiệp vụ.

Điểm cần tránh sao chép: `max_iterations` đếm lượt model (`:114`), trong khi một response có thể chứa nhiều `tool_calls` được chạy tuần tự (`:178`). Do đó `max_iterations=5` không đảm bảo tổng số tool calls ≤5. OCOP phải giữ kiểm tra tổng calls và allowlist hiện có: `ai_core/orchestration/ocop/capabilities.py:46`, `ai_core/orchestration/ocop/planner.py:131`.

Bài học khả thi: dùng mô hình để đề xuất hành động có schema rồi ánh xạ về registry và dependency DAG của server; lưu proposal, kế hoạch được chấp nhận và kết quả. Đây là đề xuất thiết kế từ source, chưa phải cải thiện đã đo. Không mang web search, Python execution hay công cụ ngoài miền vào OCOP chỉ vì framework hỗ trợ.

## 4. LightRAG và Microsoft GraphRAG: cần phân biệt mode với router

LightRAG khai báo `QueryParam.mode` là tham số caller, mặc định `mix`, với `local/global/hybrid/naive/mix/bypass` (`reference/LightRAG/lightrag/base.py:89`). Runtime dispatch theo giá trị này (`reference/LightRAG/lightrag/lightrag.py:5042`, `:5148`). Các đường này không tự phân loại ý định câu hỏi để chọn mode. Chúng không cung cấp bằng chứng rằng ghép từ khóa vào `hybrid` là cải tiến semantic routing.

Microsoft GraphRAG có API riêng cho `global_search`, `local_search`, `drift_search`, `basic_search` (`reference/graphrag/packages/graphrag/graphrag/api/query.py:63`, `:191`, `:322`, `:454`). DRIFT thực sự lập các câu hỏi bổ sung sau primer, xếp action chưa hoàn tất, mở rộng tối đa `n_depth` và `drift_k_followups` (`reference/graphrag/packages/graphrag/graphrag/query/structured_search/drift_search/search.py:234`). Nó là cơ chế lập kế hoạch truy hồi bên trong mode đã chọn, không phải router nhận diện OCOP criteria/procedure/recognition.

Bài học: tách lựa chọn hành động nghiệp vụ khỏi cách retriever thực hiện hành động ấy. Nếu thử decomposition, mỗi subquery vẫn phải giữ document/version, bằng chứng và ngân sách tổng của OCOP. Không đồng nhất mỗi follow-up do model sinh với một nhu cầu đã được người dùng yêu cầu.

## 5. Các dự án pháp lý/tiếng Việt

### Legal-RAG

Một lần gọi LLM gộp standalone rewrite, intent và metadata filters (`reference/Legal-RAG/backend/agent/query_router.py:16`). Router nhận bốn message cuối cùng cùng văn bản/thực thể đang nói (`:31`); prompt yêu cầu khôi phục tham chiếu và cấm thêm nội dung trả lời vào câu viết lại (`reference/Legal-RAG/backend/prompt.py:9`). Đây là bài học cụ thể cho câu tiếp nối và ngôn ngữ đời thường.

Tuy nhiên chỉ có hai nhánh legal/general; nhãn lạ hoặc lỗi parsing chuyển sang LEGAL_CHAT (`reference/Legal-RAG/backend/agent/query_router.py:86`). Prompt gom hầu hết vấn đề pháp lý/đời sống vào legal (`reference/Legal-RAG/backend/prompt.py:17`). Không thể chuyển nguyên cách fallback này sang hệ OCOP có phạm vi hẹp, pinned version và nhiều công cụ nghiệp vụ. Việc LLM trích filters cũng chưa tự xác minh chúng là danh tính/version hợp lệ trong corpus.

### vn-legal-rag

Analyzer tách intent pháp lý và query type, có bảng cấu hình alpha/hops/reasoning/temporal (`reference/vn-legal-rag/vn_legal_rag/online/vietnamese-legal-query-analyzer.py:25`, `:57`). Implementation classifier thực tế là regex theo thứ tự; fallback LLM được mô tả nhưng chưa triển khai (`:388`, `:406`). Không được ghi nhận đây là hybrid semantic router đã hoạt động.

Trong engine, nhánh retrieval khảo sát chạy dual-level và tree theo ablation config (`reference/vn-legal-rag/vn_legal_rag/online/legal-graphrag-3tier-query-engine.py:326`); metadata trả ra lại hardcode `hybrid_alpha=0.7`, `max_hops=2`, `use_temporal=False` (`:280`). Bảng cấu hình có tên hay metadata có giá trị chưa chứng minh execution đã tuân theo chúng. Đây là lý do phải trace cả caller và dispatch khi đánh giá router OCOP.

Script evaluation có hit@k, recall@k, reciprocal rank và thống kê theo loại/document (`reference/vn-legal-rag/scripts/evaluate-retrieval-performance-on-test-set.py:224`, `:457`, `:550`). Các đại lượng đó đánh giá bằng chứng truy hồi; không chuyển chúng thành routing accuracy. Nghiên cứu này không dùng các file results để tuyên bố repo tốt hơn OCOP vì khác dữ liệu/corpus và chưa tái lập chạy.

### ViHERMES

Interpreter có schema `regulatory/use_graph`, xác thực hai giá trị bool; mã văn bản lấy bằng regex từ query thay vì tin document ID model sinh (`reference/ViHERMES/src/vihermes/agents.py:11`, `:34`). Pathfinder thực hiện seed retrieval và chỉ graph-expand nếu plan yêu cầu (`:55`). Đây là ví dụ cụ thể về việc model đề xuất phạm vi, còn định danh ràng buộc bằng xử lý xác định.

Auditor kiểm tra citation/quote, nguồn hết hiệu lực và ngày, rồi mới semantic verification nếu có LLM (`:79`); offline chỉ chấp nhận claim trích nguyên văn (`:124`). Đúng citation không đồng nghĩa entailment, phù hợp với quy tắc OCOP. Evaluator lưu từng prediction và mẫu số hợp lệ riêng cho từng metric, phân nhóm theo hop (`reference/ViHERMES/src/vihermes/evaluation.py:32`, `:85`). Không có bằng chứng ở các hàm này về độ chính xác router OCOP, kiểm chứng score/star hay khả năng giữ pinned OCOP decision version.

### Vietnamese-GraphRAG-Demo và luatdo

Demo expose ba endpoint riêng basic/local/global; caller chọn endpoint (`reference/Vietnamese-GraphRAG-Demo/backend/app/main.py:78`, `:94`, `:110`). Không coi cache `.pyc` có tên `auto_agent` là source chứng minh router tự động.

`luatdo/route` là failover giữa nhà cung cấp/model đang khả dụng, retry khi lỗi/cooldown (`reference/luatdo/route/route.go:252`). Tên `Router` ở đây không có nghĩa là phân loại nghiệp vụ pháp lý.

## 6. Router heuristic và rủi ro nhầm nhãn với năng lực

JuanLUJoanne phân loại simple/complex/ambiguous bằng số từ, dấu hỏi, từ khóa tiếng Anh và tách `and` (`reference/JuanLUJoanne-agentic-rag/src/agents/query_router.py:36`, `:42`). Câu ≤2 từ bị gắn ambiguous bất kể thực thể hay lịch sử; node chỉ đọc query (`:77`). Tests xác nhận chính những quy tắc này (`reference/JuanLUJoanne-agentic-rag/tests/unit/test_query_router.py:11`, `:49`). Không áp dụng số từ tiếng Anh cho câu Việt nhiều âm tiết hoặc câu ngắn có định danh rõ như yêu cầu mở một quyết định.

Docstring nói LLM từng tăng latency/cost mà không tăng recall (`reference/JuanLUJoanne-agentic-rag/src/agents/query_router.py:1`); khảo sát này không tìm/kiểm chứng thí nghiệm đứng sau câu đó, nên chỉ ghi nhận đây là phát biểu trong source, không dùng làm kết luận thực nghiệm.

## 7. Hành động đề xuất cho OCOP và cách đo

Các mục dưới đây là suy luận thiết kế từ đối chiếu source; cần kiểm chứng trên tập phát triển trước khi đổi runtime. Báo cáo nghiên cứu này không đổi nhãn gold hoặc cấu hình để làm đẹp điểm.

1. **Chẩn đoán từng tầng trước khi thay router.** Ghi lại scope/dialogue → slots/temporal version → intent/capabilities → required/secondary tools → tool plan → evidence. OCOP đã có các trường này (`ai_core/orchestration/ocop/contracts.py:47`) và evaluator đã chạy route rồi plan (`tools/evaluate_router.py:66`). Tách lỗi nhãn khỏi lỗi công cụ và lỗi truy hồi; một ý định bị gắn sai nhưng vẫn chọn đúng công cụ khác với từ chối nhầm hay chọn sai corpus.
2. **Đánh giá hành động trực tiếp.** Bổ sung gold công cụ bắt buộc, công cụ chấp nhận được và công cụ cấm, thay vì dùng exact lane làm đại diện duy nhất. Đo required-tool recall, precision/cost cho công cụ thêm, vi phạm allowlist/budget và slot accuracy. Lưu lane của công cụ bắt buộc và lane toàn kế hoạch riêng nếu cần quan sát. Lý do: `choose_retrieval_path` là ánh xạ nhiều-một, graph/pinpoint có quyền ưu tiên bất kể primary/optional (`ai_core/orchestration/ocop/retrieval_strategy.py:21`); evaluator hiện so lane chính xác với một gold (`tools/evaluate_router.py:104`). Giữ metric cũ để so trước/sau, không sửa nghĩa metric âm thầm.
3. **Hiệu chỉnh semantic fallback bằng lỗi thực tế.** So rules-only, rules+embedding và rules+embedding+LLM trên cùng dev; phân tầng câu thiếu từ OCOP, paraphrase, câu nhiều nhu cầu, câu tiếp nối, tiếng Việt không dấu. OCOP đã có score+margin và chỉ override một số luật yếu (`ai_core/orchestration/ocop/router.py:672`, `:939`). Cần đo bao nhiêu lỗi không bao giờ tới semantic tier; thêm câu mẫu không sửa được một nhánh sai đã return trước đó. Báo coverage/abstention cùng accuracy có điều kiện, không coi cosine là confidence đã hiệu chỉnh.
4. **Nếu dùng LLM rộng hơn, mở rộng proposal có ràng buộc.** Đề xuất cấu trúc về hành động/capability và span nguồn của slot; công cụ thực thi vẫn ánh xạ từ registry của server, giữ DAG và tổng năm calls. OCOP đã có allowlist/dependency checks (`ai_core/orchestration/ocop/planner.py:99`, `:131`); không cần thêm một framework agent tự do để làm việc này. Không dùng số round của R2R/RAGFlow thay cho tổng tool calls.
5. **Đánh giá end-to-end bằng evidence.** Theo bài học ViHERMES/vn-legal-rag, giữ prediction từng dòng, mẫu số metric, phân nhóm theo hop/loại/document. Đo evidence recall và answer correctness riêng; thêm deterministic checks cho score/star, đúng decision version và provenance page/bbox/evidence ID/SHA-256. Router tốt không thể biến OCR chưa xác minh thành fact. Nguồn nguyên tắc: `AGENTS.md`; ví dụ tách grounding: `reference/ViHERMES/src/vihermes/agents.py:83`.

Giới hạn: chưa thực thi các router upstream với cùng dữ liệu OCOP, chưa đo latency/cost hay lợi ích centroid/LLM/decomposition. Các repo không dùng cùng taxonomy, lịch sử, phiên bản văn bản hoặc chuẩn provenance OCOP. Do đó kết quả này cung cấp cơ chế và giả thuyết có thể kiểm thử, không đưa ra bảng xếp hạng chất lượng framework.
