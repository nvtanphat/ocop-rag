# Đối chiếu trích xuất OCOP theo cấu trúc

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
