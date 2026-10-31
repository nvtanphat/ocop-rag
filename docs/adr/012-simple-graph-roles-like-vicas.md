# ADR 012: Schema graph theo vai trò (14 vai trò nút, 19 vai trò quan hệ)

Trạng thái: **Accepted**. Cài đặt: `configs/ocop_graph_roles.yaml`, `ai_core/graph/ocop/roles.py`; Neo4j lưu graph vai trò.

## Bối cảnh

Dữ liệu OCOP gồm 12 văn bản. Tri thức dùng được tập trung ở các nhóm sau: 2.943 quy phạm (Obligation 1.980, Permission 330,
Prohibition 280, Transition 198, Exemption 155), 1.531 tiêu chí, 289 điều, 1.085 khoản, 834 điểm, 183 nhóm và bộ sản phẩm,
97 sản phẩm, 75 khái niệm, 34 cơ quan, 11 đối tượng áp dụng, 10 hạng sao.

Mô hình tham khảo là ViCAS-RAG: tập loại nút và quan hệ đóng và nhỏ (11 loại nút, khoảng 13 quan hệ), quan hệ cụ thể, nguồn
gốc ghi phẳng trên từng nút và cạnh. Phần không áp dụng: dùng Chunk làm nút. Ở OCOP mỗi khẳng định phải trỏ về trang, bbox,
SHA nguồn và `evidence_unit_id`.

## Ràng buộc

- [ADR-001](001-single-graph-output.md) và AGENTS.md: một đồ thị công bố.
- Quyết định duyệt gắn `target_id` và `content_hash`.
- `SCHEMA_REVISION` là dấu vân tay mã của bộ dựng: sửa mã trong dấu vân tay buộc dựng lại và embed lại.

## Quyết định

Mỗi nút và quan hệ có một **vai trò** (`role`) cố định, tính bằng bảng ánh xạ trong cấu hình. Truy xuất, Neo4j (nhãn nút và
loại quan hệ) và giao diện đọc theo vai trò.

### 14 vai trò nút

| Vai trò | Gồm | Số nút dùng được |
| --- | --- | --- |
| Document | SourceDocument, DocumentVersion, Regulation, LocalGuidance | 24 |
| Provision | Article, Clause, Point, Annex (`level`) | 2.207 |
| Norm | Obligation, Permission, Prohibition, Exemption, Transition (`modality`; hạn nằm trong thuộc tính `deadline`) | 2.943 |
| Concept | Concept | 75 |
| Subject | SubjectType | 11 |
| Authority | Authority | 34 |
| ProductGroup | ProductGroup, ProductSubgroup, ProductSet (`level`) | 177 |
| CriterionSheet | CriterionSheet, FormTemplate | 86 |
| Criterion | Criterion (tiêu chí con cũng là Criterion; ScoreOption, Condition, EvidenceType là thuộc tính `options`, `conditions`, `evidence_types`) | 1.531 |
| StarLevel | StarLevel (ScoreBand là thuộc tính `score_range`) | 10 |
| Procedure | ProcedureStep, Procedure (FormField và Deadline là thuộc tính) | 81 |
| Record | RecognitionRecord, RecognitionDecision, Certificate | 23 |
| Product | Product | 97 |
| Organization | Organization, AdministrativeArea | 27 |

Không là vai trò nút: EvidenceUnit (nguồn gốc ghi phẳng), Mention, CandidateFact, RuleCandidate, CriterionRowCandidate,
RegulatoryClaim (danh sách `not_answer` trong cấu hình).
Chúng nằm ở hàng đợi ứng viên, không vào đường trả lời.

### 19 vai trò quan hệ

| Vai trò | Nối | Số cạnh dùng được |
| --- | --- | --- |
| CONTAINS | Document tới Provision, Provision tới Provision, ProductGroup tới nhóm con, Record tới bản ghi (HAS_ARTICLE, HAS_CLAUSE, HAS_POINT, HAS_ANNEX, HAS_SUBGROUP, HAS_RECORD, DEFINES_GROUP) | 2.197 |
| EXPRESSES | Provision tới Norm (chỉ điều khoản cha gần nhất) | 2.138 |
| APPLIES_TO | Norm tới Subject (HAS_SUBJECT, ELIGIBLE_SUBJECT, APPLIES_IN, SUBMITS_FOR_EVALUATION) | 1.134 |
| GOVERNS | Norm tới thứ nó điều chỉnh (HAS_OBJECT, MUST_MEET, EXEMPT_FROM, REQUIRES_FORM, REQUIRES_DECLARATION, REQUIRES_LABEL, REQUIRES_RECALL, REQUIRES_TRACEABILITY, GRANTS_BRAND_USE, CERT_VALID_FOR) | 3.614 |
| HANDLED_BY | tới Authority (HAS_AUTHORITY, CERTIFIED_BY, SUBMITTED_AT) | 471 |
| DEFINES | Provision tới Concept | 821 |
| REFERENCES | Provision tới Provision, khái niệm trùng (CITES, REFERENCES, SAME_CONCEPT) | 101 |
| AMENDS | tới thứ bị sửa, tạm ngưng hoặc giữ lại khi chuyển tiếp (AMENDS, AMENDS_PROVISION, SUSPENDS, PRESERVES_UNDER_TRANSITION) | 16 |
| SUPERSEDES | tới thứ bị thay (REPLACES, SUPERSEDES, APPLIES_INSTEAD) | 2 |
| BASED_ON | Document tới Document | 5 |
| USES_SHEET | ProductGroup tới CriterionSheet | 77 |
| HAS_CRITERION | CriterionSheet tới Criterion, Criterion tới Criterion | 1.531 |
| SCORES_TO | Criterion tới StarLevel | 22 |
| RECOGNIZES | Record tới Product | 21 |
| HAS_STAR | Record tới StarLevel | 21 |
| OWNED_BY | Product hoặc Record tới Organization | 82 |
| CLASSIFIED_AS | Product tới ProductGroup hoặc CriterionSheet | 46 |
| RESPONSIBLE_FOR | Authority tới Procedure | 93 |
| DEFINED_IN | StarLevel tới Provision quy định cơ quan công nhận | 12 |

Quan hệ nối tới một EvidenceUnit (trích dẫn, sửa đổi, quy định cơ quan) được nâng lên Provision sâu nhất có trích đơn vị đó.
Loại quan hệ lưu trữ gốc giữ trong `stored_relation` của cạnh vai trò. Quan hệ ngoài vai trò (nguồn gốc, ứng viên) nằm trong
`not_answer`; một test kiểm mọi loại nút và quan hệ của ontology đều là vai trò, thuộc tính gộp hoặc nằm trong `not_answer`.
Số lượng trong các bảng lấy từ lần dựng trước khi bỏ bước duyệt; cập nhật sau lần dựng tiếp theo.

### Nguồn gốc ghi phẳng

Mỗi nút và cạnh mang: `source_id`, `pdf_page`, `bbox`, `source_sha256`, `evidence_unit_ids`, `quote`, `check`, `derived`.
Phần tử gộp thành thuộc tính (ví dụ `options` của Criterion) cũng mang các trường này cho từng phần tử. Chỉ nút và cạnh có
`check` là `passed` hoặc `human_verified` thuộc đường trả lời.

## Hệ quả và giới hạn

- Dữ liệu liên văn bản còn thưa: AMENDS 16, SUPERSEDES 2, BASED_ON 5. Schema không tự tạo thêm cạnh.
- Cạnh chờ đầu mút và nút `failed` không vào đường trả lời cho đến khi được duyệt.
- Chỉ số gold phải được đo lại sau mỗi lần dựng; schema gọn không đảm bảo điểm tăng.
