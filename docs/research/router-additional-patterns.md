# Các pattern bổ sung cho router OCOP

Ngày đọc: 2026-11-02. Bổ sung cho [chẩn đoán](router-diagnosis.md) và [khảo sát trước](router-reference-study.md); chỉ đọc source, không đổi runtime, gold, index hay reference. Đây là suy luận thiết kế từ implementation, chưa phải kết quả cải thiện accuracy.

## Phạm vi và commit pin

| Checkout | Commit đã đọc | Nguồn upstream |
|---|---|---|
| `reference/graphiti` | `16bf514380de4e44884aed6779bece220e6fe470` | [getzep/graphiti](https://github.com/getzep/graphiti/tree/16bf514380de4e44884aed6779bece220e6fe470) |
| `reference/navinsreyas-agentic-rag` | `9cbb2bacf15568369f173fe44c925343b9a6e2df` | [navinsreyas/agentic-rag](https://github.com/navinsreyas/agentic-rag/tree/9cbb2bacf15568369f173fe44c925343b9a6e2df) |
| `reference/llm-graph-builder` | `a728de68d8c75720081816d47b5900a84d93fdcf` | [neo4j-labs/llm-graph-builder](https://github.com/neo4j-labs/llm-graph-builder/tree/a728de68d8c75720081816d47b5900a84d93fdcf) |

## 1. Graphiti: chọn một ứng viên do server cung cấp

**Code có thật:** ingest giải quyết entity theo identity properties, rồi tên chính xác/fuzzy, cuối cùng mới nhờ LLM cho phần chưa giải quyết: [node_operations.py:816](https://github.com/getzep/graphiti/blob/16bf514380de4e44884aed6779bece220e6fe470/graphiti_core/utils/maintenance/node_operations.py#L816). Identity key chỉ tồn tại khi đủ các thuộc tính cấu hình; nếu nhiều candidate trùng key thì code chọn theo `created_at`, UUID: [dedup_helpers.py:236](https://github.com/getzep/graphiti/blob/16bf514380de4e44884aed6779bece220e6fe470/graphiti_core/utils/maintenance/dedup_helpers.py#L236). Tên chuẩn hóa khớp nhiều entity được đẩy sang LLM, không lấy match đầu tiên: [dedup_helpers.py:321](https://github.com/getzep/graphiti/blob/16bf514380de4e44884aed6779bece220e6fe470/graphiti_core/utils/maintenance/dedup_helpers.py#L321).

LLM nhận danh sách candidate có ID, tên, nhãn và summary cùng current/previous episodes. Output có schema `NodeResolutions`; runtime bỏ ID entity ngoài khoảng/ID lặp, và coi candidate ID không hợp lệ là không merge: [node_operations.py:649](https://github.com/getzep/graphiti/blob/16bf514380de4e44884aed6779bece220e6fe470/graphiti_core/utils/maintenance/node_operations.py#L649). Schema và prompt có lựa chọn `-1`, kể cả khi không chắc: [dedupe_nodes.py:26](https://github.com/getzep/graphiti/blob/16bf514380de4e44884aed6779bece220e6fe470/graphiti_core/prompts/dedupe_nodes.py#L26). Tests mock có kiểm tra identity trước LLM và candidate ID giả: [test_node_operations.py:180](https://github.com/getzep/graphiti/blob/16bf514380de4e44884aed6779bece220e6fe470/tests/utils/maintenance/test_node_operations.py#L180), [:944](https://github.com/getzep/graphiti/blob/16bf514380de4e44884aed6779bece220e6fe470/tests/utils/maintenance/test_node_operations.py#L944). Chưa chạy suite upstream trong nghiên cứu này.

**Chuyển sang OCOP:** dùng cơ chế chọn candidate cho **tham chiếu truy vấn**, không mang thao tác merge ingest vào router. Catalog hiện hành tạo candidate document/product/subgroup với ID do server cấp. Model chỉ chọn một ID hoặc yêu cầu hỏi rõ; server ràng buộc ID với corpus/version đã khóa. Nhiều ứng viên cùng tên nhưng khác văn bản/năm cần hỏi rõ hoặc dùng định danh rõ trong câu, không lấy ứng viên cũ nhất như identity-resolution upstream. Có thể bổ sung cấu trúc `clarification` gồm loại entity, các candidate ID và câu hỏi; planner đã chặn thực thi khi `needs_clarification`: [contracts.py:47](../../ai_core/orchestration/ocop/contracts.py#L47), [planner.py:132](../../ai_core/orchestration/ocop/planner.py#L132).

**Không giải quyết:** Graphiti không có ở các hàm trên một quy trình hỏi người dùng rồi resume chọn entity. `-1` nghĩa không duplicate, không phải hành động clarification. ID nằm trong catalog cũng không chứng minh chọn đúng nghĩa. Exact/fuzzy matching không được dùng để xác minh score/star, thay đổi phiên bản quyết định hay biến OCR candidate thành fact.

## 2. navinsreyas: budget phải nằm ở execution, và phải kiểm tra cả code lẫn prompt

**Code có thật:** tool đăng ký qua `@rag_agent.tool`; mỗi wrapper gọi `_check_tool_limits` trước I/O và `_store_tool_result` sau I/O. `AgentDependencies` giữ cache/count cho lượt; ngưỡng thực là **2**, không phải số round model: [agent.py:42](https://github.com/navinsreyas/agentic-rag/blob/9cbb2bacf15568369f173fe44c925343b9a6e2df/agent/agent.py#L42), [:83](https://github.com/navinsreyas/agentic-rag/blob/9cbb2bacf15568369f173fe44c925343b9a6e2df/agent/agent.py#L83), [:138](https://github.com/navinsreyas/agentic-rag/blob/9cbb2bacf15568369f173fe44c925343b9a6e2df/agent/agent.py#L138). Metric tăng trước kiểm tra nên đếm cả lần bị chặn/cache. Budget check đứng trước cache lookup nên khi đủ hai call, ngay cả cache hit cũng nhận limit notice.

**Khác với lời nhắc:** prompt nói chỉ được **một** retrieval tool nhưng code cho hai: [prompts.py:13](https://github.com/navinsreyas/agentic-rag/blob/9cbb2bacf15568369f173fe44c925343b9a6e2df/agent/prompts.py#L13). Prompt cũng nói có thể dùng fallback ở lượt sau; đây không phải planner nhiều task có dependency. API ghép sáu message cuối vào prompt và chạy agent; fallback model dùng lại cùng `deps`: [api.py:420](https://github.com/navinsreyas/agentic-rag/blob/9cbb2bacf15568369f173fe44c925343b9a6e2df/agent/api.py#L420). Không nên tin comment rằng mỗi lần `agent.run()` tự reset deps: caller tạo deps mới, nhưng nhánh fallback dùng lại instance.

**Giới hạn có thể suy ra trực tiếp từ code:** count chỉ tăng **sau** `await`. Nếu ba wrapper chạy đồng thời lúc count bằng 0, cả ba có thể qua check trước khi call nào hoàn tất. Đây là phân tích scheduling, chưa khẳng định đã tái hiện qua PydanticAI runtime. Tool I/O ném exception trước store cũng không tăng count. Trả một chuỗi “stop” cho model không đặt trần số lần model tiếp tục đề nghị gọi tool.

**Chuyển sang OCOP:** giữ plan/DAG và registry server hiện có, tổng năm calls dùng chung cho tất cả task/recovery. Nếu tương lai cho model gọi tool động, execution phải giữ/chốt budget trước khi dispatch, trace số call đề nghị/thực thi/bị chặn riêng. Không sao chép cache này như một bảo đảm concurrency. OCOP đã kiểm tra budget ở [planner.py:151](../../ai_core/orchestration/ocop/planner.py#L151); cần xác nhận cả recovery dùng cùng tổng, không thay bằng “năm round”.

**Không giải quyết:** agent không có schema nối business intent với capability, không xác minh entity/version và không cung cấp benchmark routing tiếng Việt. Cho model chọn tool tự do chưa sửa được lỗi capability/intent lệch nhau của OCOP.

## 3. llm-graph-builder: rewrite theo hội thoại có thật; clarification chỉ là prompt

**Code có thật:** một message đi thẳng vào retriever; nhiều message đi qua prompt + LLM + `StrOutputParser`, rồi retriever: [QA_integration.py:303](https://github.com/neo4j-labs/llm-graph-builder/blob/a728de68d8c75720081816d47b5900a84d93fdcf/backend/src/QA_integration.py#L303). Prompt yêu cầu tạo một search query từ hội thoại: [constants.py:304](https://github.com/neo4j-labs/llm-graph-builder/blob/a728de68d8c75720081816d47b5900a84d93fdcf/backend/src/shared/constants.py#L304). Đây là rewrite chuỗi truy hồi, không phải output có intent/task/entity schema.

Caller truyền `mode` vào `QA_RAG`; mode được tra trong config, sau đó chọn retrieval query/index và document filter: [QA_integration.py:697](https://github.com/neo4j-labs/llm-graph-builder/blob/a728de68d8c75720081816d47b5900a84d93fdcf/backend/src/QA_integration.py#L697), [:346](https://github.com/neo4j-labs/llm-graph-builder/blob/a728de68d8c75720081816d47b5900a84d93fdcf/backend/src/QA_integration.py#L346), [:389](https://github.com/neo4j-labs/llm-graph-builder/blob/a728de68d8c75720081816d47b5900a84d93fdcf/backend/src/QA_integration.py#L389). Vì vậy không dùng tên các mode làm bằng chứng có automatic business router. Câu “ambiguous thì hỏi clarification” nằm trong answer prompt: [constants.py:272](https://github.com/neo4j-labs/llm-graph-builder/blob/a728de68d8c75720081816d47b5900a84d93fdcf/backend/src/shared/constants.py#L272); các hàm khảo sát không xuất trạng thái clarification hoặc danh sách candidate cho planner.

**Chuyển sang OCOP:** có thể rewrite câu tiếp nối như “còn nhóm đó?” sau khi đã có entity rõ trong state. Giữ query gốc và slot/version xác định tách khỏi rewrite; chuỗi model tạo không được tự sửa pinned decision hay bổ sung rule. Với nhiều cách hiểu còn hợp lệ, trả clarification trước truy hồi thay vì hy vọng answer prompt sẽ hỏi đúng sau khi retrieve.

**Không giải quyết:** rewrite không phân rã nhiều nhu cầu thành task có thể kiểm tra, không thống nhất intent/capability và không có kiểm tra provenance chuẩn OCOP ở các bước này.

## Thử nghiệm thiết kế đáng làm tiếp

Ba checkout bổ sung mạnh nhất cho **candidate-constrained resolution**, và chỉ rõ những cách dễ nhầm budget hoặc prompt với bảo đảm runtime. Không checkout nào trong các đường code đã đọc cung cấp sẵn contract đa task/clarification đầy đủ cho OCOP.

Một thiết kế nhỏ để kiểm chứng: structured proposal gồm scope, các task nghiệp vụ, slot có nguồn từ câu/state/catalog, cùng clarification khi entity chưa rõ; một mapping server duy nhất tạo capabilities và intent trình bày từ task đã chấp nhận. Đây là **đề xuất cho OCOP**, không phải tính năng được tìm thấy nguyên vẹn ở ba repo. Nó nhắm lỗi intent/capability bất nhất và mất nhu cầu phụ đã ghi trong chẩn đoán; không thay retriever, ontology hoặc cơ chế kiểm chứng facts.

Trên dev, so với baseline: required-tool coverage cho từng task, chọn đúng candidate/version, hỏi rõ đúng lúc, giữ pinned version khi đổi năm, từ chối câu ngoài miền chỉ nhắc địa phương, tổng calls ≤5. Thêm một ca có sáu nhu cầu thực sự cần hơn năm calls để kiểm tra kết quả split/clarify thay vì âm thầm cắt task. Giữ metric intent/lane cũ song song; không đổi gold sealed. Chưa có phép chạy upstream hoặc kết quả accuracy mới trong note này.
