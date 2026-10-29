# ADR 001: Đồ thị một đầu ra duy nhất

## Bối cảnh
Nhiều tệp đồ thị song song làm phân mảnh dữ liệu, khó kiểm tra toàn vẹn và dễ để truy vấn chạm vào nhánh chưa thẩm định.

## Quyết định
* Toàn bộ tri thức thực thể và quan hệ nằm trong một tập đầu ra chuẩn tại `data/processed/ocop/graph/`: `nodes.jsonl`, `edges.jsonl` và `manifest.json`.
* Mọi nút và cạnh mang trường `check` và `origin` để truy nguyên và lọc khi đọc.
* Bản ghi vi phạm ràng buộc giữ thông tin lỗi trong cùng đầu ra đồ thị; runtime loại chúng khỏi truy vấn công khai. Không duy trì `rejected.jsonl` riêng.

## Hệ quả
* Runtime, router và frontend chỉ đọc một nguồn đồ thị có mã băm SHA-256 được kiểm.
* Không có nhánh tương thích trung gian; việc xuất sang Neo4j đi từ cùng một tập đầu ra.
