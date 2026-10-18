# Kiến trúc OCOP GraphRAG

```text
12 PDF nguồn đã khóa SHA-256
  → profile trang, native text / OCR, bảng và tọa độ
  → EvidenceUnit + review_status + quan hệ nguồn
  → structure/context-aware chunks → BM25 [Dense/Qdrant tùy chọn]
  → typed graph JSONL [Neo4j tùy chọn]
  → business router → planner → bounded agent
  → evidence verification → citation → FastAPI → React
```

## Nguyên tắc

- Mặc định local: BM25, graph JSONL, agent xác định và chế độ no-LLM. Đây là đường được kiểm tra trên 12 PDF / 583 trang.
- Ollama `qwen3.5:2b`, Qdrant `google/embeddinggemma-300m`, CrossEncoder `BAAI/bge-reranker-v2-m3`, MongoDB, Neo4j và LangGraph là tích hợp tùy chọn. Cấu hình có sẵn không đồng nghĩa dịch vụ/model đã được kiểm chứng hoạt động.
- Router phân loại intent nghiệp vụ và lập kế hoạch tool. Các nhãn `PINPOINT`, `TEXT`, `GRAPH`, `HYBRID_GRAPH`, `AGENTIC` mô tả đường thực thi, không chứng minh tất cả backend chạy song song.
- Không dùng OCR candidate để khẳng định số sao/hiệu lực; áp dụng quy tắc xác minh bằng chứng, source scope, source checksum và ranh giới hồ sơ riêng.
- Cache, index và graph dùng fingerprint/phiên bản **nội bộ kỹ thuật** để xác minh tương thích. Không đặt nhãn phiên bản phát hành vào tên tài liệu, benchmark hoặc ZIP.

## Bảo trì

Mọi output (`reports/`, `outputs/`, `data/processed/`, `data/runtime/`, `data/review/`) được tạo lúc chạy và không được đóng gói. Test hồi quy chỉ dùng fixture tổng hợp; PDF và dataset đánh giá gốc được giữ nguyên về nội dung. Các giới hạn và chỉ số được ghi tại [Đánh giá](EVALUATION.md); lệnh vận hành ở [Runbook](E2E_RUNBOOK.md).
