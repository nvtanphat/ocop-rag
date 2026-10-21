# Hướng dẫn Phát triển & Mở rộng (Developer Guide)

Tài liệu cung cấp các quy chuẩn phát triển phần mềm, quy trình kiểm thử hermetic, quy ước đóng góp commit và các bước mở rộng công cụ hoặc quan hệ đồ thị mới trong OCOP GraphRAG.

---

## 1. Môi trường Phát triển & Quy chuẩn Kiểm thử

### Cài đặt Môi trường Phát triển
```powershell
python -m pip install -e .
npm --prefix frontend install
```

### Chạy Toàn bộ Bộ Kiểm thử (Pytest)
```powershell
python -m pytest
```

### Nguyên tắc Kiểm thử Hermetic (Không Đọc .env Ngoại vi)
* **Khái niệm**: Mọi bài kiểm thử trong `tests/ocop/` phải có tính độc lập và tái lập tuyệt đối (hermetic), không bị ảnh hưởng bởi các cấu hình hay khóa bí mật lưu trong file `.env` cục bộ của nhà phát triển.
* **Cơ chế thực thi**: Trong `tests/conftest.py`, hàm nạp file môi trường `load_env_file` của module `ai_core.orchestration.ocop.llm` được monkeypatch thành hàm rỗng:
  ```python
  # tests/conftest.py
  @pytest.fixture(autouse=True)
  def _isolate_test_environment(monkeypatch):
      from ai_core.orchestration.ocop import llm
      monkeypatch.setattr(llm, "load_env_file", lambda path=None: None)
  ```
* **Yêu cầu đối với lập trình viên**: Khi viết bài test mới, tuyệt đối không phụ thuộc vào các biến môi trường ngoài mà phải thiết lập tường minh qua fixture `monkeypatch.setenv`.

### Kiểm tra Cú pháp & Vệ sinh Mã nguồn (Ruff)
```powershell
python -m ruff check --select F .
```
Mã nguồn phải đạt trạng thái sạch hoàn toàn lỗi imports thừa (`F401`), biến chưa dùng (`F841`) và các lỗi logic biến (`F`).

### Kiểm tra Đóng gói Frontend
```powershell
npm --prefix frontend run build
```

---

## 2. Quy ước Đóng góp (Commit Conventions)

1. **Định dạng Conventional Commits**:
   Mọi commit phải tuân theo cấu trúc chuẩn:
   ```
   <loại>(<phạm vi>): <mô tả ngắn bằng tiếng Anh hoặc tiếng Việt>
   ```
   * Các loại commit chính:
     * `feat`: Thêm chức năng mới.
     * `fix`: Sửa lỗi.
     * `cleanup`: Dọn dẹp dead code, biến thừa, loại bỏ tương thích cũ.
     * `refactor`: Tái cấu trúc mã nguồn, gộp logic trùng lặp (không đổi hành vi).
     * `docs`: Cập nhật tài liệu kỹ thuật.
     * `test`: Bổ sung hoặc cập nhật kiểm thử.
   * Ví dụ:
     * `cleanup(core): remove unused functions, constants and regex patterns`
     * `refactor(retrieval): deduplicate vietnamese text folding and jsonl reading`
     * `docs: rewrite complete technical documentation and add adr records`

2. **Các điều cấm kỵ khi commit**:
   * **Cấm đưa file `.env` vào Git**: Tệp `.env` chứa bí mật cấu hình cá nhân, tuyệt đối không được stage hay commit.
   * **Cấm commit các thư mục phát sinh lúc runtime**: Không commit các thư mục tạm như `reports/`, `outputs/`, `data/processed/`, `data/runtime/`, `data/review/`.
   * **Cấm thêm dòng chữ ký tác giả tự động của AI**: Không commit các dòng meta như "Co-authored-by: Claude...".

---

## 3. Hướng dẫn Mở rộng Hệ thống (Extensibility)

### Cách Thêm một Công cụ Mới (Adding a New Tool)

1. **Đăng ký Công cụ vào Bảng Danh mục (`TOOL_REGISTRY`)**:
   Mở tệp `ai_core/orchestration/ocop/capabilities.py`, khai báo công cụ mới vào từ điển `TOOL_REGISTRY`:
   ```python
   # ai_core/orchestration/ocop/capabilities.py
   TOOL_REGISTRY: dict[str, ToolSpec] = {
       ...
       'lookup_market_price': ToolSpec(
           name='lookup_market_price',
           produces=('price_candidate', 'market_unit_id'),
           requires_auth=False,
           source_backed=True,
           description='Tra cứu khung giá thị trường tham chiếu cho sản phẩm OCOP'
       ),
   }
   ```
   * **Quy tắc an toàn**: Router có thể đề xuất nhiều công cụ nhưng hệ thống **không bao giờ thực thi công cụ chưa được đăng ký**. Số lượng công cụ tối đa được gọi trong một chu trình truy vấn mặc định là **5**.

2. **Triển khai Logic Thực thi Công cụ**:
   Mở tệp `ai_core/orchestration/ocop/tools.py` và bổ sung phương thức xử lý tương ứng trong class `ToolRegistry`:
   ```python
   # ai_core/orchestration/ocop/tools.py
   def dispatch(self, name: str, **kwargs) -> dict:
       ...
       if name == 'lookup_market_price':
           return self._lookup_market_price(kwargs.get('slots'), kwargs.get('context'))
   ```

3. **Bổ sung Kiểm thử**:
   Viết bài kiểm thử đơn vị trong `tests/ocop/` để xác thực đầu ra của công cụ, đảm bảo mọi dữ liệu trả về đều chứa căn cứ trích dẫn nguồn hoặc trạng thái kiểm tra hợp lệ.

---

### Cách Thêm một Loại Quan hệ Đồ thị Mới (Adding a Graph Relation)

1. **Khai báo Ràng buộc Kiểu Nút Nguồn và Đích**:
   Mở tệp `ai_core/graph/ocop/ontology.py`, bổ sung quan hệ vào bảng `EDGE_ENDPOINTS`:
   ```python
   # ai_core/graph/ocop/ontology.py
   EDGE_ENDPOINTS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
       ...
       # Quan hệ: [Sản phẩm] ĐẠT_TIÊU_CHUẨN -> [Bộ tiêu chí]
       'MEETS_STANDARD': (frozenset({'Product'}), frozenset({'Criterion', 'StarLevel'})),
   }
   ```

2. **Cập nhật Logic Xây dựng Cạnh Đồ thị**:
   Trong `ai_core/graph/ocop/builder.py`, thêm logic tạo cạnh quan hệ từ dữ liệu trích xuất tri thức, đảm bảo gán đúng thuộc tính:
   * `source_entity_id`: ID của nút nguồn.
   * `target_entity_id`: ID của nút đích.
   * `relation_type`: Tên quan hệ đã đăng ký (ví dụ: `MEETS_STANDARD`).
   * `check`: `passed` hoặc `human_verified`.
   * `origin`: `deterministic` hoặc `llm`.
   * `evidence`: Danh sách trích dẫn `EvidenceUnit` làm căn cứ chứng minh quan hệ.

3. **Kiểm thử Kiểm định Đồ thị**:
   Chạy `python -m pytest tests/ocop/test_single_graph_output.py tests/ocop/test_graph_integrity.py` để kiểm tra việc tuân thủ ontology và schema revision.

---

## 4. Quy tắc chống hardcode

Mã runtime (`ai_core/`, `backend/`, `ocr/ocop_ocr/`, `ocop_contracts/`) không chứa giá trị riêng của corpus: mã nguồn `source_id`, số hiệu văn bản, tên địa phương, tên sản phẩm/chủ thể/cơ quan, số trang, số điều/khoản/phiếu/mẫu, số hạng sao, số nhóm sản phẩm.

| Loại giá trị | Nơi đúng |
| :--- | :--- |
| Văn bản, địa danh trong corpus, sản phẩm, chủ thể, cơ quan, phiếu, mẫu | Danh mục thực thể (`entity_catalog.json`, sinh từ registry và graph lúc dựng chỉ mục) |
| Từ khóa ý định, từ nối hội thoại, đại từ, nhãn cột, thang hạng sao, tên tỉnh | `configs/ocop_language.yaml` |
| Ngưỡng, ngân sách token, số ứng viên, trọng số RRF, số luồng | `configs/ocop_retrieval.yaml` / `configs/ocop_models.yaml` |
| Mẫu che định danh | `configs/ocop_privacy.yaml` |
| Văn bản "hiện hành" cho truy vấn không ghim | Registry (`source_kind: ocop_framework`, năm mới nhất), không phải một `source_id` |

Cấu trúc pháp lý chung (mẫu regex `Điều` + chữ số bất kỳ, `Mẫu` + chữ số bất kỳ) vẫn được phép vì là hình thức văn bản, không phải giá trị cụ thể.

**Test chặn**: `tests/ocop/test_no_corpus_literals.py` quét hằng chuỗi trong mã runtime bằng `ast`, so với số hiệu/`source_id`/địa danh trong registry, nhãn sản phẩm/chủ thể/cơ quan của graph mẫu (`tests/ocop/fixtures/corpus_graph_literals.json`) và các mẫu cấu trúc (số điều/mẫu/phiếu cụ thể, lớp hạng sao viết tay). Ngoại lệ phải khai báo trong `tests/ocop/corpus_literal_allowlist.yaml` kèm lý do (hiện rỗng); một mục dư thừa cũng làm test hỏng. Test được dùng fixture cụ thể, nhưng hành vi runtime không được phụ thuộc vào đúng các giá trị đó.

## 5. Thêm một văn bản mới mà không sửa mã

1. Đặt PDF vào `data/raw/ocop/<nhóm>/` và khai báo trong `configs/ocop_sources.json` (`source_id`, `path`, `source_kind`, `document_number`, `jurisdiction`); khóa băm bằng `python tools/cli.py debug lock-ocop`.
2. Chạy lại pipeline (`python tools/cli.py run --build-only`): OCR, trích xuất, graph, chỉ mục và **danh mục thực thể** được dựng lại.
3. Router nhận ngay số hiệu, loại và năm của văn bản mới ("Luật ... 2023"), địa danh, sản phẩm và chủ thể của nó; không phải sửa router, planner hay tools.
4. Nếu văn bản dùng từ ngữ mới cho một ý định, thêm cue vào `configs/ocop_language.yaml` và một câu hỏi vào bộ đo.

## 6. Bộ đo khi phát triển

Xem `docs/EVALUATION.md`. Quy tắc làm việc: sửa theo bộ phát triển; bộ giữ riêng chỉ xem số tổng sau mỗi vòng; dựng lại graph và chỉ mục sau khi đổi mã trong `ai_core/graph`, `ai_core/retrieval` hay mô-đun trích xuất.
