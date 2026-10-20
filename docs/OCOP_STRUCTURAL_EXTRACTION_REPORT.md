# Đối chiếu trích xuất OCOP theo cấu trúc

## Chốt extraction/graph — 2026-10-20

**Chưa đạt toàn bộ tiêu chí chốt.** Đã sửa ba nhóm lỗi được giao, build trên
39 trang OCR có sẵn và xem thủ công đủ 184 mẫu bằng crop PDF. Còn một test cũ
mâu thuẫn yêu cầu mới và precision `RESPONSIBLE_FOR` là 80% (4 đúng/1 sai).
Không sửa kỳ vọng test cũ, không đánh dấu verified, không sửa OCR theo ảnh.

### Phạm vi, lệnh, thời gian và chi phí

- Nhánh `dev`, bắt đầu từ `d3a5b90`; giữ toàn bộ working tree phiên trước.
- Scratchpad lượt này: `C:/Users/PC/AppData/Local/Temp/ocop-final-quality-20261020`.
- Chỉ đọc `pages-part5-final` tại root tạm `ocop-structure-run1`; 39 trang,
  `max_pages=9999`, `allow_partial=True`. Không OCR thêm, không tạo processed
  trong repo, không đổi PDF/registry/lock. Snapshot vẫn partial và không được
  dùng thay corpus đầy đủ trong public API/Agent.
- Lệnh chính: `python <scratchpad>/run_build.py`. Hàm được gọi:

```python
extract_artifacts(root, input_dir=pages_part5_final, output_dir=knowledge,
    max_pages=9999, semantic_client=client, semantic_max_units=500,
    semantic_cache_dir=cache, semantic_workers=4, semantic_gleanings=1)
build_graph(knowledge, graph, allow_partial=True)
```

`client` lấy từ `.env` qua `make_extraction_client()`, model `gpt-6-sol`.
Bản đối chứng gọi cùng hàm với `semantic_client=None`. Không in khóa API.

Cache v8 tìm thấy tại scratchpad phiên
`7b46cf48-425a-4ea3-80b0-286919c6f34a/llm-cache`, dưới thư mục Temp/claude
của repo. Cả 76/76 EvidenceUnit đủ điều kiện (80 chunk) được xử lý, gleanings=1,
workers=4, 0 lỗi, 0 unit bỏ qua do ngân sách. Các response cache được đưa lại
qua schema, căn chỉnh nguyên văn, reconcile và cổng graph hiện tại; không chép
graph v8 làm kết quả mới.

**Chi phí API thực tế phát sinh lượt này: $0.00; số request API: 0.** Adapter trong
script bị chặn gọi mạng khi cache miss. Không có lỗi HTTP 403 và không đổi model.
Lượt build đầu sau sửa: LLM 4,172s, không LLM 3,000s. Lượt cuối:
LLM 3,890s, không LLM 3,641s; số liệu các lượt không đổi. Kiểm tra báo cáo
được ghi lúc 15:27 UTC+7 ngày 20/10/2026, sau đó hoàn tất test/commit.

Cleanup lint xóa 7 import không dùng, trong đó có import ở `contracts.py`;
fingerprint toàn file vì vậy thay đổi dù request và schema không đổi. Để
không gọi lại API, script kiểm tra bằng nhau: SYSTEM, JSON Schema, schema
Pydantic của entity/relation/rule, AST contracts bỏ riêng các dòng import,
và SHA toàn bộ proposer. Chỉ sau các kiểm tra này mới sao response cache
nguyên byte sang namespace mới; lưu ánh xạ old/new key và SHA response trong
`cache_migrations.json`. Cache v8 gốc bất biến. Không đổi chính sách cache
runtime, không tắt kiểm tra bằng chứng hoặc tạo response thay thế.

Lệnh khác đã chạy:

```text
python tools/cli.py --help
python -m pytest -q tests/ocop/test_final_grounding_quality.py
python -m pytest -q tests
python -m ruff check --select F <từng file Python đã sửa và mới thêm>
python <scratchpad>/sample_review.py
python <scratchpad>/contact_sheets.py
python <scratchpad>/final_checks.py
npm run build
npx --no-install tsc --noEmit
git diff --check
```

Script lấy mẫu/render không phân loại đúng/sai. `manual_judgments.json` là
nhãn do trợ lý ghi sau khi thực sự xem từng crop; `final_checks.py` chỉ cộng
các nhãn đó theo loại, không tự chấm nội dung PDF.

### Thay đổi chức năng và hợp đồng

1. `OWNED_BY`: ngoài câu sở hữu trực tiếp vốn có, cho phép một cạnh đã được
   extraction tạo ra dựa vào `RECOGNIZES` và `DECLARED_BY` đã qua kiểm tra,
   cùng một `RecognitionRecord`. Hai liên kết phải sống sót qua kiểm tra
   parent shape. Chứng cứ hàng và ô gộp được giữ; không suy ra cạnh mới từ
   đồng xuất hiện, khác hàng, hay một liên kết bị rejected. Không ghi điểm/sao.
2. `REPLACES`, `AMENDS`, `BASED_ON`: đối chiếu toàn bộ số hiệu đích trong
   registry bằng `contains_document_number`, gắn với từ khóa đúng loại trong
   cùng khoản/câu. Không mượn từ khóa ở khoản/Điều khác; loại câu phủ định,
   điều kiện và số hiệu gần giống. Đây là liên kết văn bản theo nguồn, không
   giải quyết tự động hiệu lực pháp lý theo thời điểm.
3. Giữ `properties.extraction_method` và `llm_enriched_attributes` trong agent
   graph; Graph Builder truyền provenance cả vào `SUPPORTED_BY` sinh từ entity
   LLM. Bốn node được LLM bổ sung thuộc tính giữ metadata enrichment như full
   graph; nguồn từng AttributeClaim vẫn riêng biệt.
4. Không nới `REQUIRES_EVIDENCE`, `Condition/HAS_CONDITION`, `StarLevel/MINIMUM_FOR`.
   Không community detection, không framework/dependency mới.

### Số liệu graph cuối

| Chế độ | Full nodes | Full edges | Rejected | Agent nodes | Agent edges |
|---|---:|---:|---:|---:|---:|
| Không LLM | 897 | 1.968 | 0 | 680 | 1.443 |
| LLM gpt-6-sol, cache | 1.190 | 2.354 | 0 | 732 | 1.517 |

Agent graph có đủ `OWNED_BY=15` (QĐ525), `REPLACES=2`, `AMENDS=1`,
`BASED_ON=1`. Có/không LLM đều nhận thêm đúng 19 cạnh so với cổng trước sửa.
Không có cạnh trùng theo `(relation_type, source_entity_id, target_entity_id)`.
Không mất node/cạnh tất định theo khóa có source, loại, nhãn chuẩn hóa và
hai đầu quan hệ. ID EvidenceUnit node/edge của builder hiện scoped theo
`corpus_version`: profile LLM làm revision khác; không gọi chênh lệch ID thô
giữa hai version là mất thông tin. Đây chưa phải thiết kế ID bất biến xuyên
mọi profile extraction.

Agent graph: **52 node LLM + 71 cạnh nguồn gốc LLM** đều có
`properties.extraction_method="llm_candidate:gpt-6-sol"`; 0 verified,
0 cạnh dẫn nguồn từ node LLM bị mất method. Cả 4 metadata
`llm_enriched_attributes` được giữ. **52 EvidenceType thêm bởi LLM không có
cạnh nghiệp vụ**, chỉ có liên kết chứng cứ; giữ nguyên và ghi nhận coverage
này, không tự nối cạnh để tăng số liệu.

### Phương pháp kiểm bằng ảnh và precision

Seed `20261020`, xáo theo từng source, chọn luân phiên giữa các source.
Chốt trước cỡ mẫu 5 cho mỗi loại hiện diện (hoặc toàn bộ nếu ít hơn 5);
riêng tầng EvidenceType LLM thêm chọn 20. Tổng 184 mẫu: agent 159, LLM thêm
25. Tầng LLM thêm xác định so với bản không LLM bằng loại + nhãn chuẩn hóa;
quan hệ dùng loại + khóa hai đầu, không dựa riêng vào ID version.

Đã SHA-256 cả 12 PDF khớp `configs/ocop_sources.lock.json`, 0 sai lệch.
Render crop quanh bbox có lề 12pt ngang/18pt dọc, 200 DPI, lưu trong
`<scratchpad>/crops`; contact sheets chỉ để xem nhiều crop, không OCR/chấm tự
động. Mỗi mẫu có ID, record ID, source, trang, bbox, SHA và đường dẫn crop trong
`samples.json`. Sau cleanup import làm đổi ID revision, `samples_final.json`
ánh xạ lại đủ 184 assertion sang graph cuối bằng loại, nhãn, source và chứng cứ
page/bbox/quote bằng nhau tuyệt đối; giữ ID trước cleanup, không lấy lại mẫu để
né lỗi. Không chép chữ hoặc điểm/sao đọc từ ảnh vào artifacts.

Precision từng loại = đúng/(đúng+sai), `n=đúng+sai`; KXĐ ghi riêng.
Đây là đối chiếu mẫu nhỏ của 39 trang, không khẳng định độ chính xác toàn corpus.

| Tầng | Loại | n | Đúng | Sai | KXĐ | Precision |
|---|---|---:|---:|---:|---:|---:|
| agent | node: `AdministrativeArea` | 0 | 0 | 0 | 0 | không có mẫu |
| agent | node: `Article` | 5 | 5 | 0 | 0 | 100% |
| agent | node: `Authority` | 5 | 5 | 0 | 0 | 100% |
| agent | node: `CandidateFact` | 0 | 0 | 0 | 0 | không có mẫu |
| agent | node: `Clause` | 5 | 5 | 0 | 0 | 100% |
| agent | node: `Condition` | 0 | 0 | 0 | 0 | không có mẫu |
| agent | node: `Criterion` | 5 | 5 | 0 | 0 | 100% |
| agent | node: `CriterionSheet` | 5 | 5 | 0 | 0 | 100% |
| agent | node: `EvidenceType` | 5 | 5 | 0 | 0 | 100% |
| agent | node: `EvidenceUnit` | 5 | 5 | 0 | 0 | 100% |
| agent | node: `FormTemplate` | 5 | 5 | 0 | 0 | 100% |
| agent | node: `LocalGuidance` | 0 | 0 | 0 | 0 | không có mẫu |
| agent | node: `Mention` | 0 | 0 | 0 | 0 | không có mẫu |
| agent | node: `Organization` | 3 | 3 | 0 | 0 | 100% |
| agent | node: `Point` | 5 | 5 | 0 | 0 | 100% |
| agent | node: `ProcedureStep` | 5 | 5 | 0 | 0 | 100% |
| agent | node: `Product` | 5 | 5 | 0 | 0 | 100% |
| agent | node: `ProductGroup` | 4 | 4 | 0 | 0 | 100% |
| agent | node: `ProductSubgroup` | 2 | 2 | 0 | 0 | 100% |
| agent | node: `RecognitionDecision` | 1 | 1 | 0 | 0 | 100% |
| agent | node: `RecognitionRecord` | 5 | 5 | 0 | 0 | 100% |
| agent | node: `RuleCandidate` | 0 | 0 | 0 | 0 | không có mẫu |
| agent | node: `ScoreOption` | 5 | 5 | 0 | 0 | 100% |
| agent | node: `SourceDocument` | 5 | 5 | 0 | 0 | 100% |
| agent | node: `StarLevel` | 0 | 0 | 0 | 0 | không có mẫu |
| agent | edge: `AMENDS` | 1 | 1 | 0 | 0 | 100% |
| agent | edge: `APPLIES_IN` | 0 | 0 | 0 | 0 | không có mẫu |
| agent | edge: `BASED_ON` | 1 | 1 | 0 | 0 | 100% |
| agent | edge: `CONTAINS` | 0 | 0 | 0 | 0 | không có mẫu |
| agent | edge: `DECLARED_BY` | 5 | 5 | 0 | 0 | 100% |
| agent | edge: `DEFINES_GROUP` | 4 | 4 | 0 | 0 | 100% |
| agent | edge: `HAS_ARTICLE` | 5 | 5 | 0 | 0 | 100% |
| agent | edge: `HAS_CLAUSE` | 5 | 5 | 0 | 0 | 100% |
| agent | edge: `HAS_CONDITION` | 0 | 0 | 0 | 0 | không có mẫu |
| agent | edge: `HAS_CRITERION` | 5 | 5 | 0 | 0 | 100% |
| agent | edge: `HAS_CRITERION_CANDIDATE` | 0 | 0 | 0 | 0 | không có mẫu |
| agent | edge: `HAS_OPTION` | 5 | 5 | 0 | 0 | 100% |
| agent | edge: `HAS_POINT` | 5 | 5 | 0 | 0 | 100% |
| agent | edge: `HAS_RECORD` | 5 | 5 | 0 | 0 | 100% |
| agent | edge: `HAS_SUBCRITERION` | 5 | 5 | 0 | 0 | 100% |
| agent | edge: `HAS_SUBGROUP` | 2 | 2 | 0 | 0 | 100% |
| agent | edge: `LOCATED_IN` | 5 | 5 | 0 | 0 | 100% |
| agent | edge: `MENTIONS` | 0 | 0 | 0 | 0 | không có mẫu |
| agent | edge: `MINIMUM_FOR` | 0 | 0 | 0 | 0 | không có mẫu |
| agent | edge: `OWNED_BY` | 5 | 5 | 0 | 0 | 100% |
| agent | edge: `RECOGNIZES` | 5 | 5 | 0 | 0 | 100% |
| agent | edge: `REFERENCES` | 0 | 0 | 0 | 0 | không có mẫu |
| agent | edge: `REPLACES` | 2 | 2 | 0 | 0 | 100% |
| agent | edge: `REQUIRES_EVIDENCE` | 2 | 2 | 0 | 0 | 100% |
| agent | edge: `RESPONSIBLE_FOR` | 5 | 4 | 1 | 0 | 80% |
| agent | edge: `SUPPORTED_BY` | 5 | 5 | 0 | 0 | 100% |
| agent | edge: `USES_SHEET` | 2 | 2 | 0 | 0 | 100% |
| LLM thêm | edge: `SUPPORTED_BY` | 5 | 5 | 0 | 0 | 100% |
| LLM thêm | node: `EvidenceType` | 20 | 19 | 1 | 0 | 95% |

### Nhật ký mẫu sai/KXĐ và giới hạn còn lại

| Mẫu | Kết quả | Nguồn | Nguyên nhân |
|---|---|---|---|
| `agent:edge:RESPONSIBLE_FOR:05` | Sai | QĐ26 p3 | Parser nhận UBND cấp xã ở mệnh đề phụ “hồ sơ được … đề nghị”, rồi cổng chấp nhận quan hệ với cả câu chính “UBND cấp tỉnh tổ chức đánh giá…”. Cần tách phạm vi predicate theo mệnh đề; còn sai, precision loại 4/5=80%, chưa đạt 90%. |
| `llm_added:node:EvidenceType:18` | Sai | Thanh Sen p2 | OCR ghi “Phụ lục m”, ảnh in “Phụ lục III”; LLM neo nguyên văn giữ lỗi OCR. Không sửa dữ liệu bằng đọc ảnh. Precision tầng 19/20=95%. |

**Không có mẫu KXĐ** trong 184 mẫu đã xem. Các loại có n=0 ghi “không có mẫu”,
không ghi 100%. Loại có n<5 chưa đủ mẫu cho tiêu chí ngưỡng n>=5.

Không dùng kết quả 80% làm lý do nới cổng hoặc bỏ mẫu sai. Lỗi mệnh đề phụ
`RESPONSIBLE_FOR` được bàn giao rõ để xử lý tiếp; không tự ghi verified.
Liên kết loại giấy tờ chưa đầy đủ dù tên EvidenceType được neo đúng nguồn.
Điểm/sao chưa xác minh vẫn bị ngăn khỏi xếp hạng/đánh giá hồ sơ.

### Test đỏ/xanh, kiểm tra cuối và lỗi lệnh

- Ban đầu `test_final_grounding_quality.py`: **7 failed, 8 passed**. Lỗi sở hữu
  trả 0 thay vì 2; năm trường hợp quan hệ văn bản trả `[]`; provenance gây
  `KeyError: 'extraction_method'`.
- Bổ sung test support sau shape check: **1 failed, 29 passed**, tái hiện
  `OWNED_BY` còn tồn tại sau khi RecognitionRecord mất cha; đã sửa.
- Bổ sung test Graph Builder cho cạnh dẫn nguồn LLM: **1 failed, 30 deselected**,
  `KeyError: 'extraction_method'`; đã sửa.
- Test mới sau sửa: **34 passed**. Có test âm tính khác hàng, link rejected,
  mất HAS_RECORD, khác khoản/Điều, không/nếu/trường hợp và số hiệu gần giống
  cho cả ba loại quan hệ văn bản.
- Toàn bộ suite cuối: **1 failed, 621 passed, 1 skipped, 3 warnings in 30.18s**; pytest exit=1, không che lỗi.
- Ruff `--select F` sạch trên toàn bộ file Python thay đổi/mới; frontend Vite build đạt (1.750 modules, 10,88s), TypeScript `--noEmit` đạt; `git diff --check` đạt.

**Test cũ mâu thuẫn yêu cầu mới (giữ nguyên kỳ vọng):**
`tests/ocop/test_operational_graph.py:171`,
`test_recognition_table_links_are_checked_but_scores_stay_out` có:

```text
assert not any(e['relation_type']=='OWNED_BY' for e in edges)
E       assert not True
```

Fixture có hai hàng công nhận, ô chủ thể rowspan rõ và hai link đã được chấp
nhận; đúng trường hợp yêu cầu mới phải cho OWNED_BY. Không thêm xfail/skip,
không đổi assertion, không đặc cách source/fixture để làm test xanh. Do đó
tiêu chí “toàn bộ test đạt” **chưa đạt**, dù các test mới và các test khác đạt.

Lỗi chẩn đoán/lệnh đã gặp, giữ nguyên thông báo chính:

```text
rg: C:/Users/PC/AppData/Local/Temp\LiveUpdateAPI: Access is denied. (os error 5)
rg: docs/adr: IO error for operation on docs/adr: The system cannot find the file specified. (os error 2)
UnicodeDecodeError: 'charmap' codec can't decode byte 0x81 in position 247: character maps to <undefined>
unable to locate image at `C:\Users\PC\AppData\Local\Temp\ocop-final-quality-20261020\sheets\agent_edge_DEFINES_GROUP_2.png`: The system cannot find the file specified. (os error 2)
Found 7 errors.
[*] 7 fixable with the `--fix` option.
```

Đã đổi đọc JSON sang UTF-8; dùng index contact sheets thay vì giả định loại nào
cũng có tấm thứ hai; nhóm DEFINES_GROUP thực tế chỉ có 4 mẫu. Thiếu docs/adr
không bị thay bằng tài liệu giả. Bảy lỗi lint là import không dùng, đã dọn.
Không có lỗi API/HTTP trong lượt này.

### Kết luận từng tiêu chí

| Tiêu chí | Kết quả |
|---|---|
| Toàn bộ test đạt | **Chưa đạt**: một test cũ mâu thuẫn chính sách OWNED_BY mới; giữ nguyên |
| Ruff F trên mọi file Python thay đổi | **Đạt** |
| rejected=0, 0 cạnh trùng, không mất nội dung tất định | **Đạt** theo khóa ngữ nghĩa có scope nguồn; ID vẫn scoped corpus_version |
| Đủ 15 OWNED_BY và 4 quan hệ văn bản | **Đạt** |
| Precision >=90% cho mọi loại n>=5 | **Chưa đạt**: RESPONSIBLE_FOR 80%; còn lại đạt trên mẫu |
| Provenance LLM đầy đủ, không verified | **Đạt**: 52 nodes/71 edges, 0 thiếu method/verified |
| Không khóa API được commit, .env không stage | **Đạt**: quét literal `sk-` và đối chiếu khóa thực từ môi trường; chỉ có giá trị giả trong test, không có khóa thật. `.env` không stage. |

### Nhật ký toàn bộ mẫu đã xem

| Mẫu | Record ID cuối | Nguồn/trang crop | Evidence ID chính | bbox chính (pt) | SHA-256 nguồn chính | Nhãn đối chiếu | Kết quả | Phân loại lỗi | Lý do |
|---|---|---|---|---|---|---|---|---|---|
| agent:edge:AMENDS:01 | ocop:kg_edge:894afdd6be684578a3a8b96c | VN.OCOP.QD1489.2025 p1; VN.HAIPHONG.QD525.2026 p1 | ocop:evidence:c31bafd621828ae6107aad46 | [89.26, 638.16, 538.18, 776.64] | c8feaadc85cece82579b90aaf7b5899920630f1546d08ddd3860c75cb388e4b7 | 1489/QĐ-TTg -> 148/QĐ-TTg | Đúng | — | QĐ1489 Điều 1 ghi sửa đổi, bổ sung QĐ148. |
| agent:edge:BASED_ON:01 | ocop:kg_edge:93918f3f6bc2fe65491e21d0 | VN.HAIPHONG.QD525.2026 p1; VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:97bfa6ba30b873074ba6cc10 | [85.1, 57.33, 543.6, 483.58] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | 525/QĐ-UBND -> 148/QĐ-TTg | Đúng | — | QĐ525 p1 có dòng Căn cứ Quyết định 148/QĐ-TTg. |
| agent:edge:DECLARED_BY:01 | ocop:kg_edge:e8c47465351b14a2eeb4c7a1 | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 412.99, 557.27, 577.78] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Dòng 5 — VN.HAIPHONG.QD525.2026 -> Công ty Trách nhiệm hữu hạn Thủy Sản Song Hải | Đúng | — | QĐ525 p3: đối chiếu STT và ô tổ chức/cá nhân gộp cùng hàng; không dùng điểm/sao. |
| agent:edge:DECLARED_BY:02 | ocop:kg_edge:6611df5ea138339313c4c713 | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 249.53, 557.27, 304.01] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Dòng 2 — VN.HAIPHONG.QD525.2026 -> Công ty Trách nhiệm hữu hạn Quang Hải | Đúng | — | QĐ525 p3: đối chiếu STT và ô tổ chức/cá nhân gộp cùng hàng; không dùng điểm/sao. |
| agent:edge:DECLARED_BY:03 | ocop:kg_edge:d2da3e2a18bcdfa1006bc430 | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 742.44, 557.27, 777.99] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Dòng 15 — VN.HAIPHONG.QD525.2026 -> Hợp tác xã sản xuất kinh doanh dịch vụ nông nghiệp Thụy Hương | Đúng | — | QĐ525 p3: đối chiếu STT và ô tổ chức/cá nhân gộp cùng hàng; không dùng điểm/sao. |
| agent:edge:DECLARED_BY:04 | ocop:kg_edge:8a6bdd0b38d60d6b44ff03e3 | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 635.98, 557.27, 671.38] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Dòng 12 — VN.HAIPHONG.QD525.2026 -> Hợp tác xã sản xuất kinh doanh dịch vụ nông nghiệp Thụy Hương | Đúng | — | QĐ525 p3: đối chiếu STT và ô tổ chức/cá nhân gộp cùng hàng; không dùng điểm/sao. |
| agent:edge:DECLARED_BY:05 | ocop:kg_edge:2d76cf30d1b9365760f933a5 | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 577.78, 557.27, 777.99] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Dòng 10 — VN.HAIPHONG.QD525.2026 -> Hợp tác xã sản xuất kinh doanh dịch vụ nông nghiệp Thụy Hương | Đúng | — | QĐ525 p3: đối chiếu STT và ô tổ chức/cá nhân gộp cùng hàng; không dùng điểm/sao. |
| agent:edge:DEFINES_GROUP:01 | ocop:kg_edge:38b71d1927277168667639bf | VN.OCOP.QD26.2026 p2; VN.HATINH.THANHSEN.2026 p1 | ocop:evidence:30041b9784e22e006e2132ab | [98.28, 147.78, 546.44, 243.32] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 26/2026/QĐ-TTg -> thực phẩm | Đúng | — | Đối chiếu danh mục nhóm QĐ26 Điều 2 và tiêu đề/phần A-B-C của phiếu tương ứng. |
| agent:edge:DEFINES_GROUP:02 | ocop:kg_edge:fb116d7c91fa21f511dc2975 | VN.OCOP.QD26.2026 p2; VN.HATINH.THANHSEN.2026 p1 | ocop:evidence:30041b9784e22e006e2132ab | [98.14, 219.96, 546.44, 258.69] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 26/2026/QĐ-TTg -> hàng thủ công mỹ nghệ | Đúng | — | Đối chiếu danh mục nhóm QĐ26 Điều 2 và tiêu đề/phần A-B-C của phiếu tương ứng. |
| agent:edge:DEFINES_GROUP:03 | ocop:kg_edge:43d1329c3839f04844036d34 | VN.OCOP.QD26.2026 p2; VN.HATINH.THANHSEN.2026 p1 | ocop:evidence:30041b9784e22e006e2132ab | [97.52, 241.62, 546.16, 275.48] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 26/2026/QĐ-TTg -> dịch vụ du lịch cộng đồng, du lịch sinh thái và điểm du lịch | Đúng | — | Đối chiếu danh mục nhóm QĐ26 Điều 2 và tiêu đề/phần A-B-C của phiếu tương ứng. |
| agent:edge:DEFINES_GROUP:04 | ocop:kg_edge:7b7dcd78f2ceda043379e298 | VN.OCOP.QD26.2026 p2; VN.HATINH.THANHSEN.2026 p1 | ocop:evidence:30041b9784e22e006e2132ab | [98.14, 241.62, 544.86, 258.69] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 26/2026/QĐ-TTg -> sinh vật cảnh | Đúng | — | Đối chiếu danh mục nhóm QĐ26 Điều 2 và tiêu đề/phần A-B-C của phiếu tương ứng. |
| agent:edge:HAS_ARTICLE:01 | ocop:kg_edge:c3a1679619fd55b3ce05f342 | VN.OCOP.QD26.2026 p13; VN.HATINH.THANHSEN.2026 p1 | ocop:evidence:6d23038cd7b39d2e6b133511 | [100.32, 130.54, 560.4, 301.4] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 26/2026/QĐ-TTg -> Điều 11. Hiệu lực thi hành | Đúng | — | Ảnh giữ đúng số Điều/khoản và văn bản cha; nội dung nằm trong phạm vi điều tương ứng. |
| agent:edge:HAS_ARTICLE:02 | ocop:kg_edge:150a2bd2c66fc1a18411b410 | VN.OCOP.QD1489.2025 p2; VN.HAIPHONG.QD525.2026 p1 | ocop:evidence:cf573e133856761ebef38656 | [88.05, 126.47, 540.06, 215.26] | c8feaadc85cece82579b90aaf7b5899920630f1546d08ddd3860c75cb388e4b7 | 1489/QĐ-TTg -> Điều 2. Quyết định này có hiệu lực kể từ ngày ký ban hành | Đúng | — | Ảnh giữ đúng số Điều/khoản và văn bản cha; nội dung nằm trong phạm vi điều tương ứng. |
| agent:edge:HAS_ARTICLE:03 | ocop:kg_edge:5ed72bc50866969fe84cf6a1 | VN.ND.43.2017 p1 | ocop:evidence:4131fdc9431ad985775c0040 | [64.08, 478.41, 534.88, 762.51] | d5771b9da7a7f898b7eeef23a21966c85a49c57572e9c71788f24b7f04f0cbdb | 43/2017/NĐ-CP -> Điều 1. Phạm vi điều chỉnh | Đúng | — | Ảnh giữ đúng số Điều/khoản và văn bản cha; nội dung nằm trong phạm vi điều tương ứng. |
| agent:edge:HAS_ARTICLE:04 | ocop:kg_edge:a5360285f8e256d848f4a666 | VN.ND.15.2018 p5; VN.ND.15.2018 p4 | ocop:evidence:d9bfb8b45d531adb32b77c6b | [64.08, 358.29, 534.89, 757.83] | 9dec41b53cb1568a50fc3a98b41a95df2e6595341e5dd8dcf5926d22dde4b1b2 | 15/2018/NĐ-CP -> Điều 5. Hồ sơ, trình tự tự công bố sản phẩm | Đúng | — | Ảnh giữ đúng số Điều/khoản và văn bản cha; nội dung nằm trong phạm vi điều tương ứng. |
| agent:edge:HAS_ARTICLE:05 | ocop:kg_edge:2bed4b395d091b1d61a9e132 | VN.HAIPHONG.QD525.2026 p1; VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:fdf1a60244519f15dbdb72e8 | [85.1, 600.04, 542.43, 651.61] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | 525/QĐ-UBND -> Điều 2. Giấy chứng nhận sản phẩm OCOP cấp thành phố có hiệu lực 36 tháng | Đúng | — | Ảnh giữ đúng số Điều/khoản và văn bản cha; nội dung nằm trong phạm vi điều tương ứng. |
| agent:edge:HAS_CLAUSE:01 | ocop:kg_edge:c88d50f9803042e0213e6e17 | VN.ND.43.2017 p1 | ocop:evidence:4131fdc9431ad985775c0040 | [64.08, 537.09, 534.88, 762.51] | d5771b9da7a7f898b7eeef23a21966c85a49c57572e9c71788f24b7f04f0cbdb | Điều 1. Phạm vi điều chỉnh -> 2. Những hàng hóa sau đây không thuộc phạm vi điều chỉnh của Nghị định này: a) Bất động sản; b) Hàng hóa tạm nhập tái xuất; hàng hóa tạm nhập để tham gia hội chợ, triển lãm sau đó tái xuất; hàng hóa quá cảnh, hàng hóa chuyển khẩu; hàng hóa trung chuy | Đúng | — | Ảnh giữ đúng số Điều/khoản và văn bản cha; nội dung nằm trong phạm vi điều tương ứng. |
| agent:edge:HAS_CLAUSE:02 | ocop:kg_edge:9ad5704064d7b81dea70c2c9 | VN.OCOP.QD1489.2025 p1; VN.OCOP.QD1489.2025 p2 | ocop:evidence:c31bafd621828ae6107aad46 | [89.26, 713.04, 538.18, 776.64] | c8feaadc85cece82579b90aaf7b5899920630f1546d08ddd3860c75cb388e4b7 | Điều 1. Sửa đổi, bổ sung một số nội dung Quyết định số 148/QĐ-TTg ngày 24 tháng 02 năm 2023 của Thủ tướng Chính phủ về việc ban hành bộ tiêu chí và quy trình đánh giá, phân hạng sản phẩm chương trình mỗi xã một sản phẩm (OCOP) như sau: -> 1. Sửa đổi, bổ sung khoản 1, Điều 1.?1. Bộ tiêu chí và quy trình đánh giá, phân hạng sản phẩm Chương trình mỗi xã một sản phẩm (sau đây gọi tắt là Bộ tiêu chí OCOP) là căn cứ để đánh giá, phân hạng sản phẩm tham gia chương trình OCOP giai đoạn 2021 - | Đúng | — | Ảnh giữ đúng số Điều/khoản và văn bản cha; nội dung nằm trong phạm vi điều tương ứng. |
| agent:edge:HAS_CLAUSE:03 | ocop:kg_edge:e7d0f25b7d88682f05da78ac | VN.NQ.15.2026 p2 | ocop:evidence:8966789549ea1e50bb267540 | [85.1, 93.83, 595.32, 443.38] | f76f585b4a3066bf9ae1511deff62690bf03fc88eca3eeddfc1fb922543689ec | Điều 3. Trách nhiệm tổ chức thực hiện -> 1. Các Bộ: Y tế, Công Thương, Nông nghiệp và Môi trường a) Chủ động hướng dẫn tổ chức triển khai thi hành Nghị quyết này theo lĩnh vực được phân công quản lý. b) Tăng cường triển khai kế hoạch kiểm tra, theo dõi, giám sát định kỳ, đột xuất, giám sát, | Đúng | — | Ảnh giữ đúng số Điều/khoản và văn bản cha; nội dung nằm trong phạm vi điều tương ứng. |
| agent:edge:HAS_CLAUSE:04 | ocop:kg_edge:1b38bee918716082591d1e4e | VN.OCOP.QD26.2026 p2; VN.OCOP.QD26.2026 p3 | ocop:evidence:96e82ce99290b78a5231c114 | [95.77, 696.42, 541.19, 727.72] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Điều 3. Bộ tiêu chí đánh giá, phân hạng sản phẩm OCOP -> 2. Tiêu chí đánh giá từng nhóm, phân nhóm sản phẩm tại phụ lục II ban hành kèm theo Quyết định này | Đúng | — | Ảnh giữ đúng số Điều/khoản và văn bản cha; nội dung nằm trong phạm vi điều tương ứng. |
| agent:edge:HAS_CLAUSE:05 | ocop:kg_edge:ff5830bc094788ad9a741254 | VN.ND.15.2018 p4 | ocop:evidence:9111c11414e4a0ac48a7dc1a | [64.08, 170.37, 534.87, 265.83] | 9dec41b53cb1568a50fc3a98b41a95df2e6595341e5dd8dcf5926d22dde4b1b2 | Điều 4. Tự công bố sản phẩm -> 1. Tổ chức, cá nhân sản xuất, kinh doanh thực phẩm thực hiện tự công bố thực phẩm đã qua chế biến bao gói sẵn, phụ gia thực phẩm, chất hỗ trợ chế biến thực phẩm, dụng cụ chứa đựng thực phẩm, vật liệu bao gói tiếp xúc trực tiếp với thực phẩm (sau đây  | Đúng | — | Ảnh giữ đúng số Điều/khoản và văn bản cha; nội dung nằm trong phạm vi điều tương ứng. |
| agent:edge:HAS_CRITERION:01 | ocop:kg_edge:5e93a68a086997156c36953f | VN.OCOP.QD26.2026 p18; VN.OCOP.QD26.2026 p17 | ocop:evidence:3f323c76931c441bfe7c9ace | [87.24, 273.95, 560.91, 305.01] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Bộ sản phẩm: rau, củ, quả, hạt tươi -> Phần A: SẢN PHẨM VÀ SỨC MẠNH CỦA CỘNG ĐỒNG (40 Điểm) | Đúng | — | Đối chiếu danh mục nhóm QĐ26 Điều 2 và tiêu đề/phần A-B-C của phiếu tương ứng. |
| agent:edge:HAS_CRITERION:02 | ocop:kg_edge:5208d94de3e4c1c560ce87de | VN.OCOP.QD26.2026 p30; VN.OCOP.QD26.2026 p17 | ocop:evidence:df121c3e9c4a4960293962e1 | [84.27, 364.91, 558.75, 406.7] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Bộ sản phẩm: gạo, ngũ cốc, hạt sơ chế khác -> Phần B: KHẢ NĂNG TIẾP THỊ (25 Điểm) | Đúng | — | Đối chiếu danh mục nhóm QĐ26 Điều 2 và tiêu đề/phần A-B-C của phiếu tương ứng. |
| agent:edge:HAS_CRITERION:03 | ocop:kg_edge:cb77276ce28048b8ef6c883c | VN.OCOP.QD26.2026 p31; VN.OCOP.QD26.2026 p17 | ocop:evidence:dbe316e0e3dd7c3d5fedff17 | [87.84, 411.06, 560.64, 437.7] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Bộ sản phẩm: gạo, ngũ cốc, hạt sơ chế khác -> Phần C: CHẤT LƯỢNG SẢN PHẨM (35 Điểm) | Đúng | — | Đối chiếu danh mục nhóm QĐ26 Điều 2 và tiêu đề/phần A-B-C của phiếu tương ứng. |
| agent:edge:HAS_CRITERION:04 | ocop:kg_edge:9b739ac79d1f2bbe629c7011 | VN.OCOP.QD26.2026 p28; VN.OCOP.QD26.2026 p17 | ocop:evidence:16d3307e324aa78461e0a642 | [86.31, 295.14, 560.15, 332.69] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Bộ sản phẩm: gạo, ngũ cốc, hạt sơ chế khác -> Phần A: SẢN PHẨM VÀ SỨC MẠNH CỦA CỘNG ĐỒNG (40 ĐIỂM) | Đúng | — | Đối chiếu danh mục nhóm QĐ26 Điều 2 và tiêu đề/phần A-B-C của phiếu tương ứng. |
| agent:edge:HAS_CRITERION:05 | ocop:kg_edge:232005c26c94e7a14e3ecd12 | VN.OCOP.QD26.2026 p20; VN.OCOP.QD26.2026 p17 | ocop:evidence:29628eacdb3bb6cb2dbc9f2a | [87.59, 377.77, 561.0, 416.1] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Bộ sản phẩm: rau, củ, quả, hạt tươi -> Phần B: KHẢ NĂNG TIẾP THỊ (25 Điểm) | Đúng | — | Đối chiếu danh mục nhóm QĐ26 Điều 2 và tiêu đề/phần A-B-C của phiếu tương ứng. |
| agent:edge:HAS_OPTION:01 | ocop:kg_edge:a61dedca8573a17e58f7ecb1 | VN.OCOP.QD26.2026 p21 | ocop:evidence:ef88383f02602cfedd628a3e | [92.16, 654.61, 564.07, 673.08] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 6.3. Mùi/vị -> Trung bình | Đúng | — | Phương án nằm trực tiếp dưới tiêu chí tương ứng trên ảnh; không xác nhận giá trị điểm/sao. |
| agent:edge:HAS_OPTION:02 | ocop:kg_edge:21e6f278cd00e0904b9175d4 | VN.OCOP.QD26.2026 p21; VN.OCOP.QD26.2026 p22 | ocop:evidence:ef88383f02602cfedd628a3e | [89.61, 341.24, 561.54, 362.83] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 5.3. Trí tuệ/bản sắc địa phương Yêu cầu: Nội dung câu chuyện sản phẩm OCOP phải thể hiện rõ nguồn gốc, tài nguyên bản địa, văn hóa, bản sắc địa phương, giá trị đặc trưng của sản phẩm, có tính truyền cảm và thuyết phục -> Có câu chuyện riêng, gắn với nguồn gốc xuất xứ sản phẩm | Đúng | — | Phương án nằm trực tiếp dưới tiêu chí tương ứng trên ảnh; không xác nhận giá trị điểm/sao. |
| agent:edge:HAS_OPTION:03 | ocop:kg_edge:de2f2429a4062b232ba0d106 | VN.OCOP.QD26.2026 p21 | ocop:evidence:ef88383f02602cfedd628a3e | [87.66, 102.5, 559.58, 120.97] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 5.1. Câu chuyện sản phẩm -> Không có câu chuyện sản phẩm | Đúng | — | Phương án nằm trực tiếp dưới tiêu chí tương ứng trên ảnh; không xác nhận giá trị điểm/sao. |
| agent:edge:HAS_OPTION:04 | ocop:kg_edge:7d8f39af26b6dd98ceca4df4 | VN.OCOP.QD26.2026 p19 | ocop:evidence:444cd79b9a07b0152dd919f5 | [90.64, 448.84, 561.38, 477.76] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 2.3. Phong cách, ghi nhãn hàng hóa -> Ghi nhãn hàng hóa đầy đủ, đúng quy định và thể hiện được thông điệp câu chuyện sản phẩm (hình ảnh hoặc lời giới thiệu) | Đúng | — | Phương án nằm trực tiếp dưới tiêu chí tương ứng trên ảnh; không xác nhận giá trị điểm/sao. |
| agent:edge:HAS_OPTION:05 | ocop:kg_edge:3a0318ddf22b754b1f38e0cf | VN.OCOP.QD26.2026 p31 | ocop:evidence:dbe316e0e3dd7c3d5fedff17 | [87.84, 107.98, 560.64, 123.1] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 5.1. Câu chuyện sản phẩm -> Không có câu chuyện sản phẩm | Đúng | — | Phương án nằm trực tiếp dưới tiêu chí tương ứng trên ảnh; không xác nhận giá trị điểm/sao. |
| agent:edge:HAS_POINT:01 | ocop:kg_edge:d6b34c7c77d9009fd36e282b | VN.OCOP.QD26.2026 p7; VN.OCOP.QD26.2026 p6 | ocop:evidence:45dc7d909d6e7c11ef1a770f | [97.2, 345.55, 546.24, 394.5] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 3. Tổ chức đánh giá, phân hạng sản phẩm OCOP cấp tỉnh: a) UBND cấp tỉnh giao cơ quan thám mựu quản lý OCOP cấp tỉnh tiếp nhận hồ sơ đề nghị đánh giá, phân hạng sản phẩm OCOP từ UBND cấp xã cơ quan tham mưu quản lý ocốp cấp tỉnh kiểm tra thành phần, n -> g) UBND cấp tỉnh giao cơ quan tham mưu quản lý OCOP cấp tỉnh thông báo bằng văn bản về kết quả đánh giá, phân hạng cho UBND cấp xã và các chủ thể OCOP | Đúng | — | Đối chiếu thứ bậc số/điểm trên ảnh; đúng khoản cha hoặc mục tiêu chí cha trong cùng phiếu. |
| agent:edge:HAS_POINT:02 | ocop:kg_edge:ada6db929e7c41df9619941d | VN.NQ.15.2026 p2 | ocop:evidence:8966789549ea1e50bb267540 | [85.1, 153.83, 586.92, 233.33] | f76f585b4a3066bf9ae1511deff62690bf03fc88eca3eeddfc1fb922543689ec | 1. Các Bộ: Y tế, Công Thương, Nông nghiệp và Môi trường a) Chủ động hướng dẫn tổ chức triển khai thi hành Nghị quyết này theo lĩnh vực được phân công quản lý. b) Tăng cường triển khai kế hoạch kiểm tra, theo dõi, giám sát định kỳ, đột xuất, giám sát, -> b) Tăng cường triển khai kế hoạch kiểm tra, theo dõi, giám sát định kỳ, đột xuất, giám sát, hướng dẫn, xử lý vi phạm về an toàn thực phẩm trong quá trình sản xuất, xuất khẩu, nhập khẩu, kinh doanh thực phẩm, các nhiệm vụ đã được phân công và các nhiệ | Đúng | — | Đối chiếu thứ bậc số/điểm trên ảnh; đúng khoản cha hoặc mục tiêu chí cha trong cùng phiếu. |
| agent:edge:HAS_POINT:03 | ocop:kg_edge:ea984ec8632098770a733112 | VN.ND.43.2017 p1 | ocop:evidence:4131fdc9431ad985775c0040 | [86.76, 637.65, 291.9, 653.19] | d5771b9da7a7f898b7eeef23a21966c85a49c57572e9c71788f24b7f04f0cbdb | 2. Những hàng hóa sau đây không thuộc phạm vi điều chỉnh của Nghị định này: a) Bất động sản; b) Hàng hóa tạm nhập tái xuất; hàng hóa tạm nhập để tham gia hội chợ, triển lãm sau đó tái xuất; hàng hóa quá cảnh, hàng hóa chuyển khẩu; hàng hóa trung chuy -> d) Hàng hóa bị tịch thu bán đấu giá; | Đúng | — | Đối chiếu thứ bậc số/điểm trên ảnh; đúng khoản cha hoặc mục tiêu chí cha trong cùng phiếu. |
| agent:edge:HAS_POINT:04 | ocop:kg_edge:a73b972056f8eb9898b35fed | VN.ND.15.2018 p4; VN.ND.15.2018 p5 | ocop:evidence:d9bfb8b45d531adb32b77c6b | [64.08, 618.33, 534.89, 713.79] | 9dec41b53cb1568a50fc3a98b41a95df2e6595341e5dd8dcf5926d22dde4b1b2 | 2. Việc tự công bố sản phẩm được thực hiện theo trình tự như sau: a) Tổ chức, cá nhân tự công bố sản phẩm trên phương tiện thông tin đại chúng hoặc trang thông tin điện tử của mình hoặc niêm yết công khai tại trụ sở của tổ chức, cá nhân và nộp 01 (mộ -> a) Tổ chức, cá nhân tự công bố sản phẩm trên phương tiện thông tin đại chúng hoặc trang thông tin điện tử của mình hoặc niêm yết công khai tại trụ sở của tổ chức, cá nhân và nộp 01 (một) bản qua đường bưu điện hoặc trực tiếp đến cơ quan quản lý nhà n | Đúng | — | Đối chiếu thứ bậc số/điểm trên ảnh; đúng khoản cha hoặc mục tiêu chí cha trong cùng phiếu. |
| agent:edge:HAS_POINT:05 | ocop:kg_edge:620896c8490f80a4d49e684d | VN.OCOP.QD26.2026 p9; VN.OCOP.QD26.2026 p8 | ocop:evidence:3ddb83a8adea2c25791c99a6 | [97.44, 725.35, 544.8, 760.14] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 6. Khi hết thời hạn 36 tháng của giấy chứng nhận, trường hợp chủ thể OCOP đề nghị đánh giá, phân hạng lại sản phẩm thì thực hiện như sau: a) Chủ thể OCOP chuẩn bị hồ sơ sản phẩm theo quy định tại điểm c khoản 1 Điều 6 Quyết định này, nộp hồ sơ theo q -> g) Thời gian tổ chức đánh giá, phân hạng lại sản phẩm OCOP không quá 45 ngày kể từ ngày nhận đủ hồ sơ đề nghị của UBND cấp xã hoặc UBND cấp tỉnh. | Đúng | — | Đối chiếu thứ bậc số/điểm trên ảnh; đúng khoản cha hoặc mục tiêu chí cha trong cùng phiếu. |
| agent:edge:HAS_RECORD:01 | ocop:kg_edge:4597c8ce44f31bc857616e18 | VN.HAIPHONG.QD525.2026 p3; VN.HAIPHONG.QD525.2026 p1 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 671.38, 557.27, 706.92] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | 525/QĐ-UBND -> Dòng 13 — VN.HAIPHONG.QD525.2026 | Đúng | — | QĐ525 p3: đúng số thứ tự, sản phẩm và phạm vi phụ lục quyết định. |
| agent:edge:HAS_RECORD:02 | ocop:kg_edge:883a02cff1eaf6459242f483 | VN.HAIPHONG.QD525.2026 p3; VN.HAIPHONG.QD525.2026 p1 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 542.26, 557.27, 577.78] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | 525/QĐ-UBND -> Dòng 9 — VN.HAIPHONG.QD525.2026 | Đúng | — | QĐ525 p3: đúng số thứ tự, sản phẩm và phạm vi phụ lục quyết định. |
| agent:edge:HAS_RECORD:03 | ocop:kg_edge:05f1f8fb07465c538a2372f4 | VN.HAIPHONG.QD525.2026 p3; VN.HAIPHONG.QD525.2026 p1 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 194.9, 557.27, 412.99] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | 525/QĐ-UBND -> Dòng 1 — VN.HAIPHONG.QD525.2026 | Đúng | — | QĐ525 p3: đúng số thứ tự, sản phẩm và phạm vi phụ lục quyết định. |
| agent:edge:HAS_RECORD:04 | ocop:kg_edge:744ecc602e20f6656a2e0da4 | VN.HAIPHONG.QD525.2026 p3; VN.HAIPHONG.QD525.2026 p1 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 304.01, 557.27, 358.49] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | 525/QĐ-UBND -> Dòng 3 — VN.HAIPHONG.QD525.2026 | Đúng | — | QĐ525 p3: đúng số thứ tự, sản phẩm và phạm vi phụ lục quyết định. |
| agent:edge:HAS_RECORD:05 | ocop:kg_edge:6c056497482038c8f795c648 | VN.HAIPHONG.QD525.2026 p3; VN.HAIPHONG.QD525.2026 p1 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 412.99, 557.27, 577.78] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | 525/QĐ-UBND -> Dòng 5 — VN.HAIPHONG.QD525.2026 | Đúng | — | QĐ525 p3: đúng số thứ tự, sản phẩm và phạm vi phụ lục quyết định. |
| agent:edge:HAS_SUBCRITERION:01 | ocop:kg_edge:2229dbb999f6db7ea5fde3ab | VN.OCOP.QD26.2026 p20 | ocop:evidence:29628eacdb3bb6cb2dbc9f2a | [90.53, 611.22, 563.72, 631.81] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 4. TIẾP THỊ -> 4.3. Quảng bá sản phẩm | Đúng | — | Đối chiếu thứ bậc số/điểm trên ảnh; đúng khoản cha hoặc mục tiêu chí cha trong cùng phiếu. |
| agent:edge:HAS_SUBCRITERION:02 | ocop:kg_edge:335d6e5a86293504abf33b42 | VN.OCOP.QD26.2026 p21 | ocop:evidence:ef88383f02602cfedd628a3e | [91.92, 625.58, 563.83, 644.06] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 6. CHỈ TIÊU CẢM QUAN -> 6.3. Mùi/vị | Đúng | — | Đối chiếu thứ bậc số/điểm trên ảnh; đúng khoản cha hoặc mục tiêu chí cha trong cùng phiếu. |
| agent:edge:HAS_SUBCRITERION:03 | ocop:kg_edge:c56afd9b632c9fa69a4020b9 | VN.OCOP.QD26.2026 p32; VN.OCOP.QD26.2026 p31 | ocop:evidence:a66f8c06456e2ec25f24ed43 | [88.18, 485.19, 561.29, 519.33] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Phần C: CHẤT LƯỢNG SẢN PHẨM (35 Điểm) -> 11. HƯỚNG DẪN SỬ DỤNG ĐỂ ĐẢM BẢO SẢN PHẨM CÓ CHẤT LƯỢNG TỐT NHẤT CHO NGƯỜI TIÊU DÙNG | Đúng | — | Đối chiếu thứ bậc số/điểm trên ảnh; đúng khoản cha hoặc mục tiêu chí cha trong cùng phiếu. |
| agent:edge:HAS_SUBCRITERION:04 | ocop:kg_edge:14faaf507020e12034e59598 | VN.OCOP.QD26.2026 p31 | ocop:evidence:dbe316e0e3dd7c3d5fedff17 | [87.84, 629.19, 560.64, 644.79] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 6. CHỈ TIÊU CẢM QUAN -> 6.3. Màu sắc | Đúng | — | Đối chiếu thứ bậc số/điểm trên ảnh; đúng khoản cha hoặc mục tiêu chí cha trong cùng phiếu. |
| agent:edge:HAS_SUBCRITERION:05 | ocop:kg_edge:f9062a815ae8df1e9c3071d8 | VN.OCOP.QD26.2026 p31; VN.OCOP.QD26.2026 p30 | ocop:evidence:dbe316e0e3dd7c3d5fedff17 | [87.84, 205.17, 560.64, 219.57] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 5. CÂU CHUYỆN SẢN PHẨM -> 5.2. Cấu trúc câu chuyện sản phẩm | Đúng | — | Đối chiếu thứ bậc số/điểm trên ảnh; đúng khoản cha hoặc mục tiêu chí cha trong cùng phiếu. |
| agent:edge:HAS_SUBGROUP:01 | ocop:kg_edge:7dd4f78c6c373a9c92d2b99a | VN.OCOP.QD26.2026 p28; VN.OCOP.QD26.2026 p2 | ocop:evidence:b9b5e54287f1a7d594d39def | [87.29, 77.64, 550.52, 270.02] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | thực phẩm -> Thực phẩm thô, sơ chế | Đúng | — | Đối chiếu danh mục nhóm QĐ26 Điều 2 và tiêu đề/phần A-B-C của phiếu tương ứng. |
| agent:edge:HAS_SUBGROUP:02 | ocop:kg_edge:4c5bb9f3b8e78d2b8c1316d1 | VN.OCOP.QD26.2026 p18; VN.OCOP.QD26.2026 p2 | ocop:evidence:64db7d95b2e5bc8b13f1d6cd | [96.95, 75.74, 545.46, 260.53] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | thực phẩm -> Thực phẩm tươi sống | Đúng | — | Đối chiếu danh mục nhóm QĐ26 Điều 2 và tiêu đề/phần A-B-C của phiếu tương ứng. |
| agent:edge:LOCATED_IN:01 | ocop:kg_edge:77b89092a5ec9cc860f6ac9c | VN.NQ.15.2026 p2 | ocop:evidence:2d31a0c8509acd4ebfab62d4 | [0.0, 0.0, 595.32, 842.04] | f76f585b4a3066bf9ae1511deff62690bf03fc88eca3eeddfc1fb922543689ec | page -> 15/2026/NQ-CP | Đúng | — | Ảnh đối chiếu đúng văn bản/trang và đoạn chứa thực thể; chỉ là liên kết provenance. |
| agent:edge:LOCATED_IN:02 | ocop:kg_edge:c3b52aec262d8558d86b827d | VN.ND.15.2018 p4; VN.ND.15.2018 p5 | ocop:evidence:9111c11414e4a0ac48a7dc1a | [86.76, 146.25, 264.87, 161.79] | 9dec41b53cb1568a50fc3a98b41a95df2e6595341e5dd8dcf5926d22dde4b1b2 | article — Điều 4. Tự công bố sản phẩm 1. Tổ chức, cá nhân sản xuất, kinh doanh thực phẩm thực hiện t -> 15/2018/NĐ-CP | Đúng | — | Ảnh đối chiếu đúng văn bản/trang và đoạn chứa thực thể; chỉ là liên kết provenance. |
| agent:edge:LOCATED_IN:03 | ocop:kg_edge:b00497c64b84d8edc43a0180 | VN.OCOP.QD26.2026 p31; VN.HATINH.THANHSEN.2026 p1 | ocop:evidence:dbe316e0e3dd7c3d5fedff17 | [87.84, 77.27, 560.64, 781.57] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | criterion_table_candidate — 5. CÂU CHUYỆN SẢN PHẨM \| 12 5.1. Câu chuyện sản phẩm \| 5 Không có câu chuyện sản phẩm \| 0  -> 26/2026/QĐ-TTg | Đúng | — | Ảnh đối chiếu đúng văn bản/trang và đoạn chứa thực thể; chỉ là liên kết provenance. |
| agent:edge:LOCATED_IN:04 | ocop:kg_edge:f2741780d934fe48b21252c8 | VN.ND.43.2017 p1 | ocop:evidence:4131fdc9431ad985775c0040 | [86.76, 478.41, 254.91, 493.95] | d5771b9da7a7f898b7eeef23a21966c85a49c57572e9c71788f24b7f04f0cbdb | article — Điều 1. Phạm vi điều chỉnh 1. Nghị định này quy định nội dung, cách ghi và quản lý nhà nướ -> 43/2017/NĐ-CP | Đúng | — | Ảnh đối chiếu đúng văn bản/trang và đoạn chứa thực thể; chỉ là liên kết provenance. |
| agent:edge:LOCATED_IN:05 | ocop:kg_edge:51c3b84c6ac72b2482bab915 | VN.OCOP.QD1489.2025 p4; VN.HAIPHONG.QD525.2026 p1 | ocop:evidence:f9793241c65936327f959696 | [127.68, 50.15, 275.28, 67.42] | c8feaadc85cece82579b90aaf7b5899920630f1546d08ddd3860c75cb388e4b7 | paragraph — - UBND cấp tỉnh chuyển hồ sơ các sản phẩm đạt từ 90 điểm đến 100 điểm lên bộ nông nghiệp v -> 1489/QĐ-TTg | Đúng | — | Ảnh đối chiếu đúng văn bản/trang và đoạn chứa thực thể; chỉ là liên kết provenance. |
| agent:edge:OWNED_BY:01 | ocop:kg_edge:cf3a63b14f957fe14680b5a7 | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 671.38, 557.27, 706.92] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Gạo ruộng rươi giống HANA -> Hợp tác xã sản xuất kinh doanh dịch vụ nông nghiệp Thụy Hương | Đúng | — | QĐ525 p3: đối chiếu STT và ô tổ chức/cá nhân gộp cùng hàng; không dùng điểm/sao. |
| agent:edge:OWNED_BY:02 | ocop:kg_edge:e54e5d635ecfca0b1b03e9a3 | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 600.46, 557.27, 635.98] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Gạo ruộng rươi Hạt ngọc 9 -> Hợp tác xã sản xuất kinh doanh dịch vụ nông nghiệp Thụy Hương | Đúng | — | QĐ525 p3: đối chiếu STT và ô tổ chức/cá nhân gộp cùng hàng; không dùng điểm/sao. |
| agent:edge:OWNED_BY:03 | ocop:kg_edge:9c15fd4f1987d89221ba1b02 | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 358.49, 557.27, 412.99] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Nước mắm truyền thống đảo Cát Hải loại Đặc Biệt -> Công ty Trách nhiệm hữu hạn Quang Hải | Đúng | — | QĐ525 p3: đối chiếu STT và ô tổ chức/cá nhân gộp cùng hàng; không dùng điểm/sao. |
| agent:edge:OWNED_BY:04 | ocop:kg_edge:a3b2c99904f5eadfd8686c2e | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 635.98, 557.27, 671.38] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Gạo ruộng rươi Nếp cái hoa vàng -> Hợp tác xã sản xuất kinh doanh dịch vụ nông nghiệp Thụy Hương | Đúng | — | QĐ525 p3: đối chiếu STT và ô tổ chức/cá nhân gộp cùng hàng; không dùng điểm/sao. |
| agent:edge:OWNED_BY:05 | ocop:kg_edge:755598b1451f5d2166be3afb | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 742.44, 557.27, 777.99] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Gạo ruộng rươi Tím thảo dược -> Hợp tác xã sản xuất kinh doanh dịch vụ nông nghiệp Thụy Hương | Đúng | — | QĐ525 p3: đối chiếu STT và ô tổ chức/cá nhân gộp cùng hàng; không dùng điểm/sao. |
| agent:edge:RECOGNIZES:01 | ocop:kg_edge:792416325fff65f293d4c762 | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 542.26, 557.27, 577.78] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Dòng 9 — VN.HAIPHONG.QD525.2026 -> Nước mắm chắt mực nguyên chất | Đúng | — | QĐ525 p3: đúng số thứ tự, sản phẩm và phạm vi phụ lục quyết định. |
| agent:edge:RECOGNIZES:02 | ocop:kg_edge:4622af212e875271f27a0461 | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 600.46, 557.27, 635.98] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Dòng 11 — VN.HAIPHONG.QD525.2026 -> Gạo ruộng rươi Hạt ngọc 9 | Đúng | — | QĐ525 p3: đúng số thứ tự, sản phẩm và phạm vi phụ lục quyết định. |
| agent:edge:RECOGNIZES:03 | ocop:kg_edge:d2eeb55720631bd1c1071b33 | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 194.9, 557.27, 412.99] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Dòng 1 — VN.HAIPHONG.QD525.2026 -> Nước mắm truyền thống sản xuất tại Cát Hải loại Chắt cao cấp | Đúng | — | QĐ525 p3: đúng số thứ tự, sản phẩm và phạm vi phụ lục quyết định. |
| agent:edge:RECOGNIZES:04 | ocop:kg_edge:a8fd301045ecb3ced9118876 | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 706.92, 557.27, 742.44] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Dòng 14 — VN.HAIPHONG.QD525.2026 -> Gạo ruộng rươi giống Huyết rồng | Đúng | — | QĐ525 p3: đúng số thứ tự, sản phẩm và phạm vi phụ lục quyết định. |
| agent:edge:RECOGNIZES:05 | ocop:kg_edge:6c8ab2d8f83b9c9132a1f0b8 | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 412.99, 557.27, 577.78] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Dòng 5 — VN.HAIPHONG.QD525.2026 -> Nước mắm cao cấp hương vị cổ xưa | Đúng | — | QĐ525 p3: đúng số thứ tự, sản phẩm và phạm vi phụ lục quyết định. |
| agent:edge:REPLACES:01 | ocop:kg_edge:193050f93ccafa0b1b0b6b4c | VN.OCOP.QD26.2026 p13; VN.HATINH.THANHSEN.2026 p1 | ocop:evidence:6d23038cd7b39d2e6b133511 | [100.32, 130.54, 560.4, 301.4] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 26/2026/QĐ-TTg -> 1489/QĐ-TTg | Đúng | — | QĐ26 Điều 11 khoản 2 nêu QĐ1489 hết hiệu lực sau 60 ngày. |
| agent:edge:REPLACES:02 | ocop:kg_edge:d53a04c6548b130d0d185aa4 | VN.OCOP.QD26.2026 p13; VN.HATINH.THANHSEN.2026 p1 | ocop:evidence:6d23038cd7b39d2e6b133511 | [100.32, 130.54, 560.4, 301.4] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 26/2026/QĐ-TTg -> 148/QĐ-TTg | Đúng | — | QĐ26 Điều 11 khoản 2 nêu QĐ148 hết hiệu lực sau 60 ngày. |
| agent:edge:REQUIRES_EVIDENCE:01 | ocop:kg_edge:56332d5617faf6284fb0fc16 | VN.OCOP.QD26.2026 p22; VN.OCOP.QD26.2026 p21 | ocop:evidence:1f3bb42793fb7d35773e10e5 | [86.34, 336.78, 560.36, 364.2] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 9. CÔNG BỐ CHẤT LƯỢNG SẢN PHẨM -> phiếu kiểm nghiệm | Đúng | — | Ghi chú tiêu chí 9 ghi rõ Bản tiêu chuẩn sản phẩm phải có phiếu kiểm nghiệm. |
| agent:edge:REQUIRES_EVIDENCE:02 | ocop:kg_edge:950ffb02aa1be5c408cd6d13 | VN.OCOP.QD26.2026 p32; VN.OCOP.QD26.2026 p31 | ocop:evidence:a66f8c06456e2ec25f24ed43 | [86.49, 347.44, 559.57, 378.94] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 9. CÔNG BỐ SẢN PHẨM -> phiếu kiểm nghiệm | Đúng | — | Ghi chú tiêu chí 9 ghi rõ Bản tiêu chuẩn sản phẩm phải có phiếu kiểm nghiệm. |
| agent:edge:RESPONSIBLE_FOR:01 | ocop:kg_edge:4c5df9661ce36beb78a67689 | VN.OCOP.QD26.2026 p7; VN.OCOP.QD26.2026 p6 | ocop:evidence:45dc7d909d6e7c11ef1a770f | [97.2, 345.55, 546.24, 394.5] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Cơ quan tham mưu quản lý OCOP cấp tỉnh -> g) UBND cấp tỉnh giao cơ quan tham mưu quản lý OCOP cấp tỉnh thông báo bằng văn bản về kết quả đánh giá, phân hạng cho UBND cấp xã và các chủ thể OCOP | Đúng | — | Chủ thể được nêu trực tiếp trong câu giao nhiệm vụ trên ảnh. |
| agent:edge:RESPONSIBLE_FOR:02 | ocop:kg_edge:4e13fe3c0762cfaf2676481f | VN.OCOP.QD1489.2025 p3 | ocop:evidence:5fa5f72e2d02365b50e37c7e | [88.06, 646.8, 539.41, 680.88] | c8feaadc85cece82579b90aaf7b5899920630f1546d08ddd3860c75cb388e4b7 | Chủ tịch UBND cấp tỉnh -> - Chủ tịch UBND cấp tỉnh ban hành Quyết định phê duyệt kết quả đánh giá và Giấy chứng nhận cho các sản phẩm đạt 3 sao, 4 sao và công bố kết quả. | Đúng | — | Chủ thể được nêu trực tiếp trong câu giao nhiệm vụ trên ảnh. |
| agent:edge:RESPONSIBLE_FOR:03 | ocop:kg_edge:aedf5b353bd3f5549f93fd4f | VN.HATINH.THANHSEN.2026 p4; VN.HATINH.THANHSEN.2026 p3 | ocop:evidence:ec4340aabc0e754d40b580b9 | [25.43, 418.8, 571.56, 520.08] | b7abbcf2f519ba9adfd01f9a6794101dbc6da6c0c3906bf3346d238ad768d827 | UBND phường Thành Sen -> UBND phường thành Sen đề nghị các doanh nghiệp, hợp tác xã, tổ hợp tác, hộ sản xuất, kinh doanh và các chủ thể có sản phẩm phù hợp trên địa bàn phường chủ động rà soát sản phẩm, nhu cầu tham gia đánh giá, phân hạng hoặc nâng hạng, đánh giá lại sản ph | Đúng | — | Chủ thể được nêu trực tiếp trong câu giao nhiệm vụ trên ảnh. |
| agent:edge:RESPONSIBLE_FOR:04 | ocop:kg_edge:deffe9fbe75f2bf6c448faf1 | VN.NQ.15.2026 p2 | ocop:evidence:8966789549ea1e50bb267540 | [85.1, 675.91, 541.96, 755.41] | f76f585b4a3066bf9ae1511deff62690bf03fc88eca3eeddfc1fb922543689ec | Bộ Khoa học và Công nghệ -> c) Bộ Khoa học và Công nghệ: Tăng cường kiểm tra, theo dõi, giám sát hoạt động của các tổ chức đã đăng ký hoạt động công nhận (trong đó có hoạt động công nhận phòng thử nghiệm); phối hợp với các Bộ: Y tế, Công Thương, Nông nghiệp và Môi trường rà soá | Đúng | — | Chủ thể được nêu trực tiếp trong câu giao nhiệm vụ trên ảnh. |
| agent:edge:RESPONSIBLE_FOR:05 | ocop:kg_edge:e89de26eee5cfd9a42877406 | VN.OCOP.QD26.2026 p3; VN.OCOP.QD26.2026 p5 | ocop:evidence:909e330970f7cd14fac2d041 | [96.44, 683.23, 546.27, 751.4] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | UBND cấp xã -> 1. UBND cấp tỉnh tổ chức đánh giá, phân hạng sản phẩm OCOP cấp tỉnh ít nhất 02 đợt trong năm. Đợt 01 trước ngày 30 tháng 6 đối với các hồ sơ được UBND cấp xã để nghị trước ngày 30 tháng 4; đợt 02 trước ngày 30 tháng 12 đối với các hồ sơ được UBND cấp | Sai | parser/gate | QĐ26 p3: nhiệm vụ tổ chức đánh giá thuộc UBND cấp tỉnh; UBND cấp xã chỉ đề nghị hồ sơ trong mệnh đề phụ. Parser/cổng gán chủ thể phụ cho toàn câu. |
| agent:edge:SUPPORTED_BY:01 | ocop:kg_edge:dfe2a7d60c197d2196a98aea | VN.HATINH.THANHSEN.2026 p4 | ocop:evidence:ec4340aabc0e754d40b580b9 | [25.43, 418.8, 571.56, 520.08] | b7abbcf2f519ba9adfd01f9a6794101dbc6da6c0c3906bf3346d238ad768d827 | UBND phường thành Sen đề nghị các doanh nghiệp, hợp tác xã, tổ hợp tác, hộ sản xuất, kinh doanh và các chủ thể có sản phẩm phù hợp trên địa bàn phường chủ động rà soát sản phẩm, nhu cầu tham gia đánh giá, phân hạng hoặc nâng hạng, đánh giá lại sản ph -> paragraph — Phần A - Sản phẩm và sức mạnh cộng đồng: 40 điểm; Phần B ? Khả năng tiếp thị: 25 điểm; Phầ | Đúng | — | Ảnh đối chiếu đúng văn bản/trang và đoạn chứa thực thể; chỉ là liên kết provenance. |
| agent:edge:SUPPORTED_BY:02 | ocop:kg_edge:82a6e2c2d77723ffeb9fe411 | VN.ND.43.2017 p1 | ocop:evidence:ae46c14230f15e51932521f8 | [206.04, 427.65, 392.91, 460.11] | d5771b9da7a7f898b7eeef23a21966c85a49c57572e9c71788f24b7f04f0cbdb | 43/2017/NĐ-CP -> section — Chương I NHỮNG QUY ĐỊNH CHUNG | Đúng | — | Ảnh đối chiếu đúng văn bản/trang và đoạn chứa thực thể; chỉ là liên kết provenance. |
| agent:edge:SUPPORTED_BY:03 | ocop:kg_edge:0709f0ac740c3ea6468c9e1c | VN.OCOP.QD26.2026 p10; VN.OCOP.QD26.2026 p6 | ocop:evidence:4ebad89a5b1198bccba543fe | [125.96, 427.9, 543.23, 640.66] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Chủ tịch UBND cấp tỉnh -> article — Điều 8. Quy định về thu hồi giấy chứng nhận 1. Giấy chứng nhận bị thu hồi trong các trường | Đúng | — | Ảnh đối chiếu đúng văn bản/trang và đoạn chứa thực thể; chỉ là liên kết provenance. |
| agent:edge:SUPPORTED_BY:04 | ocop:kg_edge:ba263a240f62188298a17214 | VN.ND.15.2018 p4 | ocop:evidence:9111c11414e4a0ac48a7dc1a | [64.08, 170.37, 534.87, 265.83] | 9dec41b53cb1568a50fc3a98b41a95df2e6595341e5dd8dcf5926d22dde4b1b2 | 1. Tổ chức, cá nhân sản xuất, kinh doanh thực phẩm thực hiện tự công bố thực phẩm đã qua chế biến bao gói sẵn, phụ gia thực phẩm, chất hỗ trợ chế biến thực phẩm, dụng cụ chứa đựng thực phẩm, vật liệu bao gói tiếp xúc trực tiếp với thực phẩm (sau đây  -> article — Điều 4. Tự công bố sản phẩm 1. Tổ chức, cá nhân sản xuất, kinh doanh thực phẩm thực hiện t | Đúng | — | Ảnh đối chiếu đúng văn bản/trang và đoạn chứa thực thể; chỉ là liên kết provenance. |
| agent:edge:SUPPORTED_BY:05 | ocop:kg_edge:c6098d043f6dbf1a02900e89 | VN.OCOP.QD148.2023 p2; VN.HAIPHONG.QD525.2026 p1 | ocop:evidence:2f58cc7b3ef00fc5741cfc9e | [104.16, 63.59, 549.36, 767.93] | 4fec9058fe2d4024d00d1994151fbe4849eb8f45b73ee6bba236933ba15336a5 | 148/QĐ-TTg -> paragraph — a) Các sản phẩm tham gia chương trình OCOP, gồm 06 nhóm sản phẩm; Thực phẩm; đồ uống; dược | Đúng | — | Ảnh đối chiếu đúng văn bản/trang và đoạn chứa thực thể; chỉ là liên kết provenance. |
| agent:edge:USES_SHEET:01 | ocop:kg_edge:8cfa30d8e0744ec85c401cb3 | VN.OCOP.QD26.2026 p28; VN.OCOP.QD26.2026 p17 | ocop:evidence:b9b5e54287f1a7d594d39def | [87.29, 77.64, 550.52, 270.02] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Thực phẩm thô, sơ chế -> Bộ sản phẩm: gạo, ngũ cốc, hạt sơ chế khác | Đúng | — | Đối chiếu danh mục nhóm QĐ26 Điều 2 và tiêu đề/phần A-B-C của phiếu tương ứng. |
| agent:edge:USES_SHEET:02 | ocop:kg_edge:dade142799f0f4b29a1739fd | VN.OCOP.QD26.2026 p18; VN.OCOP.QD26.2026 p17 | ocop:evidence:64db7d95b2e5bc8b13f1d6cd | [96.95, 75.74, 545.46, 260.53] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Thực phẩm tươi sống -> Bộ sản phẩm: rau, củ, quả, hạt tươi | Đúng | — | Đối chiếu danh mục nhóm QĐ26 Điều 2 và tiêu đề/phần A-B-C của phiếu tương ứng. |
| agent:node:Article:01 | ocop:biz_entity:0dfbb358b57f489ef7c4c5ec | VN.ND.43.2017 p1 | ocop:evidence:4131fdc9431ad985775c0040 | [64.08, 478.41, 534.88, 762.51] | d5771b9da7a7f898b7eeef23a21966c85a49c57572e9c71788f24b7f04f0cbdb | Điều 1. Phạm vi điều chỉnh | Đúng | — | Đúng nhãn Điều/khoản, đánh số và nội dung gốc trên crop. |
| agent:node:Article:02 | ocop:biz_entity:ed5a54d055fa78cb7628dd37 | VN.OCOP.QD1489.2025 p1; VN.OCOP.QD1489.2025 p2 | ocop:evidence:c31bafd621828ae6107aad46 | [89.26, 638.16, 538.18, 776.64] | c8feaadc85cece82579b90aaf7b5899920630f1546d08ddd3860c75cb388e4b7 | Điều 1. Sửa đổi, bổ sung một số nội dung Quyết định số 148/QĐ-TTg ngày 24 tháng 02 năm 2023 của Thủ tướng Chính phủ về việc ban hành bộ tiêu chí và quy trình đánh giá, phân hạng sản phẩm chương trình mỗi xã một sản phẩm (OCOP) như sau: | Đúng | — | Đúng nhãn Điều/khoản, đánh số và nội dung gốc trên crop. |
| agent:node:Article:03 | ocop:biz_entity:be81bb50d1294e5e7fc1e792 | VN.OCOP.QD26.2026 p1 | ocop:evidence:6f3e1026bbcfec96f675e71d | [94.8, 478.8, 546.48, 769.44] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Điều 1. Phạm vi điều chỉnh và đối tượng áp dụng | Đúng | — | Đúng nhãn Điều/khoản, đánh số và nội dung gốc trên crop. |
| agent:node:Article:04 | ocop:biz_entity:8f6a591185f5e918a2686036 | VN.NQ.15.2026 p2 | ocop:evidence:8966789549ea1e50bb267540 | [85.1, 71.87, 595.32, 755.41] | f76f585b4a3066bf9ae1511deff62690bf03fc88eca3eeddfc1fb922543689ec | Điều 3. Trách nhiệm tổ chức thực hiện | Đúng | — | Đúng nhãn Điều/khoản, đánh số và nội dung gốc trên crop. |
| agent:node:Article:05 | ocop:biz_entity:35aaca72f7a8b3a80b1154ce | VN.HAIPHONG.QD525.2026 p1 | ocop:evidence:fdf1a60244519f15dbdb72e8 | [85.1, 600.04, 542.43, 651.61] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Điều 2. Giấy chứng nhận sản phẩm OCOP cấp thành phố có hiệu lực 36 tháng | Đúng | — | Đúng nhãn Điều/khoản, đánh số và nội dung gốc trên crop. |
| agent:node:Authority:01 | ocop:biz_entity:6a7d92ebd5c2b2b18afc3132 | VN.OCOP.QD26.2026 p6; VN.OCOP.QD26.2026 p7 | ocop:evidence:1b5f6917a839761d5a5f2916 | [95.8, 392.13, 542.63, 464.11] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Chủ tịch UBND cấp tỉnh | Đúng | — | Tên cơ quan/chức danh được in trực tiếp hoặc trong danh sách các Bộ trên ảnh. |
| agent:node:Authority:02 | ocop:biz_entity:6420967a9d5fae7350c582fc | VN.OCOP.QD1489.2025 p3; VN.OCOP.QD1489.2025 p4 | ocop:evidence:5fa5f72e2d02365b50e37c7e | [88.06, 646.8, 539.41, 722.64] | c8feaadc85cece82579b90aaf7b5899920630f1546d08ddd3860c75cb388e4b7 | UBND cấp tỉnh | Đúng | — | Tên cơ quan/chức danh được in trực tiếp hoặc trong danh sách các Bộ trên ảnh. |
| agent:node:Authority:03 | ocop:biz_entity:0ea634c5c49fd7b282d87d8c | VN.HATINH.THANHSEN.2026 p4 | ocop:evidence:ec4340aabc0e754d40b580b9 | [25.19, 281.04, 572.28, 296.88] | b7abbcf2f519ba9adfd01f9a6794101dbc6da6c0c3906bf3346d238ad768d827 | Bộ Nông nghiệp và Môi trường | Đúng | — | Tên cơ quan/chức danh được in trực tiếp hoặc trong danh sách các Bộ trên ảnh. |
| agent:node:Authority:04 | ocop:biz_entity:d909cdf6fa9316362648c28d | VN.NQ.15.2026 p2 | ocop:evidence:8966789549ea1e50bb267540 | [120.5, 93.83, 460.09, 109.37] | f76f585b4a3066bf9ae1511deff62690bf03fc88eca3eeddfc1fb922543689ec | Bộ Y tế | Đúng | — | Tên cơ quan/chức danh được in trực tiếp hoặc trong danh sách các Bộ trên ảnh. |
| agent:node:Authority:05 | ocop:biz_entity:ecd99334f582786590f9235c | VN.OCOP.QD26.2026 p3; VN.OCOP.QD26.2026 p4 | ocop:evidence:767fed169da96397ef6f7800 | [126.68, 494.11, 545.57, 514.32] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Bộ Nông nghiệp và Môi trường | Đúng | — | Tên cơ quan/chức danh được in trực tiếp hoặc trong danh sách các Bộ trên ảnh. |
| agent:node:Clause:01 | ocop:biz_entity:7ee32b5a4199f086e3228c62 | VN.ND.43.2017 p1 | ocop:evidence:4131fdc9431ad985775c0040 | [64.08, 499.41, 534.87, 531.75] | d5771b9da7a7f898b7eeef23a21966c85a49c57572e9c71788f24b7f04f0cbdb | 1. Nghị định này quy định nội dung, cách ghi và quản lý nhà nước về nhãn đối với hàng hóa lưu thông tại Việt Nam, hàng hóa nhập khẩu. | Đúng | — | Đúng nhãn Điều/khoản, đánh số và nội dung gốc trên crop. |
| agent:node:Clause:02 | ocop:biz_entity:36893ebc5b83f163f16aa03a | VN.NQ.15.2026 p2 | ocop:evidence:8966789549ea1e50bb267540 | [85.1, 449.92, 589.78, 755.41] | f76f585b4a3066bf9ae1511deff62690bf03fc88eca3eeddfc1fb922543689ec | 2. Ngoài trách nhiệm tại khoản 1 nêu trên, các Bộ ngành có các trách nhiệm sau: a) Bộ Y tế: Kiểm tra, theo dõi, giám sát, xử lý các hành vi vi phạm về đăng ký bản công bố sản phẩm, quảng cáo đối với các sản phẩm, hàng hóa, dịch vụ thuộc lĩnh vực được | Đúng | — | Đúng nhãn Điều/khoản, đánh số và nội dung gốc trên crop. |
| agent:node:Clause:03 | ocop:biz_entity:2fd90a6a5327fd9c3ebac263 | VN.ND.15.2018 p4; VN.ND.15.2018 p5 | ocop:evidence:d9bfb8b45d531adb32b77c6b | [64.08, 594.33, 534.89, 757.83] | 9dec41b53cb1568a50fc3a98b41a95df2e6595341e5dd8dcf5926d22dde4b1b2 | 2. Việc tự công bố sản phẩm được thực hiện theo trình tự như sau: a) Tổ chức, cá nhân tự công bố sản phẩm trên phương tiện thông tin đại chúng hoặc trang thông tin điện tử của mình hoặc niêm yết công khai tại trụ sở của tổ chức, cá nhân và nộp 01 (mộ | Đúng | — | Đúng nhãn Điều/khoản, đánh số và nội dung gốc trên crop. |
| agent:node:Clause:04 | ocop:biz_entity:bfbea1bcfbdbed6cb76f1b44 | VN.OCOP.QD1489.2025 p2 | ocop:evidence:3de3cca3e09c24b2f4fd9bb2 | [89.25, 90.95, 539.34, 121.43] | c8feaadc85cece82579b90aaf7b5899920630f1546d08ddd3860c75cb388e4b7 | 3. Sửa đổi, bổ sung một số nội dung phụ lục II về Quy trình đánh giá, phân hạng sản phẩm OCOP tại Phụ lục kèm theo. | Đúng | — | Đúng nhãn Điều/khoản, đánh số và nội dung gốc trên crop. |
| agent:node:Clause:05 | ocop:biz_entity:bc49ce183815efa99c89f50e | VN.OCOP.QD26.2026 p10 | ocop:evidence:4ebad89a5b1198bccba543fe | [96.95, 399.1, 543.69, 506.92] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 2. Thẩm quyền thu hồi giấy chứng nhận a) Chủ tịch UBND cấp tỉnh quyết định thu hồi giấy chứng nhận đối với sản phẩm OCOP được công nhận 3 sao, 4 sao. b) bộ trưởng bộ nông nghiệp và môi trường quyết định thu hồi giấy chứng nhận đối với sản phẩm OCOP đ | Đúng | — | Đúng nhãn Điều/khoản, đánh số và nội dung gốc trên crop. |
| agent:node:Criterion:01 | ocop:biz_entity:0b8dfe5a9d7846251ccab131 | VN.OCOP.QD26.2026 p30 | ocop:evidence:df121c3e9c4a4960293962e1 | [87.26, 609.63, 561.5, 630.79] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 4.3. Quảng bá sản phẩm | Đúng | — | Nhãn và loại khớp điểm điều khoản hoặc hàng tiêu chí có đánh số trên ảnh. |
| agent:node:Criterion:02 | ocop:biz_entity:c78f9741dc8fc3a6fce787a6 | VN.OCOP.QD26.2026 p28; VN.OCOP.QD26.2026 p29 | ocop:evidence:16d3307e324aa78461e0a642 | [91.01, 747.75, 564.65, 767.06] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 1.6. Bảo vệ môi trường trong quá trình sản xuất | Đúng | — | Nhãn và loại khớp điểm điều khoản hoặc hàng tiêu chí có đánh số trên ảnh. |
| agent:node:Criterion:03 | ocop:biz_entity:e912a834b5f79bab9e670d54 | VN.OCOP.QD26.2026 p31 | ocop:evidence:dbe316e0e3dd7c3d5fedff17 | [87.84, 545.92, 560.64, 561.76] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 6.2. Kích thước, độ đồng đều | Đúng | — | Nhãn và loại khớp điểm điều khoản hoặc hàng tiêu chí có đánh số trên ảnh. |
| agent:node:Criterion:04 | ocop:biz_entity:6652c3d705d26d40dc8b400e | VN.OCOP.QD26.2026 p29 | ocop:evidence:6a9a4b40ff8d8482365af94d | [89.2, 335.75, 560.62, 353.67] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 2.2. Đóng gói, bao bì sản phẩm | Đúng | — | Nhãn và loại khớp điểm điều khoản hoặc hàng tiêu chí có đánh số trên ảnh. |
| agent:node:Criterion:05 | ocop:biz_entity:aca1c0152329c99cde07b435 | VN.OCOP.QD26.2026 p31 | ocop:evidence:dbe316e0e3dd7c3d5fedff17 | [87.84, 437.7, 560.64, 458.34] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | 6. CHỈ TIÊU CẢM QUAN | Đúng | — | Nhãn và loại khớp điểm điều khoản hoặc hàng tiêu chí có đánh số trên ảnh. |
| agent:node:CriterionSheet:01 | ocop:biz_entity:cc89d91760cd8db481615741 | VN.OCOP.QD26.2026 p17 | ocop:evidence:0a9d2f086a2872738f55559a | [91.93, 623.56, 526.92, 645.09] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Bộ sản phẩm: hoa | Đúng | — | Tên bộ sản phẩm khớp hàng danh mục trên QĐ26 p17; không khẳng định đã OCR toàn bộ phiếu. |
| agent:node:CriterionSheet:02 | ocop:biz_entity:37437c76cad77448d57da12f | VN.OCOP.QD26.2026 p17 | ocop:evidence:0a9d2f086a2872738f55559a | [92.29, 568.13, 527.28, 589.42] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Bộ sản phẩm: Tỉnh dầu và dược liệu khác | Đúng | — | Tên bộ sản phẩm khớp hàng danh mục trên QĐ26 p17; không khẳng định đã OCR toàn bộ phiếu. |
| agent:node:CriterionSheet:03 | ocop:biz_entity:3066db1597b400f13d99f5a4 | VN.OCOP.QD26.2026 p17 | ocop:evidence:0a9d2f086a2872738f55559a | [92.8, 489.41, 527.79, 510.47] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Bộ sản phẩm: Nước khoáng thiên nhiên, nước uống đóng chai | Đúng | — | Tên bộ sản phẩm khớp hàng danh mục trên QĐ26 p17; không khẳng định đã OCR toàn bộ phiếu. |
| agent:node:CriterionSheet:04 | ocop:biz_entity:1115facf3237374d57a6a29d | VN.OCOP.QD26.2026 p17 | ocop:evidence:0a9d2f086a2872738f55559a | [93.99, 305.35, 528.98, 326.65] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Bộ sản phẩm: Chế biến từ rau, củ, quả, hạt | Đúng | — | Tên bộ sản phẩm khớp hàng danh mục trên QĐ26 p17; không khẳng định đã OCR toàn bộ phiếu. |
| agent:node:CriterionSheet:05 | ocop:biz_entity:6b9d42f3798de28005ecc9f7 | VN.OCOP.QD26.2026 p17 | ocop:evidence:0a9d2f086a2872738f55559a | [92.17, 586.6, 527.16, 608.13] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Bộ sản phẩm: Thủ công mỹ nghệ | Đúng | — | Tên bộ sản phẩm khớp hàng danh mục trên QĐ26 p17; không khẳng định đã OCR toàn bộ phiếu. |
| agent:node:EvidenceType:01 | ocop:llm_entity:83f8facf269bba8b31aee168 | VN.HATINH.THANHSEN.2026 p2 | ocop:evidence:3c8f9b60a02ae32e53de94ee | [29.03, 248.64, 567.25, 622.32] | b7abbcf2f519ba9adfd01f9a6794101dbc6da6c0c3906bf3346d238ad768d827 | phiếu kiểm nghiệm | Đúng | — | Loại giấy tờ được nêu nguyên văn trên ảnh; không suy ra bắt buộc nộp. |
| agent:node:EvidenceType:02 | ocop:llm_entity:948ba246f199ffd5c5de74a1 | VN.ND.15.2018 p4 | ocop:evidence:d9bfb8b45d531adb32b77c6b | [86.76, 406.29, 534.87, 421.83] | 9dec41b53cb1568a50fc3a98b41a95df2e6595341e5dd8dcf5926d22dde4b1b2 | Bản tự công bố sản phẩm | Đúng | — | Loại giấy tờ được nêu nguyên văn trên ảnh; không suy ra bắt buộc nộp. |
| agent:node:EvidenceType:03 | ocop:llm_entity:2636a1f3e5e3d3d609c2bd05 | VN.OCOP.QD1489.2025 p4 | ocop:evidence:f9793241c65936327f959696 | [88.08, 208.99, 537.6, 239.94] | c8feaadc85cece82579b90aaf7b5899920630f1546d08ddd3860c75cb388e4b7 | Báo cáo đánh giá của UBND cấp xã về một số tiêu chi (theo quy định tại điểm a, khoản 1 và biểu mẫu số 3) | Đúng | — | Loại giấy tờ được nêu nguyên văn trên ảnh; không suy ra bắt buộc nộp. |
| agent:node:EvidenceType:04 | ocop:llm_entity:b7bf6c31d8f074763844d52f | VN.OCOP.QD26.2026 p20; VN.OCOP.QD26.2026 p30 | ocop:evidence:29628eacdb3bb6cb2dbc9f2a | [83.76, 72.81, 565.6, 781.77] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Bằng độc quyền giải pháp hữu ích | Đúng | — | Loại giấy tờ được nêu nguyên văn trên ảnh; không suy ra bắt buộc nộp. |
| agent:node:EvidenceType:05 | ocop:llm_entity:e6e47445a83276b58a991060 | VN.HATINH.THANHSEN.2026 p2 | ocop:evidence:3c8f9b60a02ae32e53de94ee | [29.03, 248.64, 567.25, 622.32] | b7abbcf2f519ba9adfd01f9a6794101dbc6da6c0c3906bf3346d238ad768d827 | giấy tờ pháp lý có thời hạn | Đúng | — | Loại giấy tờ được nêu nguyên văn trên ảnh; không suy ra bắt buộc nộp. |
| agent:node:EvidenceUnit:01 | ocop:entity:a1cd1ef6495766a516fd4075 | VN.ND.43.2017 p1 | ocop:evidence:4131fdc9431ad985775c0040 | [86.76, 478.41, 254.91, 493.95] | d5771b9da7a7f898b7eeef23a21966c85a49c57572e9c71788f24b7f04f0cbdb | article — Điều 1. Phạm vi điều chỉnh 1. Nghị định này quy định nội dung, cách ghi và quản lý nhà nướ | Đúng | — | Đúng đoạn/trang nguồn và loại đơn vị chứng cứ; không xem đây là xác minh toàn bộ OCR. |
| agent:node:EvidenceUnit:02 | ocop:entity:b1bcb702091d1c18d66987d3 | VN.NQ.15.2026 p2 | ocop:evidence:8966789549ea1e50bb267540 | [120.5, 71.87, 350.26, 87.41] | f76f585b4a3066bf9ae1511deff62690bf03fc88eca3eeddfc1fb922543689ec | article — Điều 3. Trách nhiệm tổ chức thực hiện 1. Các Bộ: Y tế, Công Thương, Nông nghiệp và Môi trư | Đúng | — | Đúng đoạn/trang nguồn và loại đơn vị chứng cứ; không xem đây là xác minh toàn bộ OCR. |
| agent:node:EvidenceUnit:03 | ocop:entity:e646114e3cba80ca2b2b6f44 | VN.ND.15.2018 p5 | ocop:evidence:6b4e14b26cf4ccb370b9b7a6 | [170.52, 52.29, 429.42, 67.83] | 9dec41b53cb1568a50fc3a98b41a95df2e6595341e5dd8dcf5926d22dde4b1b2 | paragraph — CÔNG BÁO/Số 375 + 376/Ngày 15-02-2018 c) Cơ quan quản lý nhà nước có thẩm quyền tiếp nhận  | Đúng | — | Đúng đoạn/trang nguồn và loại đơn vị chứng cứ; không xem đây là xác minh toàn bộ OCR. |
| agent:node:EvidenceUnit:04 | ocop:entity:83c665e33a115f976402688d | VN.HAIPHONG.QD525.2026 p1 | ocop:evidence:fd224bcee260cbe37737604a | [113.42, 492.04, 542.4, 507.58] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | article — Điều 1. Công nhận kết quả đánh giá, phân hạng sản phẩm và cấp Giấy chứng nhận sản phẩm OCO | Đúng | — | Đúng đoạn/trang nguồn và loại đơn vị chứng cứ; không xem đây là xác minh toàn bộ OCR. |
| agent:node:EvidenceUnit:05 | ocop:evidence_node:baacd7aa4983fd598d8a1e4f | VN.OCOP.QD1489.2025 p2 | ocop:evidence:5f9e82131a2b0476bed7b1a7 | [0.0, 0.0, 601.0, 844.0] | c8feaadc85cece82579b90aaf7b5899920630f1546d08ddd3860c75cb388e4b7 | page | Đúng | — | Đúng đoạn/trang nguồn và loại đơn vị chứng cứ; không xem đây là xác minh toàn bộ OCR. |
| agent:node:FormTemplate:01 | ocop:biz_entity:67d24cf52cf066196f5f2f34 | VN.OCOP.QD26.2026 p4 | ocop:evidence:1b78a92d12fa79b60288ec0a | [96.94, 509.7, 543.41, 531.94] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Mẫu số 02 Phụ lục III | Đúng | — | Số mẫu/phụ lục khớp nguồn; đây là nhắc biểu mẫu, không khẳng định có trang mẫu đã điền. |
| agent:node:FormTemplate:02 | ocop:biz_entity:3904f0326a6d08f24e9a384c | VN.HATINH.THANHSEN.2026 p2 | ocop:evidence:da48030795c440765332bba2 | [38.39, 745.68, 541.09, 761.76] | b7abbcf2f519ba9adfd01f9a6794101dbc6da6c0c3906bf3346d238ad768d827 | Mẫu số 02, Phụ lục III | Đúng | — | Số mẫu/phụ lục khớp nguồn; đây là nhắc biểu mẫu, không khẳng định có trang mẫu đã điền. |
| agent:node:FormTemplate:03 | ocop:biz_entity:9cb3c80c3315b90eb84e1c8d | VN.ND.15.2018 p4 | ocop:evidence:d9bfb8b45d531adb32b77c6b | [86.76, 406.29, 534.87, 421.83] | 9dec41b53cb1568a50fc3a98b41a95df2e6595341e5dd8dcf5926d22dde4b1b2 | Mẫu số 01 Phụ lục I | Đúng | — | Số mẫu/phụ lục khớp nguồn; đây là nhắc biểu mẫu, không khẳng định có trang mẫu đã điền. |
| agent:node:FormTemplate:04 | ocop:biz_entity:633b83b2148d0bef0ed7602d | VN.OCOP.QD1489.2025 p4 | ocop:evidence:f9793241c65936327f959696 | [88.08, 222.43, 306.48, 239.94] | c8feaadc85cece82579b90aaf7b5899920630f1546d08ddd3860c75cb388e4b7 | mẫu số 3 | Đúng | — | Số mẫu/phụ lục khớp nguồn; đây là nhắc biểu mẫu, không khẳng định có trang mẫu đã điền. |
| agent:node:FormTemplate:05 | ocop:biz_entity:fb0b9a03be74fe93c96b78b6 | VN.OCOP.QD26.2026 p4 | ocop:evidence:1b78a92d12fa79b60288ec0a | [96.56, 495.27, 544.24, 516.39] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Mẫu số 01 Phụ lục III | Đúng | — | Số mẫu/phụ lục khớp nguồn; đây là nhắc biểu mẫu, không khẳng định có trang mẫu đã điền. |
| agent:node:Organization:01 | ocop:biz_entity:2d69c50a9117a792672bd77a | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [75.86, 577.78, 168.38, 777.99] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Hợp tác xã sản xuất kinh doanh dịch vụ nông nghiệp Thụy Hương | Đúng | — | Đối chiếu QĐ525 p1/p3: đúng số hiệu, tên chủ thể hoặc tên sản phẩm trong cột tương ứng. |
| agent:node:Organization:02 | ocop:biz_entity:63d7b8bdec8d47e1718056ed | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [75.86, 412.99, 168.38, 577.78] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Công ty Trách nhiệm hữu hạn Thủy Sản Song Hải | Đúng | — | Đối chiếu QĐ525 p1/p3: đúng số hiệu, tên chủ thể hoặc tên sản phẩm trong cột tương ứng. |
| agent:node:Organization:03 | ocop:biz_entity:41777c8827051936630679aa | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [75.86, 194.9, 168.38, 412.99] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Công ty Trách nhiệm hữu hạn Quang Hải | Đúng | — | Đối chiếu QĐ525 p1/p3: đúng số hiệu, tên chủ thể hoặc tên sản phẩm trong cột tương ứng. |
| agent:node:Point:01 | ocop:biz_entity:f769711149eb5c78f8dd2f33 | VN.ND.15.2018 p4 | ocop:evidence:d9bfb8b45d531adb32b77c6b | [64.08, 722.37, 534.87, 757.83] | 9dec41b53cb1568a50fc3a98b41a95df2e6595341e5dd8dcf5926d22dde4b1b2 | b) Ngay sau khi tự công bố sản phẩm, tổ chức, cá nhân được quyền sản xuất, kinh doanh sản phẩm và chịu trách nhiệm hoàn toàn về an toàn của sản phẩm đó; | Đúng | — | Nhãn và loại khớp điểm điều khoản hoặc hàng tiêu chí có đánh số trên ảnh. |
| agent:node:Point:02 | ocop:biz_entity:01088137ed8af0dccc1a7daf | VN.ND.43.2017 p1 | ocop:evidence:4131fdc9431ad985775c0040 | [64.08, 578.97, 534.88, 611.31] | d5771b9da7a7f898b7eeef23a21966c85a49c57572e9c71788f24b7f04f0cbdb | b) Hàng hóa tạm nhập tái xuất; hàng hóa tạm nhập để tham gia hội chợ, triển lãm sau đó tái xuất; hàng hóa quá cảnh, hàng hóa chuyển khẩu; hàng hóa trung chuyển; | Đúng | — | Nhãn và loại khớp điểm điều khoản hoặc hàng tiêu chí có đánh số trên ảnh. |
| agent:node:Point:03 | ocop:biz_entity:b63775f6ac58b032da01e4fa | VN.OCOP.QD26.2026 p8 | ocop:evidence:4e7c54cacdfa9382d9393520 | [96.48, 544.45, 543.89, 592.63] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | a) Chủ thể OCOP chuẩn bị hồ sơ đăng ký tham gia đánh giá, nâng hạng theo quy định tại điểm b khoản 1 Điều 6 Quyết định này UBND cấp xã chuẩn bị hồ sơ theo quy định tại khoản 2 Điều 6 Quyết định này. UBND cấp tỉnh chuẩn bị hồ sơ | Đúng | — | Nhãn và loại khớp điểm điều khoản hoặc hàng tiêu chí có đánh số trên ảnh. |
| agent:node:Point:04 | ocop:biz_entity:74c2635aba6b37d76ab84a2b | VN.NQ.15.2026 p2 | ocop:evidence:8966789549ea1e50bb267540 | [85.1, 239.87, 595.32, 303.44] | f76f585b4a3066bf9ae1511deff62690bf03fc88eca3eeddfc1fb922543689ec | c) Chủ động rà soát, sửa đổi, bổ sung và ban hành các văn bản quy phạm pháp luật, Quy chuẩn kỹ thuật quốc gia (QCVN), các hướng dẫn chuyên môn, quy trình nội bộ thuộc phạm vi được phân công quản lý trong lĩnh vực an toàn thực phẩm. | Đúng | — | Nhãn và loại khớp điểm điều khoản hoặc hàng tiêu chí có đánh số trên ảnh. |
| agent:node:Point:05 | ocop:biz_entity:c761690ce9d01a18e02a809b | VN.ND.15.2018 p4 | ocop:evidence:d9bfb8b45d531adb32b77c6b | [64.08, 618.33, 534.89, 713.79] | 9dec41b53cb1568a50fc3a98b41a95df2e6595341e5dd8dcf5926d22dde4b1b2 | a) Tổ chức, cá nhân tự công bố sản phẩm trên phương tiện thông tin đại chúng hoặc trang thông tin điện tử của mình hoặc niêm yết công khai tại trụ sở của tổ chức, cá nhân và nộp 01 (một) bản qua đường bưu điện hoặc trực tiếp đến cơ quan quản lý nhà n | Đúng | — | Nhãn và loại khớp điểm điều khoản hoặc hàng tiêu chí có đánh số trên ảnh. |
| agent:node:ProcedureStep:01 | ocop:biz_entity:a313cf0a3d3ce3c550662b7e | VN.HATINH.THANHSEN.2026 p4 | ocop:evidence:ec4340aabc0e754d40b580b9 | [24.48, 536.4, 571.8, 617.52] | b7abbcf2f519ba9adfd01f9a6794101dbc6da6c0c3906bf3346d238ad768d827 | UBND phường thành sen sẽ hướng dẫn hỗ trợ các chủ thể hoàn thiện hồ sơ, tiêu chí và nâng cao chất lượng sản phẩm, góp phần phát triển các sản phẩm đặc trưng của địa phương theo hướng chất lượng, an toàn, xanh, bền vững, có thương hiệu và sức cạnh tra | Đúng | — | Câu mô tả thao tác/trách nhiệm đúng nguyên văn trên ảnh; tách biệt đánh giá quan hệ actor. |
| agent:node:ProcedureStep:02 | ocop:biz_entity:52d1307b06fbf110c6cec5d4 | VN.OCOP.QD1489.2025 p3 | ocop:evidence:8499ca172a4bacd0138f80e6 | [87.1, 314.4, 537.73, 439.68] | c8feaadc85cece82579b90aaf7b5899920630f1546d08ddd3860c75cb388e4b7 | (1) Tổ chức đánh giá một số nội dung của Hồ sơ sản phẩm đăng ký tham gia đánh giá sản phẩm OCOP, bao gồm các tiêu chi sau: nguồn gốc sản phẩm/nguyên liệu địa phương, sử dụng lao động địa phương; nguồn gốc ý tưởng sản phẩm; bản sắc/trí tuệ đia phương, | Đúng | — | Câu mô tả thao tác/trách nhiệm đúng nguyên văn trên ảnh; tách biệt đánh giá quan hệ actor. |
| agent:node:ProcedureStep:03 | ocop:biz_entity:cd7d5a594217809f166bef8b | VN.NQ.15.2026 p2 | ocop:evidence:8966789549ea1e50bb267540 | [85.1, 675.91, 541.96, 755.41] | f76f585b4a3066bf9ae1511deff62690bf03fc88eca3eeddfc1fb922543689ec | c) Bộ Khoa học và Công nghệ: Tăng cường kiểm tra, theo dõi, giám sát hoạt động của các tổ chức đã đăng ký hoạt động công nhận (trong đó có hoạt động công nhận phòng thử nghiệm); phối hợp với các Bộ: Y tế, Công Thương, Nông nghiệp và Môi trường rà soá | Đúng | — | Câu mô tả thao tác/trách nhiệm đúng nguyên văn trên ảnh; tách biệt đánh giá quan hệ actor. |
| agent:node:ProcedureStep:04 | ocop:biz_entity:2bf1ddaa821c1e794d85d6f8 | VN.OCOP.QD26.2026 p10 | ocop:evidence:4ebad89a5b1198bccba543fe | [97.08, 622.77, 545.74, 657.44] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | b) Chủ tịch UBND cấp tỉnh và Bộ trưởng bộ nông nghiệp và môi trường xem xét, quyết định thu hồi giấy chứng nhận theo thẩm quyền | Đúng | — | Câu mô tả thao tác/trách nhiệm đúng nguyên văn trên ảnh; tách biệt đánh giá quan hệ actor. |
| agent:node:ProcedureStep:05 | ocop:biz_entity:970e91ee6fc8aed4b3f26570 | VN.HATINH.THANHSEN.2026 p4 | ocop:evidence:ec4340aabc0e754d40b580b9 | [25.19, 256.56, 572.28, 318.72] | b7abbcf2f519ba9adfd01f9a6794101dbc6da6c0c3906bf3346d238ad768d827 | Trong đó, UBND cấp tỉnh tổ chức đánh giá, phân hạng và quyết định công nhận sản phẩm OCOP 3 sao, 4 sao; Bộ Nông nghiệp và Môi trường tổ chức đánh giá, phân hạng và quyết định công nhận sản phẩm 5 sao. | Đúng | — | Câu mô tả thao tác/trách nhiệm đúng nguyên văn trên ảnh; tách biệt đánh giá quan hệ actor. |
| agent:node:Product:01 | ocop:biz_entity:9e9934c9eb97064cb493f527 | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [168.38, 577.78, 288.29, 600.46] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Gạo ruộng rươi ST25 | Đúng | — | Đối chiếu QĐ525 p1/p3: đúng số hiệu, tên chủ thể hoặc tên sản phẩm trong cột tương ứng. |
| agent:node:Product:02 | ocop:biz_entity:407ebcc783ba678532582e42 | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [168.38, 194.9, 288.29, 249.53] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Nước mắm truyền thống sản xuất tại Cát Hải loại Chắt cao cấp | Đúng | — | Đối chiếu QĐ525 p1/p3: đúng số hiệu, tên chủ thể hoặc tên sản phẩm trong cột tương ứng. |
| agent:node:Product:03 | ocop:biz_entity:d57979fa9347495479745fa9 | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [168.38, 542.26, 288.29, 577.78] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Nước mắm chắt mực nguyên chất | Đúng | — | Đối chiếu QĐ525 p1/p3: đúng số hiệu, tên chủ thể hoặc tên sản phẩm trong cột tương ứng. |
| agent:node:Product:04 | ocop:biz_entity:cdbe8cfb398d48e4e46720b7 | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [168.38, 742.44, 288.29, 777.99] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Gạo ruộng rươi Tím thảo dược | Đúng | — | Đối chiếu QĐ525 p1/p3: đúng số hiệu, tên chủ thể hoặc tên sản phẩm trong cột tương ứng. |
| agent:node:Product:05 | ocop:biz_entity:9fb9412f24977f150e83a433 | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [168.38, 358.49, 288.29, 412.99] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Nước mắm truyền thống đảo Cát Hải loại Đặc Biệt | Đúng | — | Đối chiếu QĐ525 p1/p3: đúng số hiệu, tên chủ thể hoặc tên sản phẩm trong cột tương ứng. |
| agent:node:ProductGroup:01 | ocop:biz_entity:6e94f8103134a16bbf8c8241 | VN.OCOP.QD26.2026 p2; VN.OCOP.QD26.2026 p5 | ocop:evidence:30041b9784e22e006e2132ab | [97.52, 241.62, 546.16, 275.48] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | dịch vụ du lịch cộng đồng, du lịch sinh thái và điểm du lịch | Đúng | — | Tên nhóm/phân nhóm xuất hiện đúng trong danh mục hoặc dòng phân loại của phiếu. |
| agent:node:ProductGroup:02 | ocop:biz_entity:9a044ba9c3ab418860c6cad3 | VN.OCOP.QD26.2026 p2 | ocop:evidence:30041b9784e22e006e2132ab | [98.14, 241.62, 544.86, 258.69] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | sinh vật cảnh | Đúng | — | Tên nhóm/phân nhóm xuất hiện đúng trong danh mục hoặc dòng phân loại của phiếu. |
| agent:node:ProductGroup:03 | ocop:biz_entity:f76de255b98e8f897db2ab01 | VN.OCOP.QD26.2026 p2; VN.OCOP.QD26.2026 p18 | ocop:evidence:30041b9784e22e006e2132ab | [98.28, 147.78, 546.44, 243.32] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | thực phẩm | Đúng | — | Tên nhóm/phân nhóm xuất hiện đúng trong danh mục hoặc dòng phân loại của phiếu. |
| agent:node:ProductGroup:04 | ocop:biz_entity:a06c7f4542193c2c883d4f3b | VN.OCOP.QD26.2026 p2 | ocop:evidence:30041b9784e22e006e2132ab | [98.14, 219.96, 546.44, 258.69] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | hàng thủ công mỹ nghệ | Đúng | — | Tên nhóm/phân nhóm xuất hiện đúng trong danh mục hoặc dòng phân loại của phiếu. |
| agent:node:ProductSubgroup:01 | ocop:biz_entity:50ef9f72a7f3a4a0675fc60b | VN.OCOP.QD26.2026 p28 | ocop:evidence:b9b5e54287f1a7d594d39def | [87.29, 77.64, 550.52, 270.02] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Thực phẩm thô, sơ chế | Đúng | — | Tên nhóm/phân nhóm xuất hiện đúng trong danh mục hoặc dòng phân loại của phiếu. |
| agent:node:ProductSubgroup:02 | ocop:biz_entity:d0993bca6e84079a4d24c640 | VN.OCOP.QD26.2026 p18 | ocop:evidence:64db7d95b2e5bc8b13f1d6cd | [96.95, 75.74, 545.46, 260.53] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Thực phẩm tươi sống | Đúng | — | Tên nhóm/phân nhóm xuất hiện đúng trong danh mục hoặc dòng phân loại của phiếu. |
| agent:node:RecognitionDecision:01 | ocop:biz_entity:9bba6016cb54d22e1cb5e39b | VN.HAIPHONG.QD525.2026 p3; VN.HAIPHONG.QD525.2026 p1 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 194.9, 557.27, 412.99] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | 525/QĐ-UBND | Đúng | — | Đối chiếu QĐ525 p1/p3: đúng số hiệu, tên chủ thể hoặc tên sản phẩm trong cột tương ứng. |
| agent:node:RecognitionRecord:01 | ocop:biz_entity:1960bc0f968a2ebc91e24372 | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 448.51, 557.27, 471.19] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Dòng 6 — VN.HAIPHONG.QD525.2026 | Đúng | — | STT khớp hàng bảng QĐ525 p3; graph chỉ giữ định danh hàng. |
| agent:node:RecognitionRecord:02 | ocop:biz_entity:a4c9c088d1753027da67a662 | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 249.53, 557.27, 304.01] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Dòng 2 — VN.HAIPHONG.QD525.2026 | Đúng | — | STT khớp hàng bảng QĐ525 p3; graph chỉ giữ định danh hàng. |
| agent:node:RecognitionRecord:03 | ocop:biz_entity:0ab3ec6468e0863a903ff13c | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 600.46, 557.27, 635.98] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Dòng 11 — VN.HAIPHONG.QD525.2026 | Đúng | — | STT khớp hàng bảng QĐ525 p3; graph chỉ giữ định danh hàng. |
| agent:node:RecognitionRecord:04 | ocop:biz_entity:1a47a7d95ea6805c7ec0d331 | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 635.98, 557.27, 671.38] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Dòng 12 — VN.HAIPHONG.QD525.2026 | Đúng | — | STT khớp hàng bảng QĐ525 p3; graph chỉ giữ định danh hàng. |
| agent:node:RecognitionRecord:05 | ocop:biz_entity:d2c1057cf50561f5a7ad8137 | VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:d0812e4de1c1fc5d642f892a | [42.47, 577.78, 557.27, 777.99] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | Dòng 10 — VN.HAIPHONG.QD525.2026 | Đúng | — | STT khớp hàng bảng QĐ525 p3; graph chỉ giữ định danh hàng. |
| agent:node:ScoreOption:01 | ocop:biz_entity:324e039370319ca67504166c | VN.OCOP.QD26.2026 p32 | ocop:evidence:a66f8c06456e2ec25f24ed43 | [86.28, 330.41, 559.25, 353.26] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Có công bố chất lượng sản phẩm theo quy định và áp dụng các tiêu chuẩn quốc tế | Đúng | — | Nội dung phương án và vị trí hàng khớp ảnh; không xác nhận số điểm/sao cho xếp hạng. |
| agent:node:ScoreOption:02 | ocop:biz_entity:201e90e221327a34b469b016 | VN.OCOP.QD26.2026 p29 | ocop:evidence:6a9a4b40ff8d8482365af94d | [88.6, 241.68, 560.01, 259.36] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Sản phẩm được trồng phổ biến ở nhiều tỉnh, thành phố | Đúng | — | Nội dung phương án và vị trí hàng khớp ảnh; không xác nhận số điểm/sao cho xếp hạng. |
| agent:node:ScoreOption:03 | ocop:biz_entity:d2ae36fe959d7b38d44db062 | VN.OCOP.QD26.2026 p32 | ocop:evidence:a66f8c06456e2ec25f24ed43 | [89.52, 594.39, 562.47, 614.84] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Có thể xuất khẩu đến thị trường khu vực Đông Nam Á | Đúng | — | Nội dung phương án và vị trí hàng khớp ảnh; không xác nhận số điểm/sao cho xếp hạng. |
| agent:node:ScoreOption:04 | ocop:biz_entity:8f0074f1f4830f9024eb9594 | VN.OCOP.QD26.2026 p20 | ocop:evidence:29628eacdb3bb6cb2dbc9f2a | [86.39, 281.8, 560.6, 383.72] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Các nhãn hiệu sử dụng trên bao bì, nhãn của sản phẩm được cấp Giấy chứng nhận đăng ký nhãn hiệu và sản phẩm có sử dụng dấu hiệu chỉ dẫn nguồn gốc địa lý gắn với cộng đồng địa phương (trường hợp sản phẩm đã được nhà nước bảo hộ chi dân địa lý, nhân hi | Đúng | — | Nội dung phương án và vị trí hàng khớp ảnh; không xác nhận số điểm/sao cho xếp hạng. |
| agent:node:ScoreOption:05 | ocop:biz_entity:6b12cd72847f2c8c2874e39d | VN.OCOP.QD26.2026 p19 | ocop:evidence:444cd79b9a07b0152dd919f5 | [92.32, 763.23, 563.02, 784.95] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Có sử dụng từ 50% đến 75% lao động là người trên địa bàn cấp xã | Đúng | — | Nội dung phương án và vị trí hàng khớp ảnh; không xác nhận số điểm/sao cho xếp hạng. |
| agent:node:SourceDocument:01 | ocop:entity:79a99b3570d8a9a11c51dd26 | VN.ND.43.2017 p1 | ocop:evidence:7f159840442ed9e06ca874b0 | [83.76, 6.24, 529.79, 409.47] | d5771b9da7a7f898b7eeef23a21966c85a49c57572e9c71788f24b7f04f0cbdb | 43/2017/NĐ-CP | Đúng | — | Số hiệu/định danh nguồn khớp PDF hoặc viện dẫn có registry; tài liệu địa phương không có số hiệu giữ source ID. |
| agent:node:SourceDocument:02 | ocop:entity:1dc033ee35d8770a4c24edc7 | VN.HAIPHONG.QD525.2026 p1; VN.OCOP.QD1489.2025 p1 | ocop:evidence:97bfa6ba30b873074ba6cc10 | [85.1, 57.33, 543.6, 483.58] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | 1489/QĐ-TTg | Đúng | — | Số hiệu/định danh nguồn khớp PDF hoặc viện dẫn có registry; tài liệu địa phương không có số hiệu giữ source ID. |
| agent:node:SourceDocument:03 | ocop:entity:40e84ec34ef4ca036b6bf4d6 | VN.HAIPHONG.QD525.2026 p1; VN.HAIPHONG.QD525.2026 p3 | ocop:evidence:97bfa6ba30b873074ba6cc10 | [85.1, 57.33, 543.6, 483.58] | b6d12a12fa40c88c6b05e7378b07623d241b9646da712735bd30527d4e9534cb | 525/QĐ-UBND | Đúng | — | Số hiệu/định danh nguồn khớp PDF hoặc viện dẫn có registry; tài liệu địa phương không có số hiệu giữ source ID. |
| agent:node:SourceDocument:04 | ocop:entity:66171a9e34910e014d5806db | VN.HATINH.THANHSEN.2026 p1; VN.HATINH.THANHSEN.2026 p3 | ocop:evidence:634a79b520ee4eae00e7dabb | [24.95, 30.72, 572.52, 774.48] | b7abbcf2f519ba9adfd01f9a6794101dbc6da6c0c3906bf3346d238ad768d827 | 26/2026/QĐ-TTg | Đúng | — | Số hiệu/định danh nguồn khớp PDF hoặc viện dẫn có registry; tài liệu địa phương không có số hiệu giữ source ID. |
| agent:node:SourceDocument:05 | ocop:entity:5185d98d9173ec2004ebae5c | VN.HATINH.THANHSEN.2026 p1; VN.HATINH.THANHSEN.2026 p2 | ocop:evidence:634a79b520ee4eae00e7dabb | [24.95, 30.72, 572.52, 774.48] | b7abbcf2f519ba9adfd01f9a6794101dbc6da6c0c3906bf3346d238ad768d827 | VN.HATINH.THANHSEN.2026 | Đúng | — | Số hiệu/định danh nguồn khớp PDF hoặc viện dẫn có registry; tài liệu địa phương không có số hiệu giữ source ID. |
| llm_added:edge:SUPPORTED_BY:01 | ocop:kg_edge:adc1ec40d53b1b62a72e6d1f | VN.OCOP.QD26.2026 p19; VN.OCOP.QD26.2026 p29 | ocop:evidence:444cd79b9a07b0152dd919f5 | [88.62, 72.28, 563.02, 784.95] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | giấy đăng ký kinh doanh -> criterion_table_candidate — Có Hồ sơ, thủ tục về môi trường theo quy định của pháp luật về bảo vệ môi trường và hồ sơ  | Đúng | — | Cụm giấy tờ xuất hiện trong đơn vị chứng cứ trên ảnh; cạnh chỉ dẫn nguồn, không suy ra quan hệ nghiệp vụ. |
| llm_added:edge:SUPPORTED_BY:02 | ocop:kg_edge:e1436410fd18710d8a52346b | VN.OCOP.QD1489.2025 p3 | ocop:evidence:8499ca172a4bacd0138f80e6 | [88.78, 437.04, 537.25, 470.88] | c8feaadc85cece82579b90aaf7b5899920630f1546d08ddd3860c75cb388e4b7 | văn bản đề nghị UBND cấp tỉnh đánh giá, phân hạng các sản phẩm trên địa bàn xã -> paragraph — Kê C (145/0 TTg NGÀY 24 Waresterning Kèm theo Quyết định số 1489/QĐ-TTg ngày 06 tháng 7 nă | Đúng | — | Cụm giấy tờ xuất hiện trong đơn vị chứng cứ trên ảnh; cạnh chỉ dẫn nguồn, không suy ra quan hệ nghiệp vụ. |
| llm_added:edge:SUPPORTED_BY:03 | ocop:kg_edge:8372553529045f0052471fd9 | VN.ND.15.2018 p5 | ocop:evidence:6b4e14b26cf4ccb370b9b7a6 | [86.77, 260.13, 534.88, 275.67] | 9dec41b53cb1568a50fc3a98b41a95df2e6595341e5dd8dcf5926d22dde4b1b2 | hồ sơ tự công bố -> paragraph — CÔNG BÁO/Số 375 + 376/Ngày 15-02-2018 c) Cơ quan quản lý nhà nước có thẩm quyền tiếp nhận  | Đúng | — | Cụm giấy tờ xuất hiện trong đơn vị chứng cứ trên ảnh; cạnh chỉ dẫn nguồn, không suy ra quan hệ nghiệp vụ. |
| llm_added:edge:SUPPORTED_BY:04 | ocop:kg_edge:a2e4552993cac842c0a3a42d | VN.HATINH.THANHSEN.2026 p2; VN.HATINH.THANHSEN.2026 p3 | ocop:evidence:da48030795c440765332bba2 | [38.39, 723.84, 546.85, 739.92] | b7abbcf2f519ba9adfd01f9a6794101dbc6da6c0c3906bf3346d238ad768d827 | Phiếu đăng ký đánh giá, phân hạng sản phẩm OCOP -> paragraph — bảo đảm an toàn thực phẩm, bảo vệ môi trường và trách nhiệm xã hội, hướng đến phát triển x | Đúng | — | Cụm giấy tờ xuất hiện trong đơn vị chứng cứ trên ảnh; cạnh chỉ dẫn nguồn, không suy ra quan hệ nghiệp vụ. |
| llm_added:edge:SUPPORTED_BY:05 | ocop:kg_edge:fc51670029a12094aee00480 | VN.OCOP.QD26.2026 p18; VN.OCOP.QD26.2026 p28 | ocop:evidence:3f323c76931c441bfe7c9ace | [87.15, 259.55, 563.64, 773.88] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | hợp đồng liên kết -> criterion_table_candidate — Các tiêu chí \| Thang điểm Phần A: SẢN PHẨM VÀ SỨC MẠNH CỦA CỘNG ĐỒNG (40 Điểm) \| 40 1. TỔ  | Đúng | — | Cụm giấy tờ xuất hiện trong đơn vị chứng cứ trên ảnh; cạnh chỉ dẫn nguồn, không suy ra quan hệ nghiệp vụ. |
| llm_added:node:EvidenceType:01 | ocop:llm_entity:7ae56930503d086a8bcccba5 | VN.OCOP.QD1489.2025 p4 | ocop:evidence:f9793241c65936327f959696 | [87.36, 167.24, 537.6, 201.07] | c8feaadc85cece82579b90aaf7b5899920630f1546d08ddd3860c75cb388e4b7 | Văn bản của UBND cấp xã gửi UBND cấp tỉnh đề nghị đánh giá, phân hạng sản phẩm OCOP | Đúng | — | Tên giấy tờ khớp cụm từ in trên ảnh; chỉ nhận dạng loại chứng cứ, không tự nối yêu cầu nộp. |
| llm_added:node:EvidenceType:02 | ocop:llm_entity:948ba246f199ffd5c5de74a1 | VN.ND.15.2018 p4 | ocop:evidence:d9bfb8b45d531adb32b77c6b | [86.76, 406.29, 534.87, 421.83] | 9dec41b53cb1568a50fc3a98b41a95df2e6595341e5dd8dcf5926d22dde4b1b2 | Bản tự công bố sản phẩm | Đúng | — | Tên giấy tờ khớp cụm từ in trên ảnh; chỉ nhận dạng loại chứng cứ, không tự nối yêu cầu nộp. |
| llm_added:node:EvidenceType:03 | ocop:llm_entity:d2cae19068751f3f23799f66 | VN.HATINH.THANHSEN.2026 p2; VN.HATINH.THANHSEN.2026 p3 | ocop:evidence:da48030795c440765332bba2 | [38.39, 723.84, 546.85, 739.92] | b7abbcf2f519ba9adfd01f9a6794101dbc6da6c0c3906bf3346d238ad768d827 | Phiếu đăng ký đánh giá, phân hạng sản phẩm OCOP | Đúng | — | Tên giấy tờ khớp cụm từ in trên ảnh; chỉ nhận dạng loại chứng cứ, không tự nối yêu cầu nộp. |
| llm_added:node:EvidenceType:04 | ocop:llm_entity:b7bf6c31d8f074763844d52f | VN.OCOP.QD26.2026 p20; VN.OCOP.QD26.2026 p30 | ocop:evidence:29628eacdb3bb6cb2dbc9f2a | [83.76, 72.81, 565.6, 781.77] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Bằng độc quyền giải pháp hữu ích | Đúng | — | Tên giấy tờ khớp cụm từ in trên ảnh; chỉ nhận dạng loại chứng cứ, không tự nối yêu cầu nộp. |
| llm_added:node:EvidenceType:05 | ocop:llm_entity:9f00630b6c83692f1b4645fd | VN.OCOP.QD1489.2025 p3 | ocop:evidence:8499ca172a4bacd0138f80e6 | [88.78, 437.04, 537.25, 470.88] | c8feaadc85cece82579b90aaf7b5899920630f1546d08ddd3860c75cb388e4b7 | văn bản đề nghị UBND cấp tỉnh đánh giá, phân hạng các sản phẩm trên địa bàn xã | Đúng | — | Tên giấy tờ khớp cụm từ in trên ảnh; chỉ nhận dạng loại chứng cứ, không tự nối yêu cầu nộp. |
| llm_added:node:EvidenceType:06 | ocop:llm_entity:4c6269b5fd30134a0e73de0d | VN.ND.15.2018 p5 | ocop:evidence:6b4e14b26cf4ccb370b9b7a6 | [86.77, 260.13, 534.88, 275.67] | 9dec41b53cb1568a50fc3a98b41a95df2e6595341e5dd8dcf5926d22dde4b1b2 | hồ sơ tự công bố | Đúng | — | Tên giấy tờ khớp cụm từ in trên ảnh; chỉ nhận dạng loại chứng cứ, không tự nối yêu cầu nộp. |
| llm_added:node:EvidenceType:07 | ocop:llm_entity:091b08fc8928cebd95c8766f | VN.HATINH.THANHSEN.2026 p2; VN.HATINH.THANHSEN.2026 p3 | ocop:evidence:da48030795c440765332bba2 | [38.39, 745.68, 541.09, 761.76] | b7abbcf2f519ba9adfd01f9a6794101dbc6da6c0c3906bf3346d238ad768d827 | Báo cáo tự đánh giá về sản phẩm | Đúng | — | Tên giấy tờ khớp cụm từ in trên ảnh; chỉ nhận dạng loại chứng cứ, không tự nối yêu cầu nộp. |
| llm_added:node:EvidenceType:08 | ocop:llm_entity:fac20bf4ad852c6ac9bd4650 | VN.OCOP.QD26.2026 p20; VN.OCOP.QD26.2026 p30 | ocop:evidence:29628eacdb3bb6cb2dbc9f2a | [83.76, 72.81, 565.6, 781.77] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Giấy chứng nhận đăng ký nhãn hiệu | Đúng | — | Tên giấy tờ khớp cụm từ in trên ảnh; chỉ nhận dạng loại chứng cứ, không tự nối yêu cầu nộp. |
| llm_added:node:EvidenceType:09 | ocop:llm_entity:5038913d9ac0a25c1d99e547 | VN.OCOP.QD1489.2025 p4 | ocop:evidence:f9793241c65936327f959696 | [127.2, 247.62, 238.32, 261.54] | c8feaadc85cece82579b90aaf7b5899920630f1546d08ddd3860c75cb388e4b7 | Hồ sơ sản phẩm | Đúng | — | Tên giấy tờ khớp cụm từ in trên ảnh; chỉ nhận dạng loại chứng cứ, không tự nối yêu cầu nộp. |
| llm_added:node:EvidenceType:10 | ocop:llm_entity:e4370173cd77339ab041a014 | VN.ND.15.2018 p5 | ocop:evidence:6b4e14b26cf4ccb370b9b7a6 | [86.76, 88.17, 534.87, 103.71] | 9dec41b53cb1568a50fc3a98b41a95df2e6595341e5dd8dcf5926d22dde4b1b2 | bản tự công bố | Đúng | — | Tên giấy tờ khớp cụm từ in trên ảnh; chỉ nhận dạng loại chứng cứ, không tự nối yêu cầu nộp. |
| llm_added:node:EvidenceType:11 | ocop:llm_entity:9aee02a481e37b3234b9ee3f | VN.HATINH.THANHSEN.2026 p2 | ocop:evidence:3c8f9b60a02ae32e53de94ee | [29.03, 248.64, 567.25, 622.32] | b7abbcf2f519ba9adfd01f9a6794101dbc6da6c0c3906bf3346d238ad768d827 | Báo cáo tự đánh giá theo Mẫu số 02 | Đúng | — | Tên giấy tờ khớp cụm từ in trên ảnh; chỉ nhận dạng loại chứng cứ, không tự nối yêu cầu nộp. |
| llm_added:node:EvidenceType:12 | ocop:llm_entity:25d92be3822d1363fa87506f | VN.OCOP.QD26.2026 p19; VN.OCOP.QD26.2026 p29 | ocop:evidence:444cd79b9a07b0152dd919f5 | [88.62, 72.28, 563.02, 784.95] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | hồ sơ minh chứng về sử dụng bao gói thân thiện với môi trường | Đúng | — | Tên giấy tờ khớp cụm từ in trên ảnh; chỉ nhận dạng loại chứng cứ, không tự nối yêu cầu nộp. |
| llm_added:node:EvidenceType:13 | ocop:llm_entity:e366331c94107d2dd9422688 | VN.OCOP.QD1489.2025 p4 | ocop:evidence:f9793241c65936327f959696 | [126.0, 125.73, 537.6, 148.52] | c8feaadc85cece82579b90aaf7b5899920630f1546d08ddd3860c75cb388e4b7 | Hồ sơ đề xuất đánh giá sản phẩm cấp tỉnh | Đúng | — | Tên giấy tờ khớp cụm từ in trên ảnh; chỉ nhận dạng loại chứng cứ, không tự nối yêu cầu nộp. |
| llm_added:node:EvidenceType:14 | ocop:llm_entity:2138591ba6f3e1c630cc2d9b | VN.ND.15.2018 p4 | ocop:evidence:d9bfb8b45d531adb32b77c6b | [86.76, 450.33, 534.87, 465.87] | 9dec41b53cb1568a50fc3a98b41a95df2e6595341e5dd8dcf5926d22dde4b1b2 | Phiếu kết quả kiểm nghiệm an toàn thực phẩm | Đúng | — | Tên giấy tờ khớp cụm từ in trên ảnh; chỉ nhận dạng loại chứng cứ, không tự nối yêu cầu nộp. |
| llm_added:node:EvidenceType:15 | ocop:llm_entity:e6e47445a83276b58a991060 | VN.HATINH.THANHSEN.2026 p2 | ocop:evidence:3c8f9b60a02ae32e53de94ee | [29.03, 248.64, 567.25, 622.32] | b7abbcf2f519ba9adfd01f9a6794101dbc6da6c0c3906bf3346d238ad768d827 | giấy tờ pháp lý có thời hạn | Đúng | — | Tên giấy tờ khớp cụm từ in trên ảnh; chỉ nhận dạng loại chứng cứ, không tự nối yêu cầu nộp. |
| llm_added:node:EvidenceType:16 | ocop:llm_entity:93a7c9a9db354e801d6a6d0b | VN.OCOP.QD26.2026 p20; VN.OCOP.QD26.2026 p30 | ocop:evidence:29628eacdb3bb6cb2dbc9f2a | [83.76, 72.81, 565.6, 781.77] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | Bằng sáng chế | Đúng | — | Tên giấy tờ khớp cụm từ in trên ảnh; chỉ nhận dạng loại chứng cứ, không tự nối yêu cầu nộp. |
| llm_added:node:EvidenceType:17 | ocop:llm_entity:68ce11a3d1d05281a169989d | VN.OCOP.QD1489.2025 p3 | ocop:evidence:8499ca172a4bacd0138f80e6 | [87.1, 408.0, 537.01, 427.2] | c8feaadc85cece82579b90aaf7b5899920630f1546d08ddd3860c75cb388e4b7 | Báo cáo đánh giá của UBND cấp xã | Đúng | — | Tên giấy tờ khớp cụm từ in trên ảnh; chỉ nhận dạng loại chứng cứ, không tự nối yêu cầu nộp. |
| llm_added:node:EvidenceType:18 | ocop:llm_entity:73097c987f5b5b41b369b4eb | VN.HATINH.THANHSEN.2026 p2 | ocop:evidence:3c8f9b60a02ae32e53de94ee | [29.03, 248.64, 567.25, 622.32] | b7abbcf2f519ba9adfd01f9a6794101dbc6da6c0c3906bf3346d238ad768d827 | Phiếu đăng ký theo Mẫu số 01, Phụ lục, lục m | Sai | OCR | Thanh Sen p2: nhãn OCR ghi Phụ lục m, ảnh in Phụ lục III. LLM giữ nguyên lỗi OCR; không sửa dữ liệu theo ảnh. |
| llm_added:node:EvidenceType:19 | ocop:llm_entity:34be09589f1a7bd669d82c6a | VN.OCOP.QD26.2026 p5 | ocop:evidence:0985475f3d257990af859e59 | [97.43, 298.8, 546.44, 332.16] | 1916672a65212ad2591e2cc91718c626717c4f81b81457743da4374a72dfdd7a | báo cáo đánh giá của Tổ tư vấn Hội đồng cấp tỉnh | Đúng | — | Tên giấy tờ khớp cụm từ in trên ảnh; chỉ nhận dạng loại chứng cứ, không tự nối yêu cầu nộp. |
| llm_added:node:EvidenceType:20 | ocop:llm_entity:2636a1f3e5e3d3d609c2bd05 | VN.OCOP.QD1489.2025 p4 | ocop:evidence:f9793241c65936327f959696 | [88.08, 208.99, 537.6, 239.94] | c8feaadc85cece82579b90aaf7b5899920630f1546d08ddd3860c75cb388e4b7 | Báo cáo đánh giá của UBND cấp xã về một số tiêu chi (theo quy định tại điểm a, khoản 1 và biểu mẫu số 3) | Đúng | — | Tên giấy tờ khớp cụm từ in trên ảnh; chỉ nhận dạng loại chứng cứ, không tự nối yêu cầu nộp. |

---


## Hoàn tất trích xuất và bàn giao người duyệt — lượt tiếp tục 2026-10-19

Đang thực hiện Phần 4–8 theo yêu cầu mới: không áp dụng giới hạn dừng ba vòng
của các mục lịch sử bên dưới. Mọi quyết định duyệt thử chỉ dùng dữ liệu tổng hợp.

### Checkpoint Phần 4

`complete-knowledge-4` / `complete-graph-4` trong root tạm cũ: **902 nodes,
1979 edges, rejected=0; 0 shape violation, 24 pending_source**. Không ghi đè
snapshot resume-4c. `python -m pytest -q tests`: **527 passed, 1 skipped,
3 warnings in 21.58s**; extract+build 2,42s. Bốn test đỏ ban đầu tái hiện bốn
lỗi parser; một test mới sau đó lỗi fixture `KeyError: 'cells'`, đã sửa tìm
table unit theo kind; không thay kỳ vọng test hồi quy gốc.

Sửa tại `procedures.py` (_subjects và documents): nhận danh sách actor phối hợp;
chỉ tạo REQUIRES_EVIDENCE khi có cue đầu vào trước danh từ trong cùng mệnh đề.
Ba cạnh sai p7/p9 bị loại, có omission `document_role_not_explicit_input`.
Còn ba quan hệ đầu vào: tài liệu minh chứng Thanh Sen p4; phiếu kiểm nghiệm
trong ghi chú tiêu chí 9 của phiếu 1 và 3. `legal_structure.py:_issuer_lines`
ghép hai dòng cột trái QĐ525, giữ evidence riêng mỗi dòng nguyên văn.
`article_tree.py` dừng trước banner Phụ lục/Kèm theo, kể cả OCR `Phụ luc`:
Điều 3 QĐ1489 chỉ còn evidence p2; không còn gán nội dung p3/4 vào Điều 3.
Test tổng hợp: `tests/ocop/test_final_parser_fixes.py` (4 trường hợp).

`legend_proposals.py` kiểm lại geometry marker trên ảnh PDF SHA khớp, 300 DPI;
giữ image_marker_candidates gốc, thêm independent_marker_counts_candidate.
`star_requirements.py` bỏ marker bất đồng với omission
`option_star_geometry_disagreement`; không chép số dấu từ đọc ảnh. Test tổng
hợp mới trong `test_star_requirements.py`. Bốn MINIMUM_FOR p29 còn đủ.

Đã đọc lại ảnh QĐ525 p1, QĐ1489 p3, QĐ26 p7/p9/p10 và crop phóng lớn p31.
**Đính chính báo cáo trước:** crop p31 vùng (350,190,390,203) hiển thị bốn dấu
sao sau chữ điện tử, không phải năm; bốn component có kích thước gần nhau
(16–17)x(20–21) pixel. Giá trị điểm 5 của hàng không được dùng để suy ra năm
dấu sao. Cạnh p31 bốn sao không bị sửa theo kết luận đọc ảnh nhỏ trước đó.
Ở p30 hàng dưới 5 đại lý: bộ đếm độc lập thấy ba, cache cũ bốn; cạnh bị bỏ có
omission. Ảnh kiểm tra: `C:/Users/PC/AppData/Local/Temp/ocop-star31-detail.png`.
Listing lấy mẫu lại seed 20261019:
`C:/Users/PC/AppData/Local/Temp/ocop-complete-review-samples-4.json`.

### Checkpoint Phần 5 — tính tất định

Lấy mẫu lại còn phát hiện bare heading `Điều 12. Điều khoản chuyển tiếp` và
ghi chú bảng `Chú ý`/OCR `Chi áp dụng` bị tạo thành rule/option. Đã đọc ảnh
QĐ26 p13/p21/p31, thêm hai test tái hiện (đỏ), sửa ranh giới nominal/ghi chú;
11 test liên quan đạt. Snapshot `complete-knowledge-4b` / `complete-graph-4b`:
**899 nodes, 1974 edges, rejected=0, 0 violation, 24 pending_source**,
extract+build 3,48s; signature label/attributes Criterion/ScoreOption phiếu 1
**giống hệt complete-4**. Pytest: **534 passed, 1 skipped, 3 warnings in 33,43s**.
Listing mới cùng seed: `C:/Users/PC/AppData/Local/Temp/ocop-complete-review-samples-4b.json`.
Ảnh p5 còn cho thấy tiêu đề danh sách “Hồ sơ ... do UBND cấp tỉnh chuẩn bị,
bao gồm:” bị nhận làm bước; đã thêm test và bỏ nominal heading này, giữ bước
“UBND cấp tỉnh chuẩn bị hồ sơ”. 27 test procedure/parser đạt. Đang đối chiếu
snapshot sau sửa này, chưa dùng số precision lịch sử thay cho phép đo mới.

Lệnh extract qua module không có `--max-pages` bị chặn đúng với
`RuntimeError: PDF PageArtifact manifest not complete`; build tiếp theo thiếu
manifest cũng thất bại FileNotFoundError. Đã gọi API extract với max_pages=999
cho snapshot debug, không sửa manifest thành complete và không nới cổng.

`pdf_pipeline.py:365`: warm-up trên trang scan đầu tiên theo source_id đã sắp
xếp của registry khóa (Thanh Sen p1), trước trang OCR thật đầu tiên không có
cache; bỏ kết quả, không ghi PageArtifact/cache, ghi manifest. Cache-hit và
native-only không warm-up. Fingerprint PARSER_VERSION đã đổi vì bao gồm mã
pipeline. Test tổng hợp trong `test_smoke_pages.py` kiểm cả hai nhánh.

Ba tiến trình mới, 300 DPI: A chỉ p29, B chỉ p29, C p28 rồi p29. So sánh trực
tiếp toàn bộ dict PageArtifact p29: **A = B = C, không có trường khác biệt**.
Output `complete-warm-a/b/c`, cache riêng cùng tên; manifest ghi warm-up
A 169,000s, B 141,703s. Log ngoài repo `ocop-complete-warm-{a,b,c}.log`.
PowerShell đánh dấu exit 1 vì NativeCommandError khi thư viện ghi warning
stderr; cả ba đã ghi manifest và kết quả hoàn chỉnh, không có traceback OCR.
Không tải/cài model mới. Kết quả score phải đọc ảnh riêng; tính tất định không
đồng nghĩa độ chính xác.

### Checkpoint Phần 8 — mã và thử nghiệm tổng hợp

Đã thêm review queue/ledger/projection tại `ai_core/graph/ocop/review.py`, CLI
`tools/cli.py review`, API `backend/api/ocop_review_routes.py` và trang Người
duyệt `frontend/src/ocop/Review.tsx`. Hướng dẫn tại
[OCOP_HUMAN_REVIEW.md](OCOP_HUMAN_REVIEW.md). Crop render 300 DPI từ PDF đã
kiểm SHA; runtime ngoài source tree. P1 không có duyệt hàng loạt.

Thiết kế: **duyệt entity không kéo theo duyệt evidence span/unit**. Người duyệt
phải duyệt riêng toàn bộ EvidenceUnit mà entity trích dẫn. Cạnh cần quyết định
riêng, evidence đã duyệt và cả hai đầu verified. Correct giữ nguyên knowledge
OCR và machine_candidate, ghi asserted_correction trong projection. Quyết
định append-only, fsync, khóa ghi; hash lệch quay về candidate/cần duyệt lại.
Pipeline kiểm digest ledger khi reuse graph. Các liên kết phụ thuộc trên trang
duyệt giúp mở evidence unit và hai đầu cạnh đang chờ.

Test `test_human_review.py`: stale hash, reject, correct giữ None OCR gốc,
không cascade proof, cạnh chờ một đầu, graph bình thường verified_only thấy
node đã duyệt, API và crop SHA. Toàn bộ chỉ dùng PDF tổng hợp trong tmp_path;
**không có quyết định agent trên corpus thật**. Lần thử đầu graph tool thiếu
index tổng hợp (`FileNotFoundError index/manifest.json`), đã bổ sung fixture.
Build frontend và TypeScript đạt (vite 1750 modules, 9,79s). `npm ci
--ignore-scripts` dùng lock hiện có; không sửa lock. Test hygiene sau đó bắt
tên v1/v2 của thư viện trong node_modules; đã chuyển dependency được tạo sang
root tạm, không nới test. Pytest toàn bộ sau đó đạt **531 passed, 1 skipped,
3 warnings in 25,79s**. Sau khi thêm kiểm tra ưu tiên và phụ thuộc: năm test
review đạt trong 3,55s.

Build_graph cuối checkpoint Phần 5 trên knowledge đã sửa: **902 nodes,
1979 edges, rejected=0** (`complete-graph-5`, 3,03s gồm xuất preview queue).
Queue preview, chưa phải full corpus: **2881 mục**, P1=270, P2=114,
P3=2497 trước khi bổ sung ưu tiên kiểm số học chưa đủ dữ liệu. Không có
verified hoặc quyết định người duyệt. Preview:
`data/processed/ocop/complete-review-preview.jsonl` trong root tạm.

Đọc lại ảnh QĐ26 p29: hàng ghi chú “Không đánh giá những sản phẩm…” không
có điểm in ở cột phải; không thể tính nó là ô điểm bị OCR bỏ sót. Grid có 33
hàng nhưng chỉ 32 ô có điểm in, 30 giá trị được nhận dạng trong cả ba lượt
mới. Hai ô còn thiếu là tiêu chí 3.2 (ảnh: 1), bbox
`[486.90,640.07,562.66,667.19]`, và phương án đầu của 3.2 (ảnh: 0), bbox
`[487.07,666.71,562.82,693.11]`. Giá trị máy vẫn rỗng/None, không chép từ ảnh.
Mốc 31/33 trong yêu cầu **chưa đạt**, được ghi là giới hạn OCR và chuyển sang
duyệt P1; không nới cổng hay coi tính tất định là độ chính xác.

### Build corpus đang chạy

Lệnh chính thức `python tools/cli.py run --root
C:/Users/PC/AppData/Local/Temp/ocop-structure-run1 --build-only --dpi 300
--no-llm` chạy nền, log `C:/Users/PC/AppData/Local/Temp/ocop-complete-full-build.log`.
Worker QĐ26 dùng cùng cache mới, output `complete-qd26-pages`, log
`ocop-complete-qd26.log`. Chưa công bố độ phủ/evaluator trước khi build xong.
Không tạo data/processed trong repo. Một lệnh chèn checkpoint bằng Python qua
PowerShell thất bại `AssertionError` do encoding chuỗi tìm kiếm; không ghi file,
đã dùng patch UTF-8 để cập nhật.

Các checkpoint Phần 5–8 và precision/evaluator cuối sẽ cập nhật ở đây sau
khi chạy; các số liệu phía dưới là lịch sử, không phải kết quả của lượt này.

---

## Tiếp tục với cổng citation đã sửa — 2026-10-19

**Phần 2 đạt; Phần 3 đã thực hiện; Phần 4 chưa đạt sau ba vòng, dừng theo
quy tắc của nhiệm vụ. Phần 5–7 chưa chạy.** Snapshot cuối mới là
`resume-knowledge-4c` / `resume-graph-4c` trong
`C:/Users/PC/AppData/Local/Temp/ocop-structure-run1/data/processed/ocop`:
**910 nodes, 2012 edges, rejected=0, 0 cạnh trùng**. Đây vẫn là
`partial_debug_not_production`, không phải corpus đầy đủ hoặc index đã đồng bộ.
Snapshot gốc và các snapshot cleanup cũ không bị ghi đè.

### Phần 2 — sửa cổng theo nghĩa nghiệp vụ, đạt vòng 1

`ai_core/knowledge/ocop/shapes.py:21` và `:23` khai báo riêng ATOMIC_TYPES và
CONTAINER_TYPES đúng các loại trong yêu cầu. Ngưỡng 0,35 chỉ áp dụng nút nguyên
tử. Mọi bbox có geometry trang đều được kiểm nằm trong trang (`:87`); nút chứa
phải khớp bbox hợp các dòng quote cả hai chiều (`:98`), không chỉ kiểm rằng bbox
không quá rộng. Kiểm quote vẫn dùng literal quote_lines, không fuzzy match hay
sửa OCR. Kiểm thuộc tính/cha và duplicate graph đã có được giữ nguyên.
Mỗi mục có severity; thiếu trang phiếu là `pending_source` (`:76`), các lỗi khác
là `violation` (`:39`); `severity_counts` tại `:108`. Danh sách `violations`
vẫn chứa cả hai mức để tương thích báo cáo cũ; cổng đọc severity thay vì lấy
tổng độ dài danh sách.

Cổng cũ sai vì SourceDocument/Article/Clause có thể trích nguyên nhiều đoạn;
diện tích lớn không chứng minh citation sai. Phiếu ở index p17 không chứng minh
đã có trang phiếu. Đây là sửa định nghĩa kiểm tra theo yêu cầu mới, không sửa
bbox/dữ liệu để né cảnh báo. Trong 71 mục cũ, 43 cảnh báo diện tích của nút chứa
không còn là lỗi diện tích; 24 mục chuyển pending; bốn ref nguyên tử thật sự
được sửa phân đoạn.

`ai_core/knowledge/ocop/procedures.py:48` tách ở đầu actor mới hoặc tiêu đề chữ
hoa, giữ nguyên các dòng wrap và nguyên văn quote. Ở Thanh Sen p4 dùng đúng hai
đầu đoạn UBND và tiêu đề THÔNG TIN LIÊN HỆ. Mục 6 không còn lẫn trong bước.
Đã đọc ảnh PDF p4 (render mới ngoài repo): đoạn đề nghị y=418,80–520,08;
đoạn hướng dẫn y=536,40–617,52; hai đoạn đều kết thúc trước khối liên hệ.
Authority có ref dòng tên và ref hành động trong đúng đoạn; EvidenceType ở
vòng này dừng ở đoạn thứ nhất. Bốn ref rộng cũ được thay bằng ref đúng đoạn,
không chèn dấu câu. Sang Phần 3 tên EvidenceType tiếp tục được cắt về
`tài liệu minh chứng`.

| Snapshot / mức độ | violation | pending_source | nodes / edges / rejected |
|---|---:|---:|---:|
| cleanup-2c, diễn giải lại bằng cổng mới trước sửa đoạn | 4 | 24 | 962 / 2125 / 0 |
| resume-2a, sau sửa | **0** | **24** | **964 / 2130 / 0** |
| resume-3c | 0 | 24 | 923 / 2041 / 0 |
| resume-4c | 0 | 24 | 910 / 2012 / 0 |

24 pending là các phiếu **2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16,
17, 18, 19, 20, 21, 22, 23, 24, 25, 26**. ID, evidence, trang/bbox/quote/SHA
có trong business_quality.json của từng snapshot. Không dựng cây giả.

Test mới `tests/ocop/test_shapes.py:67`, `:79`, `:85`: sáu loại nút chứa có
quote lớn hợp lệ nhưng bbox ngoài trang bị bắt; bbox thiếu dòng quote cũng bị
bắt; pending không mang severity violation. Test ngưỡng nguyên tử cũ vẫn chạy.
`tests/ocop/test_procedures.py:7` tái hiện mất dấu chấm bằng dữ liệu tổng hợp.
Lệnh test tập trung ban đầu: **9 failed, 21 passed** (đỏ có chủ đích trước sửa);
sau sửa **30 passed**. Cuối Phần 2: `python -m pytest -q tests`:
**512 passed, 1 skipped, 3 warnings in 22.13s**.

### Phần 3 — bí danh, loại giấy tờ và temporal candidate

- `configs/ocop_authorities.json:1` và `ai_core/knowledge/ocop/authorities.py:1`:
  danh mục bí danh ứng viên, chuẩn hóa case/dấu/khoảng trắng; ánh xạ vị trí
  normalize trở lại chuỗi OCR gốc. Chủ tịch và UBND, Bộ trưởng và Bộ được giữ
  là các vai trò khác nhau. Label chuẩn và canonical_id là metadata candidate;
  quote không thay thành label chuẩn. ID node vẫn chứa source_id, không tạo
  quan hệ giữa hai văn bản chỉ vì dùng chung canonical_id.
- `procedures.py:206`: dùng catalog để định danh Authority, gộp evidence trong
  văn bản. Không gắn lại cả bước vào mọi Authority trực tiếp; actor kế thừa vẫn
  giữ anchor lẫn evidence trang hành động để giữ hợp đồng endpoint của graph.
- `procedures.py:108`: EvidenceType dùng cụm danh từ hữu hạn, không ăn tiếp
  mệnh đề `và gửi...`; loại hậu tố OCR kiểu `)ea`. `:282` loại các hàng đã có
  score hoặc được nhận làm ScoreOption khỏi trích giấy tờ. Knowledge/raw quote
  vẫn được giữ. `báo cáo Bộ...` được nhận là động từ báo cáo, không phải tên hồ sơ.
- `extractor.py:25`, `:411`, `:415`: câu có giá trị trong thời hạn 36 tháng
  thành RuleCandidate temporal có evidence, bao gồm local_guidance. Các quy
  tắc vẫn inert/candidate, không biên dịch thành hiệu lực hay ngày hết hạn.
- `knowledge_extract.py:37`–`:38`: fingerprint knowledge bao gồm module và
  config bí danh mới. Không đổi registry hoặc fingerprint PageArtifact ở đợt này.

Authority: cleanup-2c **26**, resume-3c **25**, cuối resume-4c **23**. Nhóm
trùng `(source_id, casefold(label))` trước/sau đều 0; không tuyên bố rằng đã có
26 nhãn trùng trong cùng văn bản. Danh mục mới giải quyết danh tính chung và
biến thể được quan sát; giảm sau đó còn do bỏ actor gán nhầm ở các bước.
Nhãn lặp giữa văn bản được giữ node riêng đúng yêu cầu. EvidenceType:
**41 → 10 → 5**; không còn nhãn hàng phương án kèm điểm hay `)ea`.
ProcedureStep: **61 → 52 → 46**; shape không có bước thiếu RESPONSIBLE_FOR.
Không suy từ việc giảm node ra recall hay precision tăng.

| Vòng Phần 3 | nodes / edges / rejected | Shape violation | Thời gian extract + build |
|---|---:|---:|---:|
| resume-3a | 943 / 2097 / 0 | 2 | 1,92s |
| resume-3b | 943 / 2095 / 0 | 0 | 2,05s |
| resume-3c | 923 / 2041 / 0 | 0 | 1,94s |

Hai violation vòng 1 là ref `báo cáo` bị hiểu là danh từ, xuất hiện nhiều nơi
trên p7 nên bbox hợp quá rộng. Đã sửa phân biệt động từ, không thu nhỏ bbox
bằng tay. Vòng 3 giới hạn kế thừa actor ở phần khai báo trước điểm chữ cái và
không coi danh sách phiếu/bản tự công bố là hành động chỉ vì câu con nhắc Bộ Y tế.
Các bài test mới ở `test_procedures.py:26`, `:40`, `:48`, `:57`, `:65`, `:71`
kiểm bí danh, tách văn bản, giữ quote không dấu, vai trò Chủ tịch, noun/noise,
hàng điểm, temporal và Bộ ở câu phụ. Ba lỗi test tập trung trung gian
`3 failed, 42 passed` gồm fixture chưa có khoản/trigger và hai cạnh
`edge_not_shared_by_endpoint` sau thu hẹp Authority; đã sửa fixture tổng hợp
và giữ evidence continuation đúng trang. Test endpoint gốc vẫn giữ kỳ vọng
rejected=0. Cuối Phần 3: **518 passed, 1 skipped, 3 warnings in 22.21s**.

### Đọc lại benchmark cũ và cổng hồi quy

Đã render/đọc ảnh QĐ26 p3–10, p13, p17–22, p28–32; QĐ1489 p1–4;
Thanh Sen p1–5; NĐ15 p4–5; NQ15 p2; QĐ525 p1/p3; NĐ43 p1; QĐ148 p2.
Ảnh nằm trong `C:/Users/PC/AppData/Local/Temp/ocop-resume-images`.

| Mẫu cũ | Đối chiếu lần này |
|---|---|
| QĐ26 p3, 0013 | Bộ NN&MT công nhận 5 sao vẫn có bước/actor và statement nguồn |
| QĐ26 p4, 0015–0016 | Mẫu 01/02 III và nội dung cập nhật vẫn ở Article/Clause/Point/FormTemplate; một lần OCR II vẫn candidate có cờ conflict, không đổi thành III |
| QĐ26 p5–6, 0017–0018 | 01 bản giấy + 01 điện tử vẫn có quote; kiểm tra/gửi hồ sơ kế thừa UBND xã và 15 ngày làm việc từ p5 sang p6; không gán UBND tỉnh nơi nhận làm actor |
| QĐ1489 p2, 0027 | Hai cấp tỉnh/trung ương còn trong Điều 1 khoản 2 và evidence; không cần bịa ProcedureStep cho sửa đổi pháp lý |
| Thanh Sen p1, 0030/0032 | Hạn trước 15/10/2026 và danh sách đối tượng nằm trong evidence; danh sách đối tượng không có actor cơ quan nên không ép thành ProcedureStep |
| Thanh Sen p2, 0033 | Mẫu 01/02 Phụ lục III còn trong FormTemplate/quote; đây là tham chiếu, không phải mẫu có trường đã quan sát |
| Thanh Sen p3, 0031/0034/0035 | UBND qua Phòng NN&MT, nội dung thay đổi và bao bì/nhãn vẫn trong evidence; APPLIES_IN còn. Nơi nhận không tự trở thành actor |
| Thanh Sen p4, 0037 | Khối liên hệ bà Hoàng Thị Hiền còn trong evidence riêng của trang, không ghép vào hai bước UBND |
| NĐ15 p4, 0072/0074/0075 | Tự công bố/ngoại lệ, Mẫu 01 I, sản xuất kinh doanh ngay và trách nhiệm vẫn trong Điều 4/5, Point và RuleCandidate; đã bỏ bước giả từ danh sách giấy tờ/câu phụ Bộ Y tế |
| NĐ15 p5, 0076–0077 | Thay tên/xuất xứ/thành phần phải công bố lại; nhóm đăng ký bản công bố vẫn ở Điều 5/6 và rule/quote |
| NQ15 p2, 0096–0097 | Ba Bộ cùng rà soát Luật ATTP; Bộ Công Thương về thương mại điện tử vẫn có RESPONSIBLE_FOR |

Các kiểm trên là kiểm thủ công về bảo toàn nội dung, không phải evaluator hay
khẳng định mọi ProcedureStep chính xác. Đối chiếu cấu trúc từ snapshot cũ với
cuối: signature label/attributes của toàn bộ Criterion/ScoreOption phiếu 1
**không đổi**; 207 ScoreOption, 82 Criterion, 5 StarLevel vẫn giữ. Bốn MINIMUM_FOR
có option p29 và 15 OWNED_BY QĐ525 còn đủ. Điều 11/12, hiệu lực và chuyển tiếp
vẫn giữ. Không sửa tám điểm None của phiếu 1. Mốc 45 ngày p9 tiếp tục có temporal
candidate, không tự gán một cơ quan nơi nhận làm actor.

### Phần 4 — precision thủ công, chưa đạt sau ba vòng

Listing thuần dữ liệu, seed **20261019**, tối đa 20/loại, shuffle từng stratum
văn bản rồi lấy round-robin. Công cụ tạm
`C:/Users/PC/AppData/Local/Temp/ocop_list_review_samples.py` chỉ liệt kê;
không có thuật toán chấm đúng/sai, không sinh gold label/test OCR.
Listing cuối `C:/Users/PC/AppData/Local/Temp/ocop-resume-review-samples-4c.json`
có **252 node và 229 edge**, đầy đủ citation/endpoint. SHA-256:
`529073676ec26cb7884a83d313b8c8789ec696c6a62ef2f74b11f957508756be`.
Đây là mẫu business projection (EntityType và RELATION_TYPES), không lấy
EvidenceUnit/Mention/CandidateFact hay lớp scoring/Condition debug đã loại.
Các loại không tồn tại không có mẫu, không báo precision 100% cho n=0.

Đánh giá bằng ảnh về loại, tên chính, thuộc tính đã xuất và ý nghĩa quan hệ;
không phải character accuracy của toàn bộ OCR. None/không đủ thông tin để
đối chiếu thuộc tính được ghi KXĐ, không chép giá trị ảnh vào output.
Precision = đúng/(đúng+sai), kèm KXĐ riêng; mẫu phân tầng nhỏ không đại diện
cho phân bố toàn corpus, không tính một precision tổng hợp.

| Node type | n | Đúng / sai / KXĐ | Precision ước lượng |
|---|---:|---:|---:|
| AdministrativeArea | 1 | 1 / 0 / 0 | 100% |
| Article | 20 | 19 / 1 / 0 | 95% |
| Authority | 20 | 20 / 0 / 0 | 100% |
| Clause | 20 | 18 / 2 / 0 | 90% |
| Criterion | 20 | 20 / 0 / 0 | 100% |
| CriterionSheet | 20 | 18 / 2 / 0 | 90% |
| EvidenceType | 5 | 5 / 0 / 0 | 100% |
| FormTemplate | 10 | 9 / 1 / 0 | 90% |
| LocalGuidance | 1 | 1 / 0 / 0 | 100% |
| Organization | 3 | 3 / 0 / 0 | 100% |
| Point | 20 | 20 / 0 / 0 | 100% |
| ProcedureStep | 20 | 19 / 1 / 0 | 95% |
| Product | 15 | 15 / 0 / 0 | 100% |
| ProductGroup | 6 | 5 / 1 / 0 | 83,33% |
| ProductSubgroup | 2 | 2 / 0 / 0 | 100% |
| RecognitionDecision | 1 | 1 / 0 / 0 | 100% |
| RecognitionRecord | 15 | 15 / 0 / 0 | 100% |
| RuleCandidate | 20 | 19 / 0 / 1 | 100% xác định; 19/20 toàn mẫu |
| ScoreOption | 20 | 16 / 1 / 3 | 94,12% xác định; 16/20 toàn mẫu |
| SourceDocument | 8 | 7 / 1 / 0 | 87,50% |
| StarLevel | 5 | 5 / 0 / 0 | 100% |

| Relation type | n | Đúng / sai / KXĐ | Precision ước lượng |
|---|---:|---:|---:|
| AMENDS | 1 | 1 / 0 / 0 | 100% |
| APPLIES_IN | 1 | 1 / 0 / 0 | 100% |
| BASED_ON | 1 | 1 / 0 / 0 | 100% |
| DECLARED_BY | 15 | 15 / 0 / 0 | 100% |
| DEFINES_GROUP | 6 | 5 / 1 / 0 | 83,33% |
| HAS_ARTICLE | 20 | 19 / 1 / 0 | 95% |
| HAS_CLAUSE | 20 | 18 / 2 / 0 | 90% |
| HAS_CRITERION | 6 | 6 / 0 / 0 | 100% |
| HAS_OPTION | 20 | 20 / 0 / 0 | 100% |
| HAS_POINT | 20 | 20 / 0 / 0 | 100% |
| HAS_RECORD | 15 | 15 / 0 / 0 | 100% |
| HAS_SUBCRITERION | 20 | 20 / 0 / 0 | 100% |
| HAS_SUBGROUP | 2 | 2 / 0 / 0 | 100% |
| MINIMUM_FOR | 20 | 18 / 2 / 0 | 90% |
| OWNED_BY | 15 | 15 / 0 / 0 | 100% |
| RECOGNIZES | 15 | 15 / 0 / 0 | 100% |
| REPLACES | 2 | 2 / 0 / 0 | 100% |
| REQUIRES_EVIDENCE | 8 | 5 / 3 / 0 | **62,50%** |
| RESPONSIBLE_FOR | 20 | 20 / 0 / 0 | 100% |
| USES_SHEET | 2 | 2 / 0 / 0 | 100% |

Nhật ký thủ công sau đây định danh từng ngoại lệ bằng **loại + số thứ tự
1-based trong listing cuối**. Các mục còn lại của mỗi loại là đúng theo tiêu
chí trên; không còn mục chưa đọc trong mẫu cuối. Các kết quả này chỉ nằm trong
báo cáo thủ công, không nạp lại pipeline làm nhãn chuẩn.

| Mục sai/KXĐ | Ảnh / lý do và phân loại |
|---|---|
| Article #14; Clause #16/#19; HAS_ARTICLE #10; HAS_CLAUSE #4/#12 | QĐ1489 p2–4: phụ lục p3/4 bị nối vào Điều 3 thi hành p2. Có tiêu đề Phụ lục trên ảnh; lỗi parser ranh giới tài liệu, còn lại |
| CriterionSheet #5/#11 | QĐ26 p17: ảnh là Vải / Tinh dầu; OCR là vài / Tỉnh dầu. Lỗi OCR, giữ nguyên candidate |
| FormTemplate #7 | QĐ26 p4: ảnh Mẫu 02 III, OCR II. Đã có cờ conflict, vẫn là sai so với ảnh, không sửa thành III |
| ProcedureStep #19 | QĐ26 p10: hai actor Chủ tịch UBND tỉnh **và** Bộ trưởng; output mới nhận Bộ trưởng. Lỗi parser phối hợp chủ ngữ, còn thiếu actor thứ nhất |
| ProductGroup ID 09565fbd962b2a0a99a82f7f; DEFINES_GROUP #3 | QĐ26 p2: dược liệu bị OCR thành được liệu. Không sửa nhãn từ ảnh; <90% do một mẫu OCR trong n=6; đề xuất cải thiện OCR, đo lại sau làm nóng |
| SourceDocument #1, ID 40e84ec34ef4ca036b6bf4d6 | QĐ525 p1: issuer chỉ lấy ỦY BAN NHÂN DÂN, thiếu địa danh/vai trò Chủ tịch trong văn bản. Parser metadata còn thiếu; 87,5%, cần giữ multiline issuer với evidence, chưa sửa trong ba vòng này |
| RuleCandidate #2 KXĐ | QĐ26 p32: quote ghi chú sao OCR hỏng nặng, không xác nhận toàn mệnh đề/mapping chỉ từ quote; không coi candidate là diễn giải verified |
| ScoreOption #3/#5/#14 KXĐ | QĐ26 p21/p29: points_candidate None; ảnh có ô điểm nhưng giữ None, không điền từ ảnh |
| ScoreOption #4 sai | QĐ26 p30: ảnh dấu ≥5, OCR `2 5`; số điểm 3 đúng nhưng điều kiện lượng đại lý sai. Lỗi OCR, không sửa điều kiện bằng ảnh |
| MINIMUM_FOR #5 | QĐ26 p31: ảnh năm sao sau phương án có truy xuất điện tử, image_marker_candidate cho bốn. Lỗi nhận dạng marker ảnh |
| MINIMUM_FOR #15 | QĐ26 p30: phương án dưới 5 đại lý in ba sao, image_marker_candidate cho bốn. Lỗi nhận dạng marker ảnh |
| REQUIRES_EVIDENCE #3/#4 | QĐ26 p9: hồ sơ minh chứng không rõ ràng là điều kiện tổ chức kiểm tra thực tế, không phải một yêu cầu nộp loại hồ sơ. Lỗi parser vai trò/điều kiện, còn lại |
| REQUIRES_EVIDENCE #6 | QĐ26 p7: văn bản trong hành vi cơ quan ban hành/gửi kết quả bị gán làm đầu vào. Lỗi parser đa hành động trong cùng đoạn, còn lại |

Các loại <90% đã có nguyên nhân: ProductGroup/DEFINES_GROUP là OCR nguyên văn;
SourceDocument và REQUIRES_EVIDENCE còn lỗi parser thật. Các lỗi parser sau
ba vòng là lý do **chưa đạt Phần 4**, không dùng shape=0 để cho qua.
Mẫu trước đó cũng phát hiện ghi chú `Chú ý:` p31 được nhận làm ScoreOption và
bare heading Điều khoản chuyển tiếp được nhận làm rule; mẫu cuối không chọn
chúng. Không coi việc không xuất hiện trong mẫu lại là đã sửa các lỗi đó.

| Vòng sửa Phần 4 | Sửa / kết quả | nodes / edges / rejected |
|---|---|---:|
| resume-4a | Giữ actor title qua wrap; loại nơi nhận lên/từ; tách Thành phần/Nơi tiếp nhận/bullet; bỏ văn bản đang ban hành khỏi danh từ giấy tờ | 920 / 2033 / 0 |
| resume-4b | Chỉ kế thừa actor từ khai báo kết thúc bằng dấu hai chấm; không dùng một hành động trước đó làm khai báo chung; bỏ tiêu đề Sửa đổi/Bãi bỏ | 913 / 2018 / 0 |
| resume-4c | Cần ngữ cảnh hồ sơ/minh chứng cho giấy tờ thủ tục; loại một số hành động tạo văn bản đầu ra | 910 / 2012 / 0 |

Test mới `test_procedures.py:78`, `:87`, `:97`, `:106`. Lấy mẫu lại các vòng
bằng cùng seed, giữ riêng các listing 4a/4b/4c; không dùng tăng/giảm của mẫu khác
nhau làm chứng minh thống kê. Cuối Phần 4:
**522 passed, 1 skipped, 3 warnings in 22.68s**.

### Trước/sau chín vấn đề và giới hạn

| Vấn đề | cleanup-2c | resume-4c |
|---|---|---|
| 1. Cạnh trùng | 0 | 0, kiểm lại triples trực tiếp |
| 2. Authority | 26 | 23; canonical_id nguồn riêng; 0 nhóm trùng nhãn trong văn bản |
| 3. ProcedureStep | 61 | 46; shape actor=0 lỗi, nhưng mẫu còn thiếu một actor phối hợp |
| 4. Node có ref >35% | 1/61 ProcedureStep, 1/26 Authority, 1/41 EvidenceType | **0/46, 0/23, 0/5** |
| 5. EvidenceType | 41, còn hàng điểm/rác/đuôi câu | 5 cụm danh từ; còn lỗi vai trò ở REQUIRES_EVIDENCE, chưa thể coi hồ sơ đúng toàn bộ |
| 6. Lớp hàng điểm trùng | debug knowledge, không trong agent graph | giữ nguyên lựa chọn projection; 207 ScoreOption và dữ liệu debug vẫn giữ |
| 7. Condition sao | 0 agent-facing | 0 agent-facing; MINIMUM_FOR vẫn unverified |
| 8. Nhãn văn bản | số hiệu khi có nguồn/registry | giữ; Thanh Sen không có document_number nên còn source_id fallback, không bịa số hiệu; issuer QĐ525 chưa đủ |
| 9. Đủ phiếu | 26 index, hai cây | chưa OCR/mở rộng; 24 pending_source còn nguyên |

Toàn bộ 981 business entity và 691 business relation của knowledge cuối vẫn
`candidate`, không thiếu SHA trong ref entity. Graph dùng `needs_review` cho
ứng viên. Không cập nhật index production hoặc dùng điểm/sao để xếp hạng hay
đánh giá hồ sơ. Không chạy LLM; không có OCR mới trong đợt tiếp tục này.
Không sửa PDF, `configs/ocop_sources.json`, lock; không tạo `data/processed`
trong repo. Giữ các thay đổi working tree có sẵn của người dùng.

### Test, thời gian, lỗi lệnh và phần chưa làm

| Kiểm tra toàn bộ tests | Kết quả / thời gian |
|---|---|
| Sau Phần 2 | 512 passed, 1 skipped, 3 warnings; 22,13s |
| Phần 3 vòng 2 | 517 passed, 1 skipped, 3 warnings; 21,49s |
| Cuối Phần 3 | 518 passed, 1 skipped, 3 warnings; 22,21s |
| Phần 4 vòng 2 | 521 passed, 1 skipped, 3 warnings; 23,59s |
| Cuối Phần 4 | 522 passed, 1 skipped, 3 warnings; 22,68s |

Lệnh extract_artifacts + build_graph dùng pages-part5-final đã có, max_pages=9999
để khai báo đây là chạy debug trên manifest partial, allow_partial=True khi
build; semantic_client=None mặc định. Không làm giả complete/ready. Thời gian
hàm đo bằng monotonic của ba vòng Phần 4: **2,39s / 2,48s / 2,25s**.
Phần 2 lệnh extract/build mất khoảng 3,14s theo tool. Đồng hồ UTC được đọc
từ 11:44:33 đến 11:56:23 (**710s**) cho khoảng công việc Phần 3/4 đã đo;
không có mốc clock từ đầu Phần 2 nên không gọi đây là tổng end-to-end.

Một lệnh chỉ in mẫu bị lỗi sau khi in REQUIRES_EVIDENCE:

```text
exit=1
KeyError: 'properties'
```

Nguyên nhân: một số edge không có thuộc tính tùy chọn; lệnh đọc trực tiếp
`r['properties']`. Đã dùng lệnh liệt kê riêng không đòi field này để đọc đủ
RESPONSIBLE_FOR; không thay graph hay sinh nhãn tự động. Không có lỗi OCR/
extract/build ở các vòng cuối. Các lỗi test trung gian đã ghi ở trên.

Phần 5 chưa sửa run_pipeline/warm-up, chưa đổi fingerprint OCR và chưa so hai
tiến trình p29. Phần 6 chưa OCR Phụ lục II, chưa kiểm cây ba nhóm khác và chưa
đưa pending về 0. Phần 7 chưa build locked corpus đầy đủ, chưa chạy evaluator
mới; **không có source-hit/page-hit mới** hay phân tích mười câu sai để so với
53,91% / 38,26%. Các công việc này dừng vì cổng Phần 4 còn lỗi sau ba vòng,
không phải do lỗi lệnh evaluator mới.

---

Các mục dưới là lịch sử lần chạy trước; trạng thái mới nhất ở mục tiếp tục
phía trên.

### Kiểm tra lại trạng thái dừng — 2026-10-19

Đọc trực tiếp artefact `cleanup-graph-2c`: manifest ghi 962 nodes, 2125 edges,
rejected=0; đếm lại triples relation/source/target trong edges.jsonl có **0 nhóm
trùng**, rejected.jsonl có 0 byte. `cleanup-knowledge-2c/business_quality.json`
vẫn báo 47 citation_page_area và 24 sheet_source_not_observed. Đây là kiểm tra
artefact đã có, không phải một vòng extract/build hay đọc ảnh mới.

Chạy lại `python -m pytest -q tests`: **503 passed, 1 skipped, 3 warnings in
35.92s**, exit=0. Không OCR, không dùng LLM; `data/processed` trong repo không
tồn tại. Không sửa PDF, registry hoặc lock trong lần kiểm tra này.

Giữ trạng thái dừng sau ba vòng Phần 2 theo cổng chặn của nhiệm vụ. Chưa thực hiện
Phần 3–7; không có precision hoặc evaluator mới. Không coi việc test đạt hay
graph không trùng cạnh là đã phân loại xong các vi phạm bằng ảnh nguồn.

## Đợt làm sạch và mở rộng corpus — 2026-10-19

Phần 1 đạt cổng: graph mới `cleanup-graph-1`, knowledge `cleanup-knowledge-1`
trong root tạm cũ; snapshot gốc không thay đổi. Từ 1673/3036 xuống **1091 nodes,
2276 edges, rejected=0**. Có 113 nhóm cạnh trùng nếu tính mọi quan hệ (bao gồm
35 trường hợp cha đã nêu); sau sửa còn **0**, không mất citation nào của các
nhóm còn trong projection. ID cạnh theo relation/source/target; các evidence
unit được gộp vào evidence_unit_ids và citations; thuộc tính xung đột giữ riêng
attribute_candidates. Condition dấu sao 42→0; CriterionRowCandidate 333→0;
RuleCandidate scoring 207→0 trong graph. Knowledge giữ nguyên các lớp debug;
index đọc evidence/chunk riêng nên thay đổi projection không xóa dữ liệu
retrieval. RuleCandidate không phải scoring vẫn giữ 34 nút.

Nhãn RecognitionDecision/LocalGuidance/SourceDocument lấy số hiệu có evidence
hoặc registry. Đã đọc lại ảnh QĐ26 p18, p29, p13 và QĐ525 p3: cây phiếu 1,
bốn MINIMUM_FOR p29, Điều 11/12 và chủ thể các nhóm STT 1–4/5–9/10–15 không đổi.
Các thiếu điểm OCR vẫn None. Test mới `tests/ocop/test_graph_cleanup.py:1`
kiểm hợp nhất cạnh hai trang, bảo toàn knowledge, loại lớp debug và nhãn số hiệu.
`python -m pytest -q tests`: **489 passed, 1 skipped, 3 warnings (25.28s)**;
log `C:/Users/PC/AppData/Local/Temp/ocop-cleanup-part1-tests.log`.
Lệnh in manifest đầu tiên gặp UnicodeEncodeError cp1252 sau khi extract thành
công; chạy lại phần build với PYTHONIOENCODING=utf-8 thành công, không OCR lại.

### Phần 2 — chưa đạt, dừng sau ba vòng

Thêm kiểm khai báo tại `ai_core/knowledge/ocop/shapes.py:8` và `:23`, gọi từ
`ai_core/knowledge/ocop/quality.py:12`. Schema kiểm thuộc tính/kiểu chính xác
(không chấp nhận bool thay int), cha của ScoreOption/Criterion, người chịu trách
nhiệm của ProcedureStep hoặc authority_omission_reason, cây phiếu khi có tiêu đề
nguồn, 26 phiếu và 5 hạng sao cho nguồn framework. HAS_CRITERION của một phiếu
được hiểu là tối thiểu một cạnh, vì một phiếu có ba Phần A/B/C. Nhiệm vụ liên Bộ
được phép nhiều RESPONSIBLE_FOR; không coi nhiệm vụ chung là lỗi vì có nhiều Bộ.
Kiểm bbox có ngưỡng truyền cấu hình max_page_area_ratio=0.35, bbox_tolerance=2pt;
báo cờ diện tích riêng với vượt khối quote. Chỉ báo, không sửa điểm/dữ liệu.
`audit_graph_shapes` kiểm cạnh trùng; builder cũng được kiểm trực tiếp bằng
triples trên snapshot. Báo cáo knowledge giữ riêng raw_relation_duplicate_groups
vì nhiều dòng evidence của cùng quan hệ là hợp lệ trước projection.

Để xử lý vi phạm tìm được trong cổng này, đã siết bước thủ tục tại
`ai_core/knowledge/ocop/procedures.py:52`: chỉ giữ frame có chủ thể trực tiếp hoặc
kế thừa cùng khoản và hành động; thêm action_candidate/object_candidate. Không
tạo ProcedureStep từ Điều, Căn cứ, tiêu đề thủ tục, chữ ký/email và đoạn thiếu
frame. Đây là sửa vi phạm shape, **chưa phải hoàn tất Phần 3**: chưa có danh mục
bí danh cơ quan, chưa siết đầy đủ EvidenceType hay kiểm lại mọi mẫu benchmark.
Nội dung bị loại khỏi ProcedureStep vẫn trong evidence/Article/Clause; chưa
kiểm đủ chuyển các câu giá trị 36 tháng thành RuleCandidate temporal.

Sửa geometry tại `ai_core/processing/ocop/knowledge_extract.py:417` và
`ai_core/domain/ocop_citations.py:15`: lưu quote_lines gồm text/bbox/trang,
chỉ dùng nếu khớp nguyên dòng và đúng trang. Giữ toàn bộ SourceSpan/block_id
gốc. Không fuzzy match, không thay chữ OCR hoặc suy đoán bbox khi thiếu geometry.
Fingerprint knowledge thêm shapes.py và ocop_citations.py.

| Vòng / thư mục suffix | nodes / edges / rejected | Vi phạm cha | Citation >35% (lượt ref) | Phiếu thiếu trang |
|---|---:|---:|---:|---:|
| 1: cleanup-knowledge-2 / cleanup-graph-2 | 1091 / 2276 / 0 | 110 | 412 | 24 |
| 2: cleanup-knowledge-2b / cleanup-graph-2b | 962 / 2048 / 0 | 0 | 55 | 24 |
| 3: cleanup-knowledge-2c / cleanup-graph-2c | 962 / 2125 / 0 | 0 | 47 | 24 |

Mỗi knowledge có `business_quality.json` với toàn bộ ID, quote, trang, bbox và
SHA của từng vi phạm. Không chỉ giữ mẫu 30 dòng như báo cáo quality cũ.

| Nhóm vi phạm cuối | Số lượt | Phân loại / kiểm ảnh |
|---|---:|---|
| parent_cardinality | 0 | Đã sửa parser: bỏ bước thiếu frame; không gán UBND nơi nhận làm chủ thể |
| sheet_source_not_observed | 24 | Chưa có trang nguồn của phiếu; p17 chỉ là index. Không dựng cây giả |
| citation_page_area trên ProcedureStep/Authority/EvidenceType | 4 | Đã đọc Thanh Sen p4: lỗi parser còn lại do OCR mất dấu kết câu, chưa sửa đạt |
| citation_page_area trên SourceDocument/Article/Clause/RecognitionDecision | 43 | Cần phân loại từng ref tiếp; có trích nguyên khoản/văn bản dài hợp lệ. Chưa đọc đủ để khẳng định tất cả là lỗi hay hợp lệ |
| citation_exceeds_quote_block | 0 | Theo geometry hiện có; không chứng minh OCR đúng hay bbox đủ hẹp về ngữ nghĩa |

Bốn ref Thanh Sen p4 gồm hai quote rộng của **cùng một ProcedureStep**, một
Authority và một EvidenceType. Ảnh cho thấy phần “UBND phường ... đề nghị ...”
và “UBND phường ... sẽ hướng dẫn ...” là hai đoạn riêng, tiếp theo là thông tin
liên hệ. Output ghép cả tiêu đề mục 6 và phần liên hệ/thời hạn đến cuối trang;
EvidenceType “tài liệu minh chứng và gửi về UBND...” kéo theo phần còn lại.
Đây là lỗi parser phân đoạn trên chuỗi OCR mất dấu chấm, không được chữa bằng
chép dấu câu/giá trị từ ảnh. NQ15 p2 đã đọc lại: anchor danh sách ba Bộ được cắt
về dòng khai báo chung; QĐ26 p9 đã đọc lại: mốc 45 ngày không có chủ thể trực
tiếp nên không tự gán Authority. Chưa đối chiếu toàn bộ 47 ref còn lại.

Theo quy tắc ba vòng, **dừng tại Phần 2**, không chuyển sang Phần 3–7. Chưa
chạy lấy mẫu precision, làm nóng OCR, OCR đủ Phụ lục II hay build/evaluate corpus
đầy đủ; không báo số precision/source-hit/page-hit mới. Baseline người dùng cung
cấp là 53,91% / 38,26%, chưa có kết quả mới để so theo category hoặc phân tích
10 câu sai. Không chạy lại evaluator trên corpus thiếu trang.

### Trước/sau cho chín vấn đề

| Vấn đề | Snapshot gốc | Snapshot cuối cleanup-graph-2c |
|---|---|---|
| 1. Cạnh cha/cạnh trùng | 35 trường hợp cha; 113 nhóm nếu tính mọi relation | 0 nhóm trùng; Phần 1 kiểm bảo toàn mọi citation của nhóm còn trong projection |
| 2. Authority trùng nhãn | 27 nodes | 26 nodes; chưa hợp nhất bí danh, chưa đạt yêu cầu Phần 3 |
| 3. ProcedureStep/actor | 176, kiểm độc lập nêu 98 thiếu RESPONSIBLE_FOR | 61; shape không còn bước thiếu cha; chưa kiểm precision/recall, không coi giảm số lượng là bằng chứng chính xác |
| 4. Node có ít nhất một bbox >35% | ProcedureStep 120/176 (68,18%); Authority 24/27 (88,89%); EvidenceType 22/54 (40,74%) | 1/61 (1,64%); 1/26 (3,85%); 1/41 (2,44%) |
| 5. EvidenceType hàng điểm/rác | 54 nodes | 41; chưa siết danh mục/cắt cụm, còn lỗi kéo dài p4, chưa đạt |
| 6. Ba lớp biểu diễn hàng điểm | 333 CriterionRowCandidate, 241 RuleCandidate, 207 ScoreOption | graph: 0 CriterionRowCandidate, 34 RuleCandidate không scoring, 207 ScoreOption; knowledge giữ debug |
| 7. Condition dấu sao | 42 + HAS_CONDITION | 0 trong graph; MINIMUM_FOR giữ nguyên |
| 8. Nhãn văn bản | source_id | dùng số hiệu trích/registry khi có; không bịa số hiệu thiếu |
| 9. Độ phủ phiếu | 26 phiếu index, 2 USES_SHEET, 12 HAS_CRITERION | không mở rộng độ phủ; 24 phiếu chưa có cây được báo shape |

Không mất 15 OWNED_BY QĐ525 và bốn MINIMUM_FOR p29; giữ 207 ScoreOption,
82 Criterion, 22 Article, 53 Clause, 75 Point và 5 StarLevel. Đây là kiểm hồi quy
cấu trúc, không thay thế kiểm precision từng loại và không xác nhận mọi mẫu
thủ tục cũ sau khi siết frame. Snapshot gốc `graph/` không bị ghi đè; index cũ
không được coi là đã đồng bộ với graph thử mới.

### Test, lỗi lệnh và thời gian ghi nhận

Test mới: `tests/ocop/test_graph_cleanup.py:1`, `tests/ocop/test_shapes.py:1`
(12 trường hợp), `tests/ocop/test_quote_line_spans.py:1`; thêm test loại tiêu đề,
căn cứ, giá trị chứng nhận và watermark trong `tests/ocop/test_procedures.py`.
Ba test cũ về thủ tục đã đổi cho đúng yêu cầu mới: không tạo bước chỉ từ nơi
nhận/đoạn thiếu actor; kiểm riêng hàm deadline không suy năm/không gộp hai mốc;
fixture hồ sơ thủ tục thêm chủ thể/hành động rõ ràng.

| Lần chạy pytest toàn bộ | Kết quả / thời gian |
|---|---|
| Phần 1 | 489 passed, 1 skipped, 3 warnings; 25.28s |
| Phần 2 vòng 1 | 501 passed, 1 skipped, 3 warnings; 23.30s |
| Phần 2 vòng 2 | 2 failed, 500 passed, 1 skipped, 3 warnings; 21.41s |
| Phần 2 vòng 3 | 502 passed, 1 skipped, 3 warnings; 20.62s |
| Kiểm cuối sau thêm test âm tính | **503 passed, 1 skipped, 3 warnings; 20.68s** |

Lỗi vòng 2 (log `C:/Users/PC/AppData/Local/Temp/ocop-cleanup-part2b-tests.log`):

```text
FAILED tests/ocop/test_extraction_retrieval.py::test_text_evidence_keeps_ocr_block_bbox_and_source_hash
AssertionError: block_id 'line:0' != 'vl:0'
FAILED tests/ocop/test_table_page_units.py::test_merged_line_fragments_keep_every_block_span
AssertionError: ['line:0', 'line:1'] != ['b0', 'b1', 'b2']
2 failed, 500 passed, 1 skipped, 3 warnings in 21.41s
```

Đã sửa bằng giữ nguyên spans/block_id và thêm quote_lines riêng; hai test gốc
không bị đổi kỳ vọng. Log cuối:
`C:/Users/PC/AppData/Local/Temp/ocop-cleanup-stopped-final-tests.log`.
Skip vẫn là test corpus phát sinh tùy chọn, vì không có data/processed trong repo.
Các lệnh extract+build ghi nhận khoảng 6.22s / 2.23s / 2.51s cho ba vòng;
thời gian giữa kết thúc test Phần 1 và kết thúc kiểm cuối khoảng 428s, không phải
thời gian OCR (đợt này **không OCR**). Không có đồng hồ tổng toàn lượt trước
lần test đầu nên không suy ra thời gian end-to-end chính xác.

Kiểm cuối: không có diff PDF, configs/ocop_sources.json hoặc lock; data/processed
trong repo không tồn tại. Mọi business entity/relation trong knowledge vẫn
candidate, không tự verified; graph giữ quy ước review_status=needs_review hiện
có cho candidate. Không dùng dữ liệu chưa xác minh để xếp hạng/kết luận hồ sơ.

---

Nội dung dưới đây là báo cáo đợt trích xuất trước, không phải kết quả hoàn tất
Phần 3–7 của đợt làm sạch này.

Ngày thực hiện: 2026-10-19. Các kết quả dưới đây là ứng viên máy trích xuất,
không phải xác minh pháp lý, điểm số hoặc kết luận hồ sơ.

Root thử nghiệm nằm ngoài repo:
`C:/Users/PC/AppData/Local/Temp/ocop-structure-run1`.
Root chạy lại QĐ1489 sau trang OCR phụ:
`C:/Users/PC/AppData/Local/Temp/ocop-structure-warm`.
Không chỉnh PDF nguồn, registry, hoặc tạo `data/processed` trong repo.
LLM không được bật.

## Phần 1 — đạt cổng sau lượt sửa thứ hai

Thay đổi:

- `ai_core/knowledge/ocop/contracts.py:26`: SourceDocument và các quan hệ
  OWNED_BY, BASED_ON, AMENDS, REPLACES, SUSPENDS trong hợp đồng nghiệp vụ;
  thuộc tính cạnh tại dòng 102; SHA-256 trong EvidenceRef tại dòng 76.
- `ai_core/knowledge/ocop/contracts.py:154`: kiểm tra số hiệu nguyên vẹn;
  `:159`: ngoại lệ xuyên tài liệu chỉ với đích khớp registry và bằng chứng số hiệu.
- `ai_core/knowledge/ocop/extractor.py:397`: OWNED_BY dùng chính chủ thể đã
  giải từ bản ghi công nhận, bao gồm ô gộp có chứng cứ rowspan.
- `ai_core/knowledge/ocop/legal_structure.py:28`: metadata trang đầu, hiệu lực,
  quy tắc chuyển tiếp và quan hệ văn bản. `:74` tránh lấy watermark làm cơ quan
  ban hành; `:124`, `:128`, `:137` sinh AMENDS, REPLACES và BASED_ON.
- `ai_core/processing/ocop/knowledge_extract.py:528`, `:542`, `:558`:
  truyền registry thật vào trích xuất/kiểm tra và lưu registry dùng cho build.
- `ai_core/graph/ocop/builder.py:86`, `:145`, `:193`, `:361`: kiểm tra SHA,
  kiểm tra giải quyết văn bản xuyên nguồn và giữ thuộc tính cạnh.
- Các endpoint trên đã tồn tại trong ontology; không thêm endpoint trùng.

Test mới: `tests/ocop/test_legal_structure.py` (9 test ở cổng, hiện 11 test tổng hợp): metadata,
không lấy ngày trong câu căn cứ làm ngày ký, watermark, hết hiệu lực không tạo
AMENDS nhầm, số hiệu ngoài/trùng registry, BASED_ON, OWNED_BY, chuyển tiếp
không thực thi, build giữ thuộc tính/SHA và không rejected.
Hai test bổ sung kiểm tra SUSPENDS với câu mở đầu điều khoản có số hiệu đăng ký
và tránh lấy số hiệu trong khoản khác làm đích hết hiệu lực/sửa đổi.

Đối chiếu ảnh:

| Trang | Đúng | Sai phát hiện và sửa | Thiếu được giữ unknown |
|---|---|---|---|
| QĐ26 p1 | 26/2026/QĐ-TTg; THỦ TƯỚNG CHÍNH PHỦ; 2026-05-22 | Không còn sai trong các trường được kiểm | Không |
| QĐ26 p13 | effective_from 2026-05-22; REPLACES tới 148 và 1489; expires_after_days=60; toàn văn Điều 12 thành temporal candidate | Không tạo AMENDS từ câu mô tả QĐ1489 | Không tính một ngày hết hiệu lực tuyệt đối khi nguồn chỉ ghi mốc tương đối |
| QĐ1489 p1–2 | 1489/QĐ-TTg; ngày ký 2025-07-06; AMENDS tới 148 | Lượt đầu trên OCR đã làm nóng chọn CHÍNH PHỦ trong watermark; lượt hai chọn đúng tiêu đề THỦ TƯỚNG CHÍNH PHỦ trước Số: | effective_from của 1489 để None: chưa triển khai suy ra từ “ngày ký ban hành” |
| QĐ525 p3 | 15 OWNED_BY: STT 1–4 Quang Hải, 5–9 Song Hải, 10–15 HTX Thụy Hương | Không | Không |
| QĐ525 p1 | BASED_ON tới 148/QĐ-TTg; không nối luật/nghị định ngoài registry | Không | Số/ngày trên phần mẫu trang đầu không đọc được thành giá trị xác định: None + omission |

Ảnh QĐ26 p13 thực tế ghi chuyển tiếp 60/30 ngày và trường hợp kéo dài tối đa
180 ngày. Giữ nguyên câu nguồn; không gán 90 ngày theo mô tả nhiệm vụ.
Ảnh cũng in lần nhắc thứ hai của QĐ148 với năm 2025; không tự sửa thành 2023.
Phân giải văn bản dùng số hiệu khớp registry, không dùng ngày nhắc lại đó.

OCR 300 DPI. Lượt smoke đầu có trang phụ QĐ525 nhưng đó là chữ gốc, nên
QĐ1489 p1 vẫn là lượt OCR đầu và không được dùng để chốt cổng. Đã chạy lại
QĐ148 p1 trước QĐ1489 p1 trong tiến trình mới, rồi chọn PageArtifact đã làm
nóng vào bản `pages-warm`; QĐ26 p1/p13 đều sau các lượt OCR khác.
Đổi phần trích xuất chỉ chạy lại extract_artifacts + build_graph, không OCR lại.

Kết quả ở cổng: **130 nodes, 247 edges, rejected=0**; **463 passed, 1 skipped**.
Artefact giữ lại tại `data/processed/ocop/knowledge-part1-final`,
`pages-part1-final`, và `graph-part1-final-manifest.json` trong root tạm.
Log pytest: `C:/Users/PC/AppData/Local/Temp/ocop-structure-part1-final-tests.log`.
Sau khi gộp metadata vào SourceDocument chuẩn trong builder, build lại chính
bộ knowledge đã lưu: **127 nodes, 247 edges, rejected=0** tại
`data/processed/ocop/graph-part1-recheck`. Chỉ bỏ ba node văn bản trùng danh tính;
không mất cạnh nghiệp vụ.
Hai lượt smoke đầu trả mã wrapper PowerShell 1 khi ghi cảnh báo thư viện qua
stderr (`NativeCommandError`); log vẫn chạy tới cuối, sinh index/graph và báo
partial root not_ready. Các lần extract/build trực tiếp trả 0, rejected=0.

## Phần 2 — đạt cổng sau lượt sửa thứ hai

Thay đổi:

- `ai_core/knowledge/ocop/article_tree.py:11`: cây SourceDocument → Article →
  Clause → Point. Tiêu đề/khoản/điểm có quote, trang, bbox, SHA và evidence ID.
  Chỉ kế thừa ngữ cảnh trên trang liên tiếp; thiếu trang hoặc gặp section/annex
  thì dừng. Điểm nối trang có cả bằng chứng khoản cha và ô văn bản trang sau.
- `ai_core/knowledge/ocop/contracts.py:26`, `:50`: Article/Clause/Point,
  HAS_ARTICLE/HAS_CLAUSE/HAS_POINT.
- `ai_core/graph/ocop/ontology.py`: Point và HAS_POINT; endpoint còn lại đã có.
- `ai_core/orchestration/ocop/tools.py`: thêm ba quan hệ cây vào traversal.
- `ai_core/processing/ocop/knowledge_extract.py:37`: fingerprint module mới.

Test mới: `tests/ocop/test_article_tree.py` (4 test tổng hợp): thứ tự khoản/điểm,
quote nguyên văn, nối trang có cả hai evidence và build rejected=0, ngắt khi
thiếu trang, chữ đ và chữ hoa trong ký hiệu điểm.

Đối chiếu ảnh:

| Trang | Kết quả |
|---|---|
| QĐ26 p1 | Điều 1 có khoản 1–2 |
| QĐ26 p2 | Điều 2 có khoản 1–3; Điều 3 có khoản 1–3, điểm a/b/c dưới khoản 1 |
| QĐ26 p3 | Đầu trang thuộc Điều 3 khoản 3, đủ điểm a/b/c/d/đ với evidence p2+p3; Điều 4 có khoản 1–3, điểm a/b dưới khoản 1; Điều 5 khoản 1 có trong nguồn nên cũng được giữ |
| QĐ26 p13 | Điều 11 khoản 1–2; Điều 12 khoản 1–3, điểm a/b thuộc khoản 2; không gắn c) đầu trang vào điều 5 từ p3 qua khoảng trống trang |
| NĐ43/2017 p1 (chữ gốc) | Điều 1 khoản 1–2; khoản 2 đủ a/b/c/d/đ/e |

Sai ở lượt đầu: OCR ghi `C) HẠNG 3 SAO` nên parser chỉ nhận chữ thường bỏ
điểm c. Sửa regex nhận cả chữ hoa, giữ quote OCR nguyên văn, chỉ chuẩn hóa
thuộc tính ký hiệu điểm. Lượt hai đủ năm điểm ở Điều 3 khoản 3.
Không còn sai/thiếu trong các điều/khoản/điểm thuộc phạm vi cổng đã kiểm.
Phần c) đầu p13 thiếu trang cha được ghi omission, không đoán cha.

OCR mới chạy với QĐ148 p2 làm trang quét phụ trước QĐ26 p2/p3, 300 DPI.
Các trang đã có cache được giữ; QĐ1489 p1 sau đó vẫn được thay bằng bản đã
làm nóng đã kiểm ở Phần 1.

Kết quả ở cổng: **224 nodes, 440 edges, rejected=0**; **467 passed, 1 skipped**.
Artefact: `knowledge-part2-final`, `pages-part2-final`,
`graph-part2-final-manifest.json` trong root tạm.
Log: `C:/Users/PC/AppData/Local/Temp/ocop-structure-part2-final-tests.log`.
Build lại sau thay đổi SourceDocument chuẩn: **219 nodes, 440 edges,
rejected=0**, lưu tại `data/processed/ocop/graph-part2-recheck`.

## Phần 3 — đạt cổng sau lượt thứ hai

Thay đổi: `ai_core/knowledge/ocop/star_requirements.py` sinh StarLevel từ Điều 3,
giữ cận dưới None nếu không được nêu; MINIMUM_FOR chỉ từ phương án có marker
và chú thích của cùng phiếu, không qua khoảng trống trang. Bổ sung StarLevel,
MINIMUM_FOR vào contracts/ontology và semantic traversal.
`ai_core/processing/ocop/legend_proposals.py` đề xuất marker của chú thích
từ cụm glyph ảnh lặp lại và số hạng OCR cùng block; kiểm SHA-256 trước khi
render PDF. Không OCR lại, không sửa quote, không đặt verified.
`knowledge_extract.py` gọi bộ đề xuất trong extract_artifacts và fingerprint
các module phụ thuộc.

Test: `tests/ocop/test_star_requirements.py` (6 test): ngưỡng có cận mở,
phương án thay vì tiêu chí, ảnh + chú thích cùng phiếu, thiếu trang/chú thích,
ánh xạ đúng câu chú thích thay vì giả định số dấu sao = hạng, glyph ảnh tổng
hợp và giữ quote OCR hỏng nguyên văn. Test cũ về Condition được bổ sung
kiểm tra không tạo MINIMUM_FOR khi thiếu chú thích.

Lượt đầu: không sinh MINIMUM_FOR vì chú thích p32 OCR thành
`44%. 3 sao; 44%-4 sao; đặc đ% 5 sao`. Đây là thiếu ánh xạ, không lấy số hạng
để đoán số dấu sao. Lượt hai: bộ đề xuất ảnh tìm đúng cụm 3/4/5 glyph tại
block 107/108, kèm bbox PDF và SHA nguồn; mỗi cụm ghép với số hạng OCR
trong chính block đó. Tất cả interpretation_verified=False.

Đối chiếu ảnh:

| Trang/phương án | Kết quả |
|---|---|
| Điều 3 p3 | 1 sao (None,30); 2 sao [30,50); 3 sao [50,70); 4 sao [70,90); 5 sao [90,100] |
| p29: Sản phẩm được trồng ở nhiều nơi… | MINIMUM_FOR 4 sao |
| p29: Đóng gói sáng tạo, bao bì đẹp | MINIMUM_FOR 3 sao |
| p29: Có nhãn, ghi nhãn… đúng quy định | MINIMUM_FOR 3 sao |
| p29: Ghi nhãn… mã truy xuất nguồn gốc điện tử | MINIMUM_FOR 4 sao |
| p29: phương án còn lại | Không có MINIMUM_FOR khác |
| p32 chú thích | Đủ ba cụm ký hiệu, evidence phương án p29 + chú thích p32 |

Giới hạn ngoài cổng p29: p28 còn thiếu hai marker `****` ở phương án hợp đồng
liên kết từ 75% sản lượng và phương án hồ sơ môi trường. OCR chưa tạo marker
candidate cho hai ô này; không đoán hoặc thêm tay. Hai phương án `*****` p28
đã có MINIMUM_FOR 5 sao. Đây chưa phải đo phủ toàn bộ 26 phiếu.

OCR 300 DPI, QĐ1489 p3 có ocr_engine=easyocr_vietocr và chạy trước p28.
Phiếu 3 có đủ trang 28–32 để kiểm ngữ cảnh.
Kết quả cổng: **693 nodes, 1190 edges, rejected=0**;
**475 passed, 1 skipped**. Artefact: `knowledge-part3-final`, `pages-part3-final`,
`graph-part3-final-manifest.json`. Log:
`C:/Users/PC/AppData/Local/Temp/ocop-structure-part3-final-tests.log`.

## Phần 4 — đạt cổng sau lượt đối chiếu phiếu 1 thứ hai

Thay đổi: `ai_core/knowledge/ocop/criterion_sheets.py` dựng 26 CriterionSheet
từ từng hàng index p17; nhóm từ Điều 2, phân nhóm/USES_SHEET từ chính tiêu đề
phiếu. DEFINES_GROUP, USES_SHEET, HAS_CRITERION có cả contracts/ontology;
DEFINES_GROUP được thêm vào traversal. A/B/C là Criterion level 0.
`extractor.py` nhận tiêu đề kèm ngoặc giải thích, dấu phẩy thay dấu chấm,
thiếu khoảng trắng sau số và phương án ngắn “Kém”/“Tốt”; bỏ các dòng hướng
dẫn/ghi chú khỏi phương án. `table_continuity.py` thêm min_columns nhưng
giữ mặc định 3; `knowledge_extract.py` gọi 2 cho bảng OCOP, lưu hint vào unit.
Nối trang giữ cả evidence của tiêu chí cha và hàng trang sau.

`ai_core/knowledge/ocop/quality.py` kiểm tổng con, max phương án, điểm phần
theo Điều 3 cùng nguồn và tổng phiếu. Ghi mismatch riêng với thiếu dữ liệu;
mọi chỗ có label, entity ID, hàng/trang/bbox/quote/SHA và giá trị ứng viên.
Không thay bất kỳ giá trị điểm nào.

Test: `tests/ocop/test_criterion_sheets.py` (5 test tổng hợp): index 26 phiếu,
6 nhóm, ba phần, nối trang có đủ hai evidence, không đoán khi thiếu continuity,
điểm sai được báo nhưng không sửa; tiêu đề có ngoặc/chấm phẩy/thiếu khoảng
trắng, phương án ngắn, hướng dẫn không thành phương án và reference phần A
không lấy điểm phần B khi chữ “điểm” bị OCR sai dấu.

Đối chiếu p17: đủ 26 dòng/số phiếu. Tiêu đề phiếu 1 p18 đúng nhóm Thực phẩm,
phân nhóm Thực phẩm tươi sống. Phiếu 1 p18–22 có **3 phần, 12 mục, 26 tiêu
chí con, 103 phương án**; đã đọc cả năm ảnh để đếm/so cây. Hàng đầu p19
thuộc 1.6 của p18; hàng đầu p20 thuộc 3.3 của p19. Không thêm phương án cho
tiêu chí 2.4 vì nguồn không in dòng phương án riêng.

Lượt đầu có bốn cảnh báo số học, đều là lỗi parser/checker, không phải điểm PDF:

| Cảnh báo ban đầu | Đối chiếu ảnh / nguyên nhân | Sửa |
|---|---|---|
| Mục 1: 18 so tổng con 15 | p18 có 1.4=3; OCR tiêu đề `1.4,` bị xem là phương án | Nhận dấu phẩy kết thúc số, giữ nguyên quote |
| Mục 3: 12 so tổng con 11 | p19 có 3.2=1; OCR `3.2.Đại…` thiếu khoảng trắng | Nhận tiêu đề số không có khoảng trắng |
| Phần C: 35 so tổng mục 33 | p22 có mục 11=2; OCR `11, HƯỚNG…` bị xem là phương án | Nhận tiêu đề mục kết thúc bằng dấu phẩy |
| Tiêu chí 6.3: max 3 so phương án max 2 | p21 in “Tốt”=3 và OCR cũng đọc 3; ngưỡng độ dài nhãn đã bỏ “Tốt” | Nhận phương án ngắn có chữ, không đoán điểm |

Lượt hai không còn mismatch số học. Các tổng nguồn/ứng viên tương ứng là
A=18+10+12=40; B=13+12=25; C=12+3+5+5+5+2+3=35; tổng 100.
Tám ô điểm trống trong OCR đều là lỗi thật, đã đọc ảnh xác nhận từng ô:

| Trang / hàng bảng (zero-based) | Phương án | Ảnh PDF in | Output |
|---|---|---|---|
| p19 r3 | Không sử dụng công nghệ… | 0 | None |
| p19 r8 | Trồng phổ biến nhiều tỉnh nhưng chất lượng nổi trội… | 1 | None |
| p19 r27 | Đại diện không phải nữ/đồng bào DTTS/người khuyết tật | 0 | None |
| p20 r2 | HTX xếp loại trung bình hoặc lợi nhuận tăng… | 1 | None |
| p20 r5 | Đơn đăng ký nhãn hiệu được chấp nhận/công bố | 1 | None |
| p21 r10 | Ngắn gọn, xúc tích | 1 | None |
| p21 r13 | Giống câu chuyện sản phẩm khác | 0 | None |
| p22 r1 | Không có (dinh dưỡng) | 0 | None |

Tám giá trị vẫn giữ None, không chép điểm đã đọc ảnh vào dữ liệu. Một mục
incomplete khác là 2.4: nguồn không có phương án để kiểm max, không phải OCR
bỏ phương án. Ngoài phiếu 1, các phiếu mới chỉ có index chưa được kiểm đủ
cây: group/subgroup vẫn None + omission nếu chưa thấy tiêu đề thật.
Tên nhóm dược liệu trong OCR Điều 2 là “được liệu…”; giữ nhãn quan sát đó,
không tự sửa. Dấu phân cách bị đọc thành dấu phẩy được ghi omission.

OCR 300 DPI với QĐ1489 p4 trước p17. Smoke dài bị lỗi sau khi OCR xong:

```text
TypeError: possible_continuations() got an unexpected keyword argument 'min_columns'
```

Nguyên nhân là hàm cũ đã được tiến trình nạp trước lúc sửa code. Không OCR lại:
chạy extract_artifacts + build_graph trong tiến trình mới trả 0 và hoàn tất.
Log giữ tại `C:/Users/PC/AppData/Local/Temp/ocop-structure-part4.log`.
Một test chất lượng cũ cũng từng bắt KeyError attributes với fixture tối giản;
đã sửa đọc thuộc tính tùy chọn, test cũ được giữ.

Kết quả cổng: **1205 nodes, 2068 edges, rejected=0**;
**480 passed, 1 skipped**. Artefact: `knowledge-part4-final`, `pages-part4-final`,
`graph-part4-final-manifest.json`. Log pytest:
`C:/Users/PC/AppData/Local/Temp/ocop-structure-part4-final-tests.log`.

## Phần 5 — đạt cổng trên các trang mẫu

Đã thêm `procedures.py`, Authority/ProcedureStep và RESPONSIBLE_FOR;
REQUIRES_EVIDENCE hỗ trợ Criterion và ProcedureStep với danh sách endpoint
được kiểm; thêm APPLIES_IN cho LocalGuidance/AdministrativeArea.
Đã có test tổng hợp cho đơn vị deadline, nối điều khoản qua trang, nơi nhận
không thành chủ thể, nhiều mốc không bị gộp, phạm vi địa phương, tham chiếu
Mẫu, nhóm các Bộ và không coi giấy chứng nhận đầu ra là hồ sơ phải nộp.
Đã OCR và đọc ảnh QĐ26 p4–10; Thanh Sen p1–6, NĐ15 p4/5 và NQ15 p2.
Root riêng có một lượt OCR QĐ1489 p4 trước khi chạy mọi trang cần kiểm, cùng
tiến trình, dpi 300. Không đổi thứ tự/metadata registry để làm nóng OCR.

Đối chiếu các mẫu benchmark (đây là kiểm tra thủ công, không phải metric evaluator):

| Nguồn/trang; mẫu | Kết quả đúng trong node/edge/statement và evidence |
|---|---|
| QĐ26 p3; 0013 | Bộ NN&MT công nhận 5 sao |
| QĐ26 p4; 0015–0016 | Mẫu 01/02 Phụ lục III; nội dung cập nhật nguyên liệu, công nghệ, bao bì, nhãn, công bố, kiểm nghiệm, thị trường, sản lượng, doanh thu và giấy tờ pháp lý |
| QĐ26 p5; 0017–0018 | 01 bản giấy + 01 bản điện tử; UBND cấp xã, 15 ngày làm việc |
| QĐ1489 p2; 0027 | Hai cấp tỉnh/trung ương trong Điều/Khoản và statement |
| Thanh Sen p1; 0030,0032 | Trước 15/10/2026, inclusive=False; các nhóm chủ thể đủ điều kiện |
| Thanh Sen p2; 0033 | Mẫu 01/02 Phụ lục III |
| Thanh Sen p3; 0031,0034,0035 | UBND phường qua Phòng NN&MT; nội dung thay đổi, hồ sơ bao bì/nhãn; APPLIES_IN phường Thành Sen |
| Thanh Sen p4; 0037 | Câu liên hệ bà Hoàng Thị Hiền có evidence p4 |
| NĐ15 p4; 0072,0074,0075 | Phạm vi tự công bố và ngoại lệ; Mẫu 01 Phụ lục I; sản xuất/kinh doanh ngay và tự chịu trách nhiệm |
| NĐ15 p5; 0076–0077 | Đổi tên/xuất xứ/thành phần phải công bố lại; thực phẩm bảo vệ sức khỏe thuộc nhóm đăng ký bản công bố |
| NQ15 p2; 0096–0097 | Cả ba Bộ Y tế, Công Thương, NN&MT chịu trách nhiệm rà soát Luật ATTP; Bộ Công Thương phụ trách thương mại điện tử |

Lượt đầu gán nhầm UBND tỉnh là chủ thể câu đề xuất ở QĐ26 p6 khoản 2b.
Ảnh xác nhận đây là nơi nhận: đã sửa từ dẫn nơi nhận, kế thừa UBND xã và
15 ngày làm việc từ p5 trong cùng khoản, giữ evidence cả p5/p6. Lượt hai đúng.
Mốc 15 ngày thường thu hồi p10 không bị gộp với ngày làm việc. Câu 45 ngày p9
thiếu chủ thể trực tiếp giữ None + omission. Dấu chấm OCR trong “tổ.chức” không
còn làm mất nhiệm vụ Chủ tịch xã tổ chức họp.

Một lần nhắc Mẫu 02 QĐ26 p4 OCR đọc Phụ lục III thành II: giữ candidate II kèm
cờ xung đột; các lần nhắc khác cho III đúng. Không tự sửa bằng ảnh. PDF địa phương
chỉ tham chiếu Mẫu, không chứa trường biểu mẫu (p5 phần cuối, p6 trắng):
reference_only=True, fields=None + omission. Chưa kiểm toàn bộ trường biểu mẫu
Phụ lục III trung ương.

Kết quả cuối 39 trang: **1673 nodes, 3036 edges, rejected=0**;
**488 passed, 1 skipped, 3 warnings in 21.01s**. Skip là test corpus phát sinh
tùy chọn vì repo không có data/processed. Log:
`C:/Users/PC/AppData/Local/Temp/ocop-structure-part5-final-tests.log`.
Snapshot cuối: `knowledge-part5-final`, `pages-part5-final`,
`graph-part5-final-manifest.json` trong root tạm đã nêu.

## Vị trí sửa theo phần và giới hạn còn lại

| Phần | File:dòng chính | Test tổng hợp |
|---|---|---|
| 1 | `legal_structure.py:29`, `extractor.py:153`, `contracts.py:169`, `ai_core/graph/ocop/builder.py:134` | `tests/ocop/test_legal_structure.py:1` |
| 2 | `article_tree.py:11` | `tests/ocop/test_article_tree.py:1` |
| 3 | `star_requirements.py:19`, `ai_core/processing/ocop/legend_proposals.py:39` | `tests/ocop/test_star_requirements.py:1` |
| 4 | `criterion_sheets.py:14`, `quality.py:62`, `ai_core/processing/ocop/table_continuity.py:5`, `ai_core/processing/ocop/knowledge_extract.py:482` | `tests/ocop/test_criterion_sheets.py:1` |
| 5 | `procedures.py:52` | `tests/ocop/test_procedures.py:1` |

Tên module ngắn thuộc `ai_core/knowledge/ocop/`. Schema chung:
`contracts.py:26`, `contracts.py:55`, `contracts.py:82`; endpoint:
`ai_core/graph/ocop/ontology.py:13`. Đã cập nhật traversal trong tools.py.
Giữ nguyên các thay đổi có sẵn của người dùng trong working tree.

Không sửa PDF/registry/lock; không tạo data/processed trong repo. Không dùng LLM
cho các cổng trên. Entity/relation nghiệp vụ máy trích vẫn candidate;
MINIMUM_FOR giữ interpretation_verified=False. Chưa kiểm toàn bộ 26 cây phiếu;
SUSPENDS có test tổng hợp nhưng chưa có đối chiếu dương tính trên PDF thật với
đích thuộc registry. Những thiếu sót OCR đã nêu ở phần 3–5 vẫn được giữ nguyên,
không dùng để kết luận hạng hay đánh giá hồ sơ.

## Manual PDF benchmark

Đã thử:

```text
python tools/evaluate_manual_pdf.py --root C:/Users/PC/AppData/Local/Temp/ocop-structure-run1 --out C:/Users/PC/AppData/Local/Temp/ocop-structure-manual-eval.json
exit=1
RuntimeError: Build the locked corpus first: python tools/cli.py run --build-only
```

Log: `C:/Users/PC/AppData/Local/Temp/ocop-structure-manual-eval.log`.
Source-hit/page-hit: **chưa đo được**. Các root hiện là bản build chọn trang,
không phải locked corpus đầy đủ; evaluator yêu cầu trạng thái ready.
Không bỏ qua kiểm tra readiness hoặc báo số liệu từ corpus thiếu trang.
