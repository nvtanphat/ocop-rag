# ADR 011: Quy phạm hạng nhất, danh tính khái niệm và truy xuất có chuỗi bằng chứng

Trạng thái: **Accepted**. Chủ repo cho phép sửa mã và cập nhật graph từ bằng chứng
hiện có; Markdown OCR và PDF nguồn giữ nguyên. Các phần dưới xác định hợp đồng
đích; phạm vi triển khai thực tế được phân biệt tại mục vận hành.
Không sửa EvidenceUnit/PDF hoặc gold để đạt bộ đo.

## Quyết định và ranh giới

Đồ thị có ba lớp liên kết: cấu trúc văn bản, thực thể miền có kiểu, và khái niệm
liên văn bản. Lớp là vai trò biểu diễn, không phải bằng chứng về độ tin cậy.
Nguồn hình thành, kết quả kiểm kỹ thuật và quyết định con người là các trục riêng.
Quan hệ suy ra giữ `derived=true` kể cả sau khi được chấp nhận; không xóa lịch sử
nguồn hình thành. Quyết định về danh tính không tự chứng minh quan hệ pháp lý.

Giữ một đồ thị công bố theo [ADR-001](001-single-graph-output.md). Không thêm
đường trả lời dùng đồ thị phụ để tránh cổng provenance, phiên bản hoặc điểm/sao.
Mọi trường ngôn ngữ và tham số thuật toán nằm trong cấu hình theo DEVELOPMENT.

## Danh tính và loại nút

| Nhóm | Mô hình đích | Tương thích với hiện tại |
| --- | --- | --- |
| Văn bản | Document, DocumentVersion, Provision, EvidenceUnit | Document tương ứng danh tính SourceDocument; Article/Clause/Point/Annex/Form giữ ID và có vai trò Provision; không đổi tên hàng loạt module hoặc nút |
| Phân loại | Product, ProductSet, ProductGroup, Sheet, Criterion, ScoreBand, StarLevel | Sheet đối chiếu CriterionSheet; ProductSet không tự đồng nhất ProductSubgroup; ScoreOption không tự biến thành một khoảng điểm |
| Chủ thể | Subject, SubjectType, Authority, Area | Organization/AdministrativeArea có ánh xạ tường minh; phân biệt chủ thể cụ thể với loại chủ thể được một quy định nói đến |
| Thủ tục | Procedure, Step, Form, FormField, Deadline | Step/Form đối chiếu ProcedureStep/FormTemplate; Deadline giữ đơn vị, sự kiện bắt đầu và điều kiện |
| Công nhận | Decision, Record, Certificate | Decision/Record đối chiếu RecognitionDecision/RecognitionRecord; không đồng nhất chứng nhận, quyết định và kết quả công nhận |
| Quy phạm | Obligation, Permission, Prohibition, Exemption, Transition | Là các biến thể có kiểu của hợp đồng Norm; không nâng RuleCandidate thành quy phạm chỉ vì có cùng từ khóa |
| Khái niệm | Concept, Mention | Concept có định nghĩa/bí danh và phạm vi; Mention là lần xuất hiện có vị trí, không phải một danh tính thực thể mới |

Mỗi danh tính chuẩn có loại, tên chuẩn, bí danh có dẫn chứng và phạm vi phân biệt.
Gộp theo ID chính thức khi nguồn có; nếu không, xét loại, địa bàn/cấp, chủ thể sở
hữu và thời gian. Không gộp chỉ bằng bỏ dấu, đổi hoa/thường hoặc viết tắt trùng.
Các lần xuất hiện giữ provenance riêng. Bảng ánh xạ ID cũ → ID chuẩn phải kiểm
được; không chuyển quyết định con người sang nội dung có hash khác một cách ngầm.

`SAME_CONCEPT` đòi hỏi cùng nghĩa trong phạm vi tương ứng; giống từ hoặc embedding
gần nhau chỉ tạo đề xuất. Một thuật ngữ đổi định nghĩa theo phiên bản không được
gộp thành một quy phạm bất biến. Chu trình alias và ánh xạ sang hai danh tính
khác nhau phải bị chặn trước khi công bố.

## Hợp đồng quy phạm

Mỗi Norm chứa tối thiểu:

- `id`, `kind`, `subject_ids`, `action`, `object_ids`;
- `condition_ids`, `exception_ids`, `authority_ids`, `deadline_ids`;
- `document_version_id`, `provision_ids`;
- `valid_from`, `valid_to`, `validity_basis`, `applicability_event`;
- `origin`, `derived`, kết quả kiểm, hash nội dung và phiên bản cơ chế tạo;
- `citations`: EvidenceUnit, trang PDF, bbox, SHA nguồn, quote nguyên văn.

Giá trị không được nguồn nêu phải là null/danh sách rỗng kèm trạng thái thiếu,
không được model điền cho đủ. Hiệu lực chưa biết khác với không giới hạn thời
gian. Ngày nhận hồ sơ, ngày công nhận, ngày cấp giấy và ngày hiệu lực không được
thay thế nhau. Nếu ngày kết thúc được tính từ sự kiện, giữ công thức và sự kiện
thay vì bịa một ngày lịch. Thời gian pháp lý khác thời điểm hệ thống ghi nhận.

Điều có thể chứa nhiều Norm hoặc không chứa Norm. Mỗi Provision phải được phân
loại có quy phạm/không có quy phạm/hỗn hợp/chưa xác định; mục không có quy phạm
giữ lý do. Không ép điều định nghĩa, bảng danh mục hoặc tiêu đề thành nghĩa vụ.

Các thuộc tính JSON structured output đều thuộc `required`; trường tùy chọn
dùng null hoặc mảng rỗng. Cấm loại nút, quan hệ hoặc thuộc tính ngoài schema.

## Quan hệ có kiểu

| Quan hệ | Hai đầu và điều kiện |
| --- | --- |
| ELIGIBLE_SUBJECT, EXEMPT_FROM, MUST_MEET | Quy phạm/phạm vi chương trình → loại chủ thể, quy phạm được miễn hoặc điều kiện; bắt buộc giữ điều kiện/ngoại lệ |
| CLASSIFIED_AS, USES_SHEET | Product → ProductSet; ProductSet/nhóm → Sheet; việc khớp từ trong tên bộ chỉ tạo ứng viên |
| MEETS_SCORE_BAND, SCORE_MAPS_TO_RATING | Record → ScoreBand → StarLevel; khoảng có cận đóng/mở, đơn vị, phiên bản và điều kiện; kiểm số tất định |
| CERTIFIED_BY | StarLevel → Authority trong phạm vi quy phạm, thời gian và cấp có thẩm quyền; không gán cơ quan đó cho mọi sự kiện công nhận |
| SUBMITS_FOR_EVALUATION, REQUIRES_FORM, SUBMITTED_AT, HAS_DEADLINE | Chủ thể/Procedure/Step → thủ tục, Form đúng phiên bản, nơi nhận hoặc Deadline; không ghép bước của thủ tục khác |
| CERT_VALID_FOR, GRANTS_BRAND_USE | Certificate hoặc quy phạm về Certificate → thời hạn/quyền; phân biệt hạn của giấy với hạn của văn bản |
| AMENDS_PROVISION, SUPERSEDES, SUSPENDS, APPLIES_INSTEAD, PRESERVES_UNDER_TRANSITION | DocumentVersion/Provision/Transition → phiên bản hoặc Provision đích đã giải; giữ phạm vi, sự kiện và thời gian áp dụng |
| REQUIRES_DECLARATION, REQUIRES_LABEL, REQUIRES_TRACEABILITY, REQUIRES_RECALL | Quy phạm/chủ thể/thủ tục → hành vi hoặc yêu cầu được định danh; phải có căn cứ trực tiếp hoặc chuỗi quy phạm được chứng minh |
| DEFINES, REFERS_TO, SAME_CONCEPT | Provision → Concept; Mention → nút đích thật; Concept ↔ Concept chỉ khi có căn cứ tương đương nghĩa |

Danh mục trên cần được cụ thể hóa thành domain/range đóng trong ontology trước
khi công bố. Norm nối subject/condition/exception/provision bằng các quan hệ có
kiểu tương ứng; không làm mất cấu trúc điều kiện khi chiếu ra bộ ba để tìm kiếm.
Quan hệ của gold là nhãn nhiệm vụ, không phải nguồn tạo cạnh. Ánh xạ nhãn gold
sang đường quan hệ cần được khai báo, kiểm hướng và phạm vi; không đổi gold.
`DIFFERENCE_OF_COUNTS` là phép tổng hợp có toán hạng được dẫn chứng, không phải
một cạnh khẳng định sẵn trong graph.

## Tạo, kiểm và duyệt

1. Đọc snapshot bằng chứng hiện có; giải cấu trúc, tham chiếu nội bộ và số hiệu
   qua registry. Sửa đổi phải giải tới đúng khoản/điều/mẫu và phiên bản, không
   áp dụng rộng cho cả văn bản khi nguồn chỉ thay một phần.
2. Trích tất định bảng công nhận, đại lượng và cận điểm khi có cấu trúc đủ rõ.
   Gộp danh tính có kiểm tra trước khi đưa ứng viên cho người duyệt.
3. Model chỉ đề xuất Norm/bộ ba theo schema đóng. Hai ID đầu mút phải tồn tại,
   đúng kiểu và cùng phạm vi được phép. Quote phải nằm trong EvidenceUnit gốc;
   quote hợp lệ không tự chứng minh nghĩa. Ngoại lệ, phủ định và đại lượng được
   kiểm riêng; mâu thuẫn giữ lại để giải quyết, không chọn tùy tiện một phía.
4. Giao diện/lệnh duyệt theo Concept/Subject gom các cạnh liên quan thành lô có
   thể xem. Mỗi cạnh vẫn hiện hai đầu, chiều, quy phạm, điều kiện và dẫn chứng.
   Chấp nhận lô ghi danh sách ID + hash của từng cạnh cùng snapshot, người duyệt
   và thời điểm; không có cơ chế “duyệt nút thì mọi cạnh tự đúng”.
5. Đổi quote, đầu mút, điều kiện, phiên bản hoặc hash phải làm quyết định liên
   quan hết khả năng áp dụng tự động. Từ chối/đính chính có thể làm lô mất hợp lệ.

Mention không giải được do mơ hồ/ngoài registry giữ lý do; không tạo nút giả để
đạt số 0. Chỉ tiêu là mọi tham chiếu đủ điều kiện trong corpus được giải đúng.

## Truy xuất và ngữ cảnh

Hai nguồn seed là đoạn tìm được và danh tính đã liên kết từ câu hỏi. Trước mọi
hop phải lọc corpus, phiên bản đã ghim, thời gian, phạm vi và trạng thái cho phép.
Giữ edge ID, hướng, bằng chứng và provenance của đường đi; không dùng đường
SUPPORTED_BY/CONTAINS chung một văn bản như chứng minh quan hệ nghiệp vụ.

Câu hỏi có đường nghiệp vụ rõ dùng traversal theo loại quan hệ. Câu liên tưởng
có thể dùng Personalized PageRank trên đoạn và Concept sau cùng bộ lọc; điểm
PageRank chỉ xếp hạng ứng viên, không xác lập nghĩa vụ hay hiệu lực pháp lý.
Chuỗi công nhận xuất phát Decision/Record → Product, phân loại đi qua ProductSet;
muốn tới StarLevel/Authority phải giữ nhánh Record → ScoreBand/StarLevel tương
ứng, không coi RECOGNIZES → CLASSIFIED_AS → CERTIFIED_BY là chuỗi có kiểu hợp lệ.

Ngân sách giữ ít nhất một khối cho mỗi hop của chuỗi được chọn, khử trùng khi
một khối hỗ trợ nhiều hop. Nếu chuỗi không vừa ngân sách, thu hẹp hoặc báo thiếu
chuỗi; không âm thầm bỏ hop rồi tuyên bố đã trả lời đủ. Giữ các cổng sẵn có về
quy tắc server-owned, quyết định đã ghim và kiểm điểm/sao tất định.

## Nghiệm thu và điều kiện chạy

- Khóa SHA của gold trước/sau. Bộ hiện có 25 câu, 64 bước và 39 lần chuyển bước;
  nhãn tự khai trong file phải được đối chiếu số thực tế khi chấm.
- Ít nhất **36/39** lần chuyển có đường có kiểu, có căn cứ; báo riêng đường tồn
  tại, đường được truy xuất và đường thực sự vào prompt. Không tính đường qua
  hub cấu trúc hoặc chỉ trùng EvidenceUnit là chứng minh ngữ nghĩa.
- Báo độ phủ Norm trên mệnh đề quy phạm và tỷ lệ Provision được phân loại;
  không dùng số nút tạo ra thay độ đúng. Kiểm mẫu âm, ngoại lệ và thay đổi thời gian.
- Mọi cạnh liên văn bản được dùng để khẳng định phải đáp ứng cổng duyệt từng
  quan hệ; số lượng cạnh có trong kho là chỉ số khác.
- Báo tham chiếu đủ điều kiện đã giải, mơ hồ và ngoài corpus riêng. Tất cả đầu
  mút dùng khi trả lời phải tồn tại và đúng snapshot.
- Đo complete-chain recall trên 25 câu; step recall trên 64 bước; thêm đúng đủ
  ý có citation bằng API thật. Không dùng số topology thay chất lượng trả lời.
- So Text-RAG/GraphRAG trên cùng corpus/model/budget. Mốc truy xuất 48/64 và mốc
  14/39 do người dùng cung cấp phải tái lập cùng giao thức trước khi so trước/sau.
  Chuỗi “79 trên 25” chưa đủ rõ để dùng làm số đo baseline.

Không chạy lại model trên 1.668 EvidenceUnit khi chưa có dự toán token, trần chi
phí, giới hạn đồng thời, checkpoint/cache, điều kiện dừng và phép chạy được chấp
thuận. Không chạy hai tiến trình cùng nạp embedding/reranker. Graph tốt hơn
không bảo đảm điểm trả lời tăng; seed phải bổ sung được các đối tượng/cơ quan/mẫu
ngầm rồi vẫn qua chọn bằng chứng và kiểm chứng câu trả lời.

## Cơ sở thiết kế

- [LegalRuleML, OASIS](https://docs.oasis-open.org/legalruleml/legalruleml-core-spec/v1.0/csprd01/legalruleml-core-spec-v1.0-csprd01.html): tham khảo cách tách modality, điều kiện/ngoại lệ và thời gian; không thêm bộ suy diễn pháp lý tự động.
- [HippoRAG 2](https://arxiv.org/abs/2502.14802), [mã nguồn tác giả](https://github.com/OSU-NLP-Group/HippoRAG): tham khảo đồ thị có passage và Personalized PageRank; chỉ chọn thuật toán sau đối chiếu với traversal có kiểu trên bộ đo của dự án.

## Vận hành hiện hành

- `semantics.py` tạo DocumentVersion, các biến thể Norm, Concept trong phạm vi
  điều định nghĩa (kể cả đoạn nối trang), SubjectType, ProductSet, ScoreBand và
  Deadline từ bằng chứng hiện có. Giá trị thời gian, điều kiện và ngoại lệ chưa
  xác định giữ null/mảng rỗng cùng `missing_fields`; Norm không tự thành quy tắc
  tính điểm có thể thực thi.
- `proposals.py` cung cấp schema bộ ba đóng và bộ kiểm hai ID, domain/range,
  quote nguyên văn và hình học trang. Đây là kiểm đầu vào cho đề xuất model,
  không phải bộ chứng minh entailment hoặc tiến trình gọi model hàng loạt.
- `search_graph` hợp nhất seed thực thể và seed EvidenceUnit, đi qua quan hệ có
  kiểu và dùng Personalized PageRank khi không có yêu cầu quan hệ tường minh.
  PageRank chạy sau bộ lọc và chỉ điều khiển thứ tự; không biến hub cấu trúc
  thành bằng chứng pháp lý. Chọn SOURCE dành chỗ theo hop; chuỗi không vừa
  ngân sách tối thiểu bị loại cùng nhau.
- Lệnh `review decide-batch` ghi một sự kiện với danh sách ID/hash tường minh.
  Duyệt Concept riêng không tự chấp nhận cạnh liên quan. Quyết định đổi nội dung
  hoặc snapshot không còn khớp bị từ chối. Nút/cạnh vi phạm kiểm kỹ thuật không
  được bỏ qua kiểm tra bằng quyết định theo lô.
  Có thể xuất queue và quyết định trên snapshot chưa kích hoạt bằng
  `--candidate-graph <graph-dir>`; ledger phải còn khớp thời điểm dựng snapshot.
  Nhờ vậy có thể kiểm và chấp nhận sửa provenance trước khi đổi graph đang dùng.
- `review refresh-graph` chỉ dựng graph từ EvidenceUnit hiện có. Trước khi công
  bố, kiểm byte-value của toàn bộ evidence/structured records, đầu vào parent
  chain và catalog so với chỉ mục. Chỉ khi giống nhau mới cập nhật liên kết
  manifest; chunk, BM25, catalog, vector và collection giữ nguyên. Nếu không
  chứng minh được thì dừng, không tự dựng lại chỉ mục. Snapshot trước được giữ
  để phục hồi khi publication lỗi.
- Xuất Neo4j ghi từng lô vào snapshot chưa hoạt động. Một transaction cuối
  kiểm đủ số nút/cạnh rồi đổi con trỏ active; lỗi giữa các lô không đổi con trỏ.
  Cách chia transaction theo [hướng dẫn Neo4j](https://neo4j.com/docs/operations-manual/current/database-internals/transaction-management/) giới hạn bộ nhớ giao dịch.

```powershell
python tools/cli.py review refresh-graph
python tools/cli.py review queue --group-id <node-id> --out <queue.jsonl>
python tools/cli.py review decide-batch --graph-version <version> --targets-file <targets.json> --decision approve --reviewer <name>
python tools/cli.py review publish-neo4j
python tools/cli.py status
```

`targets.json` là mảng `[{"target_id":"...","content_hash":"..."}]` được người
duyệt chọn từ queue; `graph_version` nằm trong kết quả lệnh queue. Các lệnh
không gọi model. Phần chưa được triển khai đầy đủ gồm hợp nhất bí danh liên
văn bản, lấp toàn bộ chủ thể/điều kiện/ngoại lệ và hiệu lực pháp lý, cùng bộ chạy
model toàn corpus. Chưa thể dùng số nút Norm hoặc số cạnh để khẳng định đạt
36/39 bước chuyển hay tăng chất lượng câu trả lời.
