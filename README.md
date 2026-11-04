# OCOP GraphRAG

Trợ lý tra cứu văn bản về Chương trình mỗi xã một sản phẩm (OCOP). Mỗi câu trả lời được ghép từ các claim ngắn, và mỗi claim trỏ ngược về PDF gốc: văn bản, trang, vùng bằng chứng trên trang và mã SHA-256 của file. Claim nào không kiểm chứng được với nguồn thì không được hiển thị.

Một hệ thống đầu cuối: PDF → dataset OCR → EvidenceUnit → đồ thị tri thức và chỉ mục → định tuyến công cụ → kiểm chứng claim → API FastAPI và giao diện React.

## Tính năng

- **Hỏi đáp có trích dẫn:** hỏi bằng tiếng Việt có dấu hoặc không dấu, hỏi tiếp nhiều lượt ("còn tiện nghi thì sao"). Mỗi ý trả lời kèm trích dẫn; phần tài liệu không trả lời được ghi rõ là "Chưa tìm thấy trong tài liệu".
- **Xem bằng chứng trên PDF:** mở đúng trang gốc, tô đúng vùng được trích và tự cuộn tới vùng đó.
- **Đồ thị dẫn chứng:** từ một trích dẫn, xem tiêu chí đó nằm ở phiếu chấm, phần và nhóm nào, kèm các mức điểm của nó.
- **Bảng tiêu chí chấm điểm:** mọi tiêu chí của 52 phiếu chấm (QĐ26/2026 và QĐ148/2023), lọc theo văn bản và bộ sản phẩm, có điểm tối đa và căn cứ trang, xuất CSV.
- **Danh mục sản phẩm đã công nhận:** sản phẩm trong các quyết định công nhận của Hải Phòng và Huế, kèm căn cứ.
- **Tra cứu có cấu trúc qua đồ thị:** khung điểm từng hạng sao, điểm tối đa của từng tiêu chí, sản phẩm theo địa phương và hạng sao, văn bản thay thế văn bản nào.

## Nguồn dữ liệu

12 văn bản, 583 trang PDF, nằm trong `data/raw/ocop` và được khóa bằng SHA-256 tại `configs/ocop_sources.lock.json`.

| Nhóm | Văn bản |
| --- | --- |
| Khung OCOP hiện hành | 26/2026/QĐ-TTg |
| Khung OCOP đã được thay thế | 148/QĐ-TTg (2023), 1489/QĐ-TTg (2025, sửa đổi 148) |
| Quyết định công nhận | 525/QĐ-UBND Hải Phòng, 797/QĐ-UBND Huế |
| Hướng dẫn địa phương | Phường Thành Sen, Hà Tĩnh |
| Văn bản ngành | Luật An toàn thực phẩm 55/2010/QH12, Nghị định 15/2018/NĐ-CP, Nghị quyết 15/2026/NQ-CP, Nghị định nhãn hàng hóa 43/2017/NĐ-CP và 111/2021/NĐ-CP, Luật Hợp tác xã 17/2023/QH15 |

Khi câu hỏi không nêu năm hay số văn bản, hệ thống ưu tiên văn bản đang có hiệu lực; đoạn trích của văn bản đã được thay thế được gắn nhãn và chỉ dùng cho phần văn bản hiện hành không trả lời được.

## Kiến trúc

**Dựng corpus** (`python tools/cli.py run --build-only`):

1. **OCR**: dự án riêng trong `ocr/` tạo dataset có vị trí từng khối chữ; chữ đã được người duyệt nằm trong `data/ocr-review`.
2. **EvidenceUnit**: chia trang thành điều, khoản, điểm, đoạn văn, bảng; mỗi vùng giữ trang, bbox và dòng chữ của nó.
3. **Trích xuất tri thức**: luật tất định đọc phiếu chấm, tiêu chí, mức điểm, quyết định công nhận; LLM đề xuất thêm thực thể và quy tắc, chỉ được giữ khi có câu trích trong nguồn.
4. **Đồ thị**: mọi node và cạnh qua kiểm định nguồn; chỉ phần đã qua kiểm định được phục vụ.
5. **Chỉ mục**: chunk kèm chuỗi tiêu đề cha, BM25 và vector EmbeddingGemma trong Qdrant.

**Trả lời một câu hỏi**:

1. Phục hồi dấu và viết lại câu hỏi nối tiếp thành câu độc lập.
2. Router chọn công cụ trong danh sách đăng ký, tối đa 5 lần gọi.
3. Truy xuất lai BM25 + vector (RRF), rerank bằng cross-encoder `bge-reranker-v2-m3` (ONNX int8 trên CPU).
4. LLM soạn claim, mỗi claim kèm câu trích nguyên văn.
5. Kiểm chứng từng claim: câu trích phải có trong nguồn; điểm và hạng sao phải gắn đúng bản ghi; số liệu suy ra (khung sao, đếm sản phẩm, điểm tiêu chí) được đối chiếu với đồ thị.

Chi tiết: [ARCHITECTURE](docs/ARCHITECTURE.md).

## Bắt đầu nhanh

Yêu cầu: Python 3.11+, Node.js 22.14+, Git LFS. Docker chỉ cần khi chạy truy xuất hybrid (Qdrant) hoặc Neo4j.

```powershell
git lfs install
git clone https://github.com/nvtanphat/ocop-rag.git
cd ocop-rag
python -m pip install -e ./ocop_contracts -e ./ocr -e ".[agent,persistence,dev]"
copy .env.example .env   # điền endpoint và khóa của LLM tương thích OpenAI
.\run.ps1
```

Mở http://127.0.0.1:8000. `run.ps1` build giao diện rồi chạy API phục vụ cả hai; `-BackendOnly` bỏ bước build khi đã có `frontend/dist`.

Repo đã có sẵn corpus đã dựng (pages, knowledge, graph, index), nên không cần chạy OCR hay trích xuất để dùng thử. Mặc định hệ thống chạy truy xuất sparse (BM25). Để có chất lượng như số đo ở dưới, bật hybrid và rerank:

```powershell
docker compose --profile stores up -d qdrant
$env:OCOP_RETRIEVAL_PROFILE = "hybrid"
$env:OCOP_RERANK = "1"
python tools/cli.py run --build-only --dense
.\run.ps1 -BackendOnly
```

Khi hybrid bật mà Qdrant không chạy, hệ thống tự lùi về BM25 mà không báo lỗi; kiểm tra `GET /api/ocop/health` (`retrieval_profile.ready`). Docker cho toàn bộ hệ thống và xử lý sự cố: [RUNBOOK](docs/RUNBOOK.md).

## Lệnh chính

| Lệnh | Việc |
| --- | --- |
| `python tools/cli.py run --build-only` | Dựng hoặc cập nhật corpus từ dataset OCR |
| `python tools/cli.py run --query "..."` | Trả lời một câu hỏi từ dòng lệnh |
| `python tools/cli.py status` | Kiểm tra corpus có nhất quán và sẵn sàng không |
| `python tools/cli.py graph refresh-index` | Làm mới chỉ mục sau khi đồ thị đổi (tự xuất lại bảng tiêu chí và sản phẩm) |
| `python tools/cli.py graph export-extraction` | Xuất file trích xuất để người duyệt sửa (`data/extraction/entities-relations.md`) |
| `python tools/cli.py graph publish-neo4j` | Đẩy đồ thị đã kiểm định lên Neo4j |

## Cấu hình

| File | Nội dung |
| --- | --- |
| `.env` | Endpoint, khóa và tên model của LLM trả lời (`OCOP_ANSWER_LLM_*`) và LLM trích xuất (`OCOP_EXTRACT_LLM_*`); `OCOP_RETRIEVAL_PROFILE`, `OCOP_RERANK` |
| `configs/ocop_models.yaml` | Model nhúng, reranker, cửa sổ ngữ cảnh LLM |
| `configs/ocop_retrieval.yaml` | Ngân sách truy xuất và prompt: số khối nguồn, token, RRF, rerank |
| `configs/ocop_language.yaml` | Toàn bộ từ vựng tiếng Việt mà router và bộ kiểm chứng dùng |
| `configs/ocop_sources.json` | Danh sách văn bản và loại văn bản |

Chi tiết: [CONFIGURATION](docs/CONFIGURATION.md).

## Kiểm thử và đánh giá

```powershell
python -m pytest -q          # backend và OCR, không gọi mạng hay model thật
Push-Location frontend; npm test; npm run build; Pop-Location
```

Bộ test gồm một test đọc thẳng đồ thị đang phục vụ: mỗi phiếu chấm của văn bản hiện hành phải đủ Phần A, B, C và tổng 100 điểm.

Kết quả hiện tại, chấm theo trang trên corpus đang phục vụ:

| Bộ đo | Kết quả |
| --- | --- |
| Truy xuất, 100 câu | Top-1 75, MRR 0,848, Recall@5 0,99, Recall@10 1,0 |
| Router, 80 câu | Ý định 65/80, phạm vi 77/80, slot 31/32 |

Các bộ citation, multihop, hội thoại và từ chối trả lời cần LLM thật: `python tools/evaluate_gold.py run <bộ> --llm real --out <file>`. Cách đo và đọc kết quả: [EVALUATION](docs/EVALUATION.md).

## Cấu trúc thư mục

```
ai_core/          processing (EvidenceUnit, trích xuất), knowledge, graph, retrieval, orchestration (router, công cụ, kiểm chứng), evaluation
backend/api/      FastAPI: /api/ocop/query, sources, criteria, products, graph/subgraph, PDF và ảnh vùng bằng chứng
frontend/         React + Vite: hỏi đáp, tài liệu, tiêu chí, sản phẩm, đồ thị, trình xem PDF
ocop_contracts/   Model dữ liệu dùng chung (nguồn, vùng, EvidenceUnit)
ocr/              Dự án OCR độc lập
configs/          Cấu hình model, truy xuất, từ vựng, danh sách nguồn
data/raw/ocop/    PDF gốc, không bao giờ sửa
data/processed/   Corpus đã dựng: pages, knowledge, graph, index
data/evaluations/ Bộ câu hỏi gold
tools/            CLI, công cụ đánh giá
tests/            Test backend, fixture dùng chung
docs/             Kiến trúc, vận hành, cấu hình, đánh giá, ADR
```

## Nguyên tắc

- PDF trong `data/raw/ocop` là nguồn bất biến; mọi trích dẫn giữ trang, bbox, mã bằng chứng và SHA-256, không bao giờ tạo giả.
- Ứng viên OCR chưa kiểm chứng luôn tách khỏi dữ kiện đã kiểm chứng; điểm và hạng sao chưa kiểm chứng không được dùng để kết luận.
- Chỉ mục công khai không chứa dữ liệu riêng của đơn vị hay hồ sơ.
- Hệ thống không tự kết luận văn bản nào áp dụng cho một năm hay ngày cụ thể khi chưa có quy tắc hiệu lực đã kiểm định.

Quy tắc sửa mã: [AGENTS.md](AGENTS.md). Thuật ngữ và quyết định thiết kế: [GLOSSARY](GLOSSARY.md), [ADR](docs/adr/README.md).

## Giới hạn

- Hệ thống chỉ trả lời từ 12 văn bản trong corpus. Sản phẩm không được nêu đích danh (ví dụ "bánh tráng") không phân loại được chắc chắn, và câu trả lời sẽ nói rõ điều đó.
- Một số ô điểm trong phiếu QĐ148 bị OCR đọc thiếu hoặc sai số; dữ liệu đã chốt nên giữ nguyên, và các điểm đó không qua kiểm định.
- Câu trả lời của LLM có thể khác nhau giữa các lần hỏi; lớp kiểm chứng chặn claim không có căn cứ chứ không làm câu trả lời giống hệt nhau.

## Dữ liệu trong Git

Repo lưu dataset OCR đã xử lý, file trích xuất có thể sửa, pages, knowledge, index và snapshot đồ thị đang hoạt động. File đồ thị lớn lưu bằng Git LFS: cài Git LFS trước khi clone, hoặc chạy `git lfs install` rồi `git lfs pull` nếu đã clone. Cache, log, snapshot cũ và trọng số model OCR không đưa vào Git. Khi dựng lại đồ thị, thêm thư mục snapshot mới mà manifest tham chiếu bằng `git add -f data/processed/ocop/graph/snapshots/<graph_version>`. Dữ liệu trong Qdrant và Neo4j nằm ngoài repo; dựng lại theo [RUNBOOK](docs/RUNBOOK.md).
