# ADR 001: Đồ thị một đầu ra duy nhất (Single Graph Output)

## Bối cảnh
Trước đây, hệ thống sinh ra nhiều file đồ thị trung gian rời rạc (`agent_nodes.jsonl`, `agent_edges.jsonl`, các lớp layout riêng biệt), gây phân mảnh dữ liệu, khó kiểm tra tính toàn vẹn và tạo nguy cơ truy vấn nhầm vào các nhánh chưa được thẩm định.

## Quyết định
* Hợp nhất toàn bộ tri thức thực thể và quan hệ vào một tập đầu ra đồ thị chuẩn duy nhất tại `data/processed/ocop/graph/`: `nodes.jsonl`, `edges.jsonl` và `manifest.json`.
* Mọi nút và cạnh đều mang trường `check` (`passed` hoặc `human_verified`) và `origin` (`deterministic`, `llm`, hoặc `human`).
* Các đối tượng vi phạm ràng buộc kỹ thuật được ghi riêng vào `rejected.jsonl` và bị loại hoàn toàn khỏi các truy vấn runtime.

## Hệ quả
* Runtime, router và frontend chỉ đọc từ một nguồn đồ thị đã được xác thực mã băm SHA-256.
* Loại bỏ toàn bộ các nhánh tương thích trung gian và đơn giản hóa việc xuất sang Neo4j.
