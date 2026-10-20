# Tham khảo kiến trúc extraction và graph cho OCOP

Ngày đối chiếu: 20/10/2026. Chỉ dùng tài liệu và mã nguồn chính thức; các URL nhánh `main` có thể thay đổi. Đây là phân tích mẫu thiết kế, không phải kết quả benchmark chất lượng OCOP.

## Microsoft GraphRAG

GraphRAG tạo entity/relation theo text unit, hợp nhất entity cùng tên và loại, rồi tóm tắt mô tả. Community và community report phục vụ truy vấn tổng quan. Schema đầu ra giữ `text_unit_ids`; BYOG cho phép dùng graph tự trích xuất thay vì bắt buộc dùng extractor mặc định. [Dataflow](https://github.com/microsoft/graphrag/blob/main/docs/index/default_dataflow.md), [outputs](https://github.com/microsoft/graphrag/blob/main/docs/index/outputs.md), [BYOG](https://github.com/microsoft/graphrag/blob/main/docs/index/byog.md).

Áp dụng OCOP: giữ graph hiện tại, liên kết entity/relation với EvidenceUnit. Không đồng nhất tổ chức chỉ bằng tên; không dùng mô tả tổng hợp làm chứng cứ pháp lý. Community report chỉ đáng thêm khi có nhu cầu hỏi tổng quan đã xác định.

## LightRAG

LightRAG kết hợp truy xuất local, global và chunk trong chế độ `mix`. Mã nguồn lưu `source_id` cho entity/relation; xử lý merge có theo dõi chunk nguồn và chống cộng lại trọng số khi cùng nguồn được xử lý lại. [README](https://github.com/HKUDS/LightRAG), [operate.py](https://github.com/HKUDS/LightRAG/blob/main/lightrag/operate.py).

Áp dụng OCOP: phối hợp seed từ tìm kiếm văn bản với traversal giới hạn; đưa chunk chứng cứ trở lại context. Kiểm tra idempotency của merge bằng evidence ID. Trọng số/tần suất xuất hiện chỉ giúp retrieval, không chứng minh đúng hay xác nhận điểm/sao. Provenance OCOP cần chi tiết hơn chunk ID: trang PDF, bbox và SHA nguồn.

## Google LangExtract

LangExtract dùng ví dụ và schema cho đầu ra có cấu trúc, hỗ trợ chunking và nhiều lượt extraction. Resolver phân biệt exact, partial và fuzzy alignment; tìm được vị trí văn bản không đồng nghĩa đã chứng minh quan hệ. [README](https://github.com/google/langextract), [resolver.py](https://github.com/google/langextract/blob/main/langextract/resolver.py).

Áp dụng OCOP: anchor và offset của từng mention/thuộc tính phải ánh xạ về EvidenceUnit và vùng PDF. Giữ OCR nguyên văn; alignment gần đúng chỉ tạo ứng viên duyệt. Hai entity cùng xuất hiện trong một đoạn chưa đủ để kết luận OWNED_BY hoặc REQUIRES_EVIDENCE. Chứng cứ cần chứa đúng chủ thể, vị ngữ, đối tượng và điều kiện áp dụng.

## LlamaIndex Property Graph

`SchemaLLMPathExtractor` kiểm tra loại entity/relation và đường quan hệ theo schema; chế độ strict lọc triple ngoài schema. Property graph retrieval có thể phối hợp truy xuất synonym, vector và đường graph. Mã nguồn hỗ trợ danh sách triple `(subject_type, relation, object_type)` cho validation. [Hướng dẫn chính thức](https://developers.llamaindex.ai/python/framework/module_guides/indexing/lpg_index_guide/), [schema_llm.py](https://github.com/run-llama/llama_index/blob/main/llama-index-core/llama_index/core/indices/property_graph/transformations/schema_llm.py).

Áp dụng OCOP: dùng ontology để kiểm tra cả hai đầu cạnh; schema hợp lệ vẫn cần verification ngữ nghĩa. Giữ truy vấn có tham số, giới hạn hops và loại quan hệ. Không cần đưa lớp framework mới vào để thực hiện các kiểm tra này.

## Đối chiếu code hiện có và hướng tích hợp

Những nhận xét dưới đây là kết luận từ code OCOP, không phải cam kết của các framework tham khảo:

- `processing/ocop/knowledge_extract.py` đã điều phối deterministic extraction, semantic extraction, LLM proposal và quality audit trong cùng pipeline. Tiếp tục mở rộng đường này; không tạo pipeline song song.
- `knowledge/ocop/llm_proposals.py` đã có whitelist loại/thuộc tính, alignment nguồn, chunk overlap, cache và reconciliation. Điểm cần bảo vệ bằng regression là gắn thuộc tính đúng entity, giữ evidence khi merge và phân biệt nguồn văn bản với semantic entailment. JSON mode và prompt schema không tự bảo đảm schema ở phía provider; cần validation ứng dụng rõ ràng.
- `knowledge/ocop/contracts.py` và `graph/ocop/ontology.py` là hợp đồng nghiệp vụ và ontology materialization. Cần kiểm tra chúng đồng bộ bằng test; tránh nhân bản danh sách quan hệ trong prompt hoặc adapter.
- `graph/ocop/builder.py` đã kiểm tra citation và giữ trạng thái candidate. Builder không được nâng `verified` chỉ vì quote/bbox hợp lệ; verification phải độc lập với extraction và khớp hash nội dung.
- `graph/ocop/retriever.py` đã giới hạn traversal 0–3 hops, kiểm tra snapshot, hỗ trợ lọc verified và chặn fan-out qua document hub. Retrieval/Agent phải chọn đúng version và trạng thái theo mục đích, đồng thời trả provenance của mọi cạnh được dùng.

Ưu tiên kỹ thuật: kiểm tra hợp đồng xuyên Extraction → Graph → Retrieval → Agent; ID ổn định theo định danh và phạm vi pháp lý; merge bảo toàn evidence, trạng thái và xung đột thuộc tính; regression cho co-occurrence sai, tên trùng, phủ định/điều kiện và bằng chứng stale. Với điểm/sao, giữ deterministic checks và duyệt nguồn riêng; không dùng LLM làm thẩm quyền xác nhận.

Không đề xuất cài Microsoft GraphRAG, LightRAG, LangExtract hoặc LlamaIndex như dependency mới. Các mẫu thiết kế cần thiết đã có điểm tích hợp trong code hiện tại. Chưa có benchmark Precision/Recall/F1 hoặc bằng chứng rằng thêm community detection, graph database hay framework sẽ cải thiện corpus OCOP.
