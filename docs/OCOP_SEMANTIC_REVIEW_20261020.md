# Manual PDF review - 2026-10-20

Seed 20261020; source-balanced fixed sample: 10 passed/type (all if fewer), 5 failed/type; all 65 LLM EvidenceType mentions. PDF SHA-256 checked against the lock before rendering at 200 DPI. All 60 contact sheets and five targeted cross-page crops were viewed. The mixed-actor sample RESPONSIBLE_FOR:10 was superseded by its two literal clauses after a red/green regression; both clauses are visible in its p7 crop. No image text was copied into graph data.

Scratch: `C:/Users/PC/AppData/Local/Temp/ocop-semantic-quality-20261020`; `final_samples.json`, `manual_judgments.json`, `verified_source_sha256.json`, `invariants.json`, `cache_migrations.json`, `build_results.json`, `crops/`. Full rows retain evidence IDs, bboxes and hashes. This journal judges extraction assertions, not legal/scoring validity; a correct candidate may intentionally remain failed.

| Sample | Check | PDF source/pages | Verdict | Error class | Reason |
|---|---|---|---|---|---|
| failed:edge:HAS_CONDITION:01 | failed | VN.OCOP.QD26.2026 p21 | correct | gate | Source contains this note/qualification, but no automatic condition interpretation is promoted. |
| failed:edge:HAS_CONDITION:02 | failed | VN.OCOP.QD26.2026 p18 | correct | gate | Source contains this note/qualification, but no automatic condition interpretation is promoted. |
| failed:edge:HAS_CONDITION:03 | failed | VN.OCOP.QD26.2026 p28 | correct | gate | Source contains this note/qualification, but no automatic condition interpretation is promoted. |
| failed:edge:HAS_CONDITION:04 | failed | VN.OCOP.QD26.2026 p18, VN.OCOP.QD26.2026 p19 | correct | gate | Source contains this note/qualification, but no automatic condition interpretation is promoted. |
| failed:edge:HAS_CONDITION:05 | failed | VN.OCOP.QD26.2026 p19, VN.OCOP.QD26.2026 p20 | correct | gate | Source contains this note/qualification, but no automatic condition interpretation is promoted. |
| failed:edge:REQUIRES_EVIDENCE:01 | failed | VN.OCOP.QD26.2026 p20, VN.OCOP.QD26.2026 p30 | incorrect | LLM | A scoring alternative mentions a storefront URL, not an unconditional document input. |
| failed:edge:REQUIRES_EVIDENCE:02 | failed | VN.HATINH.THANHSEN.2026 p2, VN.HATINH.THANHSEN.2026 p4 | incorrect | LLM | Agency requests applicants to prepare documents; agency is not their input obligor. |
| failed:edge:REQUIRES_EVIDENCE:03 | failed | VN.OCOP.QD26.2026 p21, VN.OCOP.QD26.2026 p22 | incorrect | LLM | Certificate appears in an optional score alternative. |
| failed:edge:REQUIRES_EVIDENCE:04 | failed | VN.OCOP.QD26.2026 p29, VN.OCOP.QD26.2026 p30 | incorrect | LLM | Conditional intellectual-property evidence within a scoring alternative. |
| failed:edge:REQUIRES_EVIDENCE:05 | failed | VN.OCOP.QD26.2026 p31, VN.OCOP.QD26.2026 p32 | incorrect | LLM | Product standard is mentioned, but this note explicitly requires the test sheet, not this extra input edge. |
| failed:edge:RESPONSIBLE_FOR:01 | failed | VN.OCOP.QD1489.2025 p3, VN.OCOP.QD1489.2025 p4 | correct | gate | Conditional action: case of invalid/subthreshold dossier; kept failed. |
| failed:edge:RESPONSIBLE_FOR:02 | failed | VN.OCOP.QD26.2026 p5, VN.OCOP.QD26.2026 p6 | correct | gate | Actor inherited from the prior-page declaration; current verifier abstains. |
| failed:edge:RESPONSIBLE_FOR:03 | failed | VN.OCOP.QD26.2026 p6, VN.OCOP.QD26.2026 p9 | correct | gate | Actual actor, but conditional inspection context; kept failed. |
| failed:edge:RESPONSIBLE_FOR:04 | failed | VN.OCOP.QD26.2026 p10 | correct | gate | Triggered inspection/withdrawal; not an unconditional responsibility assertion. |
| failed:edge:RESPONSIBLE_FOR:05 | failed | VN.OCOP.QD26.2026 p3, VN.OCOP.QD26.2026 p4 | incorrect | parser | Province is not the actor of the ministry action; gate correctly rejects. |
| failed:node:Condition:01 | failed | VN.OCOP.QD26.2026 p21 | correct | gate | Source contains this note/qualification, but no automatic condition interpretation is promoted. |
| failed:node:Condition:02 | failed | VN.OCOP.QD26.2026 p30 | correct | gate | Source contains this note/qualification, but no automatic condition interpretation is promoted. |
| failed:node:Condition:03 | failed | VN.OCOP.QD26.2026 p21 | correct | gate | Source contains this note/qualification, but no automatic condition interpretation is promoted. |
| failed:node:Condition:04 | failed | VN.OCOP.QD26.2026 p30 | correct | gate | Source contains this note/qualification, but no automatic condition interpretation is promoted. |
| failed:node:Condition:05 | failed | VN.OCOP.QD26.2026 p20 | correct | gate | Source contains this note/qualification, but no automatic condition interpretation is promoted. |
| failed:node:ProcedureStep:01 | failed | VN.OCOP.QD26.2026 p10 | correct | gate | Conditional withdrawal action; no unconditional relation accepted. |
| failed:node:ProcedureStep:02 | failed | VN.OCOP.QD1489.2025 p3 | correct | gate | Conditional action, retained failed. |
| failed:node:ProcedureStep:03 | failed | VN.OCOP.QD26.2026 p5, VN.OCOP.QD26.2026 p6 | correct | gate | Real commune step; actor declaration is on p5 and action on p6. False negative remains. |
| failed:node:ProcedureStep:04 | failed | VN.OCOP.QD26.2026 p9 | correct | gate | Real conditional inspection step; conservative failure remains. |
| failed:node:ProcedureStep:05 | failed | VN.OCOP.QD26.2026 p8 | correct | gate | OCR joined notification with a conditional paragraph; failed instead of flattening condition. |
| llm_documents:node:EvidenceType:01 | passed | VN.OCOP.QD1489.2025 p4 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:02 | failed | VN.HATINH.THANHSEN.2026 p3 | incorrect | OCR | Label has an OCR accent error in the document noun; failed. |
| llm_documents:node:EvidenceType:03 | passed | VN.OCOP.QD26.2026 p20 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:04 | failed | VN.ND.15.2018 p5 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:05 | passed | VN.OCOP.QD1489.2025 p4 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:06 | passed | VN.HATINH.THANHSEN.2026 p2 | incorrect | OCR | Annex number/name corrupted by OCR on the infographic; retained verbatim, no correction from image. |
| llm_documents:node:EvidenceType:07 | passed | VN.OCOP.QD26.2026 p20, VN.OCOP.QD26.2026 p30 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:08 | passed | VN.ND.15.2018 p5 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:09 | passed | VN.OCOP.QD1489.2025 p4 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:10 | passed | VN.HATINH.THANHSEN.2026 p2, VN.HATINH.THANHSEN.2026 p3 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:11 | failed | VN.OCOP.QD26.2026 p22, VN.OCOP.QD26.2026 p32 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:12 | passed | VN.ND.15.2018 p5 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:13 | passed | VN.OCOP.QD1489.2025 p3 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:14 | passed | VN.HATINH.THANHSEN.2026 p2 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:15 | failed | VN.OCOP.QD26.2026 p22, VN.OCOP.QD26.2026 p32 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:16 | passed | VN.ND.15.2018 p4 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:17 | passed | VN.OCOP.QD1489.2025 p4 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:18 | passed | VN.HATINH.THANHSEN.2026 p2 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:19 | passed | VN.OCOP.QD26.2026 p22, VN.OCOP.QD26.2026 p32 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:20 | passed | VN.ND.15.2018 p4 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:21 | passed | VN.OCOP.QD1489.2025 p3 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:22 | passed | VN.HATINH.THANHSEN.2026 p2 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:23 | failed | VN.OCOP.QD26.2026 p32 | unknown | LLM | Trade-promotion results can be information rather than a specific document; failed. |
| llm_documents:node:EvidenceType:24 | passed | VN.OCOP.QD1489.2025 p3 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:25 | passed | VN.HATINH.THANHSEN.2026 p2, VN.HATINH.THANHSEN.2026 p3 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:26 | passed | VN.OCOP.QD26.2026 p8 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:27 | passed | VN.HATINH.THANHSEN.2026 p2 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:28 | passed | VN.OCOP.QD26.2026 p4 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:29 | failed | VN.OCOP.QD26.2026 p32 | unknown | LLM | Market information is not a uniquely typed document; failed. |
| llm_documents:node:EvidenceType:30 | passed | VN.OCOP.QD26.2026 p30 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:31 | failed | VN.OCOP.QD26.2026 p18, VN.OCOP.QD26.2026 p19 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:32 | passed | VN.OCOP.QD26.2026 p19, VN.OCOP.QD26.2026 p29 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:33 | passed | VN.OCOP.QD26.2026 p4 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:34 | passed | VN.OCOP.QD26.2026 p20, VN.OCOP.QD26.2026 p30 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:35 | passed | VN.OCOP.QD26.2026 p5 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:36 | failed | VN.OCOP.QD26.2026 p20, VN.OCOP.QD26.2026 p30 | incorrect | LLM | A storefront URL is not itself a document type; failed. |
| llm_documents:node:EvidenceType:37 | passed | VN.OCOP.QD26.2026 p4 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:38 | passed | VN.OCOP.QD26.2026 p22, VN.OCOP.QD26.2026 p32 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:39 | failed | VN.OCOP.QD26.2026 p5 | incorrect | OCR | Anchor is a clipped fragment of the dossier noun; failed. |
| llm_documents:node:EvidenceType:40 | passed | VN.OCOP.QD26.2026 p18, VN.OCOP.QD26.2026 p28 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:41 | passed | VN.OCOP.QD26.2026 p5 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:42 | passed | VN.OCOP.QD26.2026 p20, VN.OCOP.QD26.2026 p30 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:43 | failed | VN.OCOP.QD26.2026 p5 | incorrect | LLM | Anchor clips the beginning of the decision title; failed. |
| llm_documents:node:EvidenceType:44 | passed | VN.OCOP.QD26.2026 p20, VN.OCOP.QD26.2026 p30 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:45 | passed | VN.OCOP.QD26.2026 p22, VN.OCOP.QD26.2026 p32 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:46 | failed | VN.OCOP.QD26.2026 p6, VN.OCOP.QD26.2026 p8 | unknown | LLM | Test results could mean values or a document; conditional request, failed. |
| llm_documents:node:EvidenceType:47 | passed | VN.OCOP.QD26.2026 p20, VN.OCOP.QD26.2026 p30 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:48 | failed | VN.OCOP.QD26.2026 p22, VN.OCOP.QD26.2026 p32 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:49 | failed | VN.OCOP.QD26.2026 p20, VN.OCOP.QD26.2026 p30 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:50 | passed | VN.OCOP.QD26.2026 p6, VN.OCOP.QD26.2026 p8 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:51 | passed | VN.OCOP.QD26.2026 p5 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:52 | passed | VN.OCOP.QD26.2026 p19, VN.OCOP.QD26.2026 p29 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:53 | passed | VN.OCOP.QD26.2026 p5 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:54 | passed | VN.OCOP.QD26.2026 p5 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:55 | passed | VN.OCOP.QD26.2026 p20 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:56 | passed | VN.OCOP.QD26.2026 p6 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:57 | passed | VN.OCOP.QD26.2026 p4 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:58 | passed | VN.OCOP.QD26.2026 p20, VN.OCOP.QD26.2026 p30 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:59 | passed | VN.OCOP.QD26.2026 p18, VN.OCOP.QD26.2026 p28 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:60 | passed | VN.OCOP.QD26.2026 p6 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:61 | passed | VN.OCOP.QD26.2026 p4 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:62 | passed | VN.OCOP.QD26.2026 p5 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:63 | passed | VN.OCOP.QD26.2026 p19, VN.OCOP.QD26.2026 p29 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:64 | passed | VN.OCOP.QD26.2026 p20, VN.OCOP.QD26.2026 p30 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| llm_documents:node:EvidenceType:65 | passed | VN.OCOP.QD26.2026 p5 | correct | none | Document mention visible in source; this does not establish an input requirement or an entity equivalence. |
| passed:edge:AMENDS:01 | passed | VN.HAIPHONG.QD525.2026 p1, VN.OCOP.QD1489.2025 p1 | correct | none | Registered target number and operative cue in the same source clause. |
| passed:edge:BASED_ON:01 | passed | VN.HAIPHONG.QD525.2026 p1, VN.HAIPHONG.QD525.2026 p3 | correct | none | Registered target number and operative cue in the same source clause. |
| passed:edge:DECLARED_BY:01 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:DECLARED_BY:02 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:DECLARED_BY:03 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:DECLARED_BY:04 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:DECLARED_BY:05 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:DECLARED_BY:06 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:DECLARED_BY:07 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:DECLARED_BY:08 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:DECLARED_BY:09 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:DECLARED_BY:10 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:HAS_CRITERION:01 | passed | VN.OCOP.QD26.2026 p17, VN.OCOP.QD26.2026 p30 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_CRITERION:02 | passed | VN.OCOP.QD26.2026 p17, VN.OCOP.QD26.2026 p18 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_CRITERION:03 | passed | VN.OCOP.QD26.2026 p17, VN.OCOP.QD26.2026 p21 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_CRITERION:04 | passed | VN.OCOP.QD26.2026 p17, VN.OCOP.QD26.2026 p31 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_CRITERION:05 | passed | VN.OCOP.QD26.2026 p17, VN.OCOP.QD26.2026 p20 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_CRITERION:06 | passed | VN.OCOP.QD26.2026 p17, VN.OCOP.QD26.2026 p28 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_OPTION:01 | passed | VN.OCOP.QD26.2026 p30 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_OPTION:02 | passed | VN.OCOP.QD26.2026 p29 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_OPTION:03 | passed | VN.OCOP.QD26.2026 p29, VN.OCOP.QD26.2026 p32 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_OPTION:04 | passed | VN.OCOP.QD26.2026 p30 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_OPTION:05 | passed | VN.OCOP.QD26.2026 p20 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_OPTION:06 | passed | VN.OCOP.QD26.2026 p31, VN.OCOP.QD26.2026 p32 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_OPTION:07 | passed | VN.OCOP.QD26.2026 p18 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_OPTION:08 | passed | VN.OCOP.QD26.2026 p21 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_OPTION:09 | passed | VN.OCOP.QD26.2026 p21, VN.OCOP.QD26.2026 p22 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_OPTION:10 | passed | VN.OCOP.QD26.2026 p31 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_SUBCRITERION:01 | passed | VN.OCOP.QD26.2026 p30, VN.OCOP.QD26.2026 p31 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_SUBCRITERION:02 | passed | VN.OCOP.QD26.2026 p28, VN.OCOP.QD26.2026 p29 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_SUBCRITERION:03 | passed | VN.OCOP.QD26.2026 p18, VN.OCOP.QD26.2026 p19 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_SUBCRITERION:04 | passed | VN.OCOP.QD26.2026 p31 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_SUBCRITERION:05 | passed | VN.OCOP.QD26.2026 p28, VN.OCOP.QD26.2026 p29 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_SUBCRITERION:06 | passed | VN.OCOP.QD26.2026 p18, VN.OCOP.QD26.2026 p19 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_SUBCRITERION:07 | passed | VN.OCOP.QD26.2026 p28, VN.OCOP.QD26.2026 p29 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_SUBCRITERION:08 | passed | VN.OCOP.QD26.2026 p18, VN.OCOP.QD26.2026 p19 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_SUBCRITERION:09 | passed | VN.OCOP.QD26.2026 p29, VN.OCOP.QD26.2026 p30 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:HAS_SUBCRITERION:10 | passed | VN.OCOP.QD26.2026 p28, VN.OCOP.QD26.2026 p29 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| passed:edge:OWNED_BY:01 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:OWNED_BY:02 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:OWNED_BY:03 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:OWNED_BY:04 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:OWNED_BY:05 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:OWNED_BY:06 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:OWNED_BY:07 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:OWNED_BY:08 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:OWNED_BY:09 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:OWNED_BY:10 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:RECOGNIZES:01 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:RECOGNIZES:02 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:RECOGNIZES:03 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:RECOGNIZES:04 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:RECOGNIZES:05 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:RECOGNIZES:06 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:RECOGNIZES:07 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:RECOGNIZES:08 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:RECOGNIZES:09 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:RECOGNIZES:10 | passed | VN.HAIPHONG.QD525.2026 p3 | correct | none | Matching printed recognition row, including the explicit merged organization cell. |
| passed:edge:REPLACES:01 | passed | VN.HATINH.THANHSEN.2026 p1, VN.OCOP.QD26.2026 p13 | correct | none | Registered target number and operative cue in the same source clause. |
| passed:edge:REPLACES:02 | passed | VN.HATINH.THANHSEN.2026 p1, VN.OCOP.QD26.2026 p13 | correct | none | Registered target number and operative cue in the same source clause. |
| passed:edge:REQUIRES_EVIDENCE:01 | passed | VN.OCOP.QD26.2026 p31, VN.OCOP.QD26.2026 p32 | correct | none | Printed criterion/option label and source frame match. |
| passed:edge:REQUIRES_EVIDENCE:02 | passed | VN.OCOP.QD26.2026 p21, VN.OCOP.QD26.2026 p22 | correct | none | Printed criterion/option label and source frame match. |
| passed:edge:RESPONSIBLE_FOR:01 | passed | VN.HATINH.THANHSEN.2026 p3, VN.HATINH.THANHSEN.2026 p4 | correct | none | Acting subject/action visible; recipients are not promoted to the acting role. |
| passed:edge:RESPONSIBLE_FOR:02 | failed | VN.OCOP.QD26.2026 p3, VN.OCOP.QD26.2026 p4 | correct | none | Acting subject/action visible; recipients are not promoted to the acting role. |
| passed:edge:RESPONSIBLE_FOR:03 | passed | VN.NQ.15.2026 p2 | correct | none | Acting subject/action visible; recipients are not promoted to the acting role. |
| passed:edge:RESPONSIBLE_FOR:04 | passed | VN.OCOP.QD1489.2025 p3 | correct | none | Acting subject/action visible; recipients are not promoted to the acting role. |
| passed:edge:RESPONSIBLE_FOR:05 | passed | VN.HATINH.THANHSEN.2026 p3, VN.HATINH.THANHSEN.2026 p4 | correct | none | Acting subject/action visible; recipients are not promoted to the acting role. |
| passed:edge:RESPONSIBLE_FOR:06 | failed | VN.OCOP.QD26.2026 p3, VN.OCOP.QD26.2026 p4 | correct | none | Acting subject/action visible; recipients are not promoted to the acting role. |
| passed:edge:RESPONSIBLE_FOR:07 | passed | VN.NQ.15.2026 p2 | correct | none | Acting subject/action visible; recipients are not promoted to the acting role. |
| passed:edge:RESPONSIBLE_FOR:08 | passed | VN.OCOP.QD1489.2025 p3, VN.OCOP.QD1489.2025 p4 | correct | none | Acting subject/action visible; recipients are not promoted to the acting role. |
| passed:edge:RESPONSIBLE_FOR:09 | passed | VN.HATINH.THANHSEN.2026 p3, VN.HATINH.THANHSEN.2026 p4 | correct | none | Acting subject/action visible; recipients are not promoted to the acting role. |
| passed:node:Criterion:01 | passed | VN.OCOP.QD26.2026 p31, VN.OCOP.QD26.2026 p32 | correct | none | Printed criterion/option label and source frame match. |
| passed:node:Criterion:02 | passed | VN.OCOP.QD26.2026 p17, VN.OCOP.QD26.2026 p21 | correct | none | Printed criterion/option label and source frame match. |
| passed:node:Criterion:03 | passed | VN.OCOP.QD26.2026 p18 | correct | none | Printed criterion/option label and source frame match. |
| passed:node:Criterion:04 | passed | VN.OCOP.QD26.2026 p31, VN.OCOP.QD26.2026 p32 | correct | none | Printed criterion/option label and source frame match. |
| passed:node:Criterion:05 | passed | VN.OCOP.QD26.2026 p21 | correct | none | Printed criterion/option label and source frame match. |
| passed:node:Criterion:06 | passed | VN.OCOP.QD26.2026 p28, VN.OCOP.QD26.2026 p29 | correct | none | Printed criterion/option label and source frame match. |
| passed:node:Criterion:07 | passed | VN.OCOP.QD26.2026 p17, VN.OCOP.QD26.2026 p31 | correct | none | Printed criterion/option label and source frame match. |
| passed:node:Criterion:08 | passed | VN.OCOP.QD26.2026 p19 | correct | none | Printed criterion/option label and source frame match. |
| passed:node:Criterion:09 | passed | VN.OCOP.QD26.2026 p21, VN.OCOP.QD26.2026 p22 | correct | none | Printed criterion/option label and source frame match. |
| passed:node:Criterion:10 | passed | VN.OCOP.QD26.2026 p30 | correct | none | Printed criterion/option label and source frame match. |
| passed:node:ProcedureStep:01 | passed | VN.OCOP.QD1489.2025 p4 | correct | none | Acting subject/action visible; recipients are not promoted to the acting role. |
| passed:node:ProcedureStep:02 | failed | VN.NQ.15.2026 p2 | correct | none | Acting subject/action visible; recipients are not promoted to the acting role. |
| passed:node:ProcedureStep:03 | passed | VN.OCOP.QD26.2026 p7 | correct | none | Acting subject/action visible; recipients are not promoted to the acting role. |
| passed:node:ProcedureStep:04 | passed | VN.HATINH.THANHSEN.2026 p4 | correct | none | Acting subject/action visible; recipients are not promoted to the acting role. |
| passed:node:ProcedureStep:05 | passed | VN.OCOP.QD1489.2025 p3 | correct | none | Acting subject/action visible; recipients are not promoted to the acting role. |
| passed:node:ProcedureStep:06 | passed | VN.NQ.15.2026 p2 | correct | none | Acting subject/action visible; recipients are not promoted to the acting role. |
| passed:node:ProcedureStep:07 | passed | VN.OCOP.QD26.2026 p7 | correct | none | Acting subject/action visible; recipients are not promoted to the acting role. |
| passed:node:ProcedureStep:08 | passed | VN.HATINH.THANHSEN.2026 p4 | correct | none | Acting subject/action visible; recipients are not promoted to the acting role. |
| passed:node:ProcedureStep:09 | failed | VN.OCOP.QD1489.2025 p3 | correct | none | Acting subject/action visible; recipients are not promoted to the acting role. |
| passed:node:ProcedureStep:10 | passed | VN.NQ.15.2026 p2 | correct | none | Acting subject/action visible; recipients are not promoted to the acting role. |
| passed:node:ScoreOption:01 | passed | VN.OCOP.QD26.2026 p21, VN.OCOP.QD26.2026 p22 | correct | none | Printed criterion/option label and source frame match. |
| passed:node:ScoreOption:02 | passed | VN.OCOP.QD26.2026 p31 | correct | none | Printed criterion/option label and source frame match. |
| passed:node:ScoreOption:03 | passed | VN.OCOP.QD26.2026 p31, VN.OCOP.QD26.2026 p32 | correct | none | Printed criterion/option label and source frame match. |
| passed:node:ScoreOption:04 | passed | VN.OCOP.QD26.2026 p21 | correct | none | Printed criterion/option label and source frame match. |
| passed:node:ScoreOption:05 | passed | VN.OCOP.QD26.2026 p28 | correct | none | Printed criterion/option label and source frame match. |
| passed:node:ScoreOption:06 | passed | VN.OCOP.QD26.2026 p20 | correct | none | Printed criterion/option label and source frame match. |
| passed:node:ScoreOption:07 | passed | VN.OCOP.QD26.2026 p31 | correct | none | Printed criterion/option label and source frame match. |
| passed:node:ScoreOption:08 | passed | VN.OCOP.QD26.2026 p29 | correct | none | Printed criterion/option label and source frame match. |
| passed:node:ScoreOption:09 | passed | VN.OCOP.QD26.2026 p31 | correct | none | Printed criterion/option label and source frame match. |
| passed:node:ScoreOption:10 | passed | VN.OCOP.QD26.2026 p30 | correct | none | Printed criterion/option label and source frame match. |
| targeted:edge:HAS_OPTION:01 | passed | VN.OCOP.QD26.2026 p18, VN.OCOP.QD26.2026 p19 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| targeted:edge:HAS_OPTION:02 | passed | VN.OCOP.QD26.2026 p28, VN.OCOP.QD26.2026 p29 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| targeted:edge:HAS_OPTION:03 | passed | VN.OCOP.QD26.2026 p18, VN.OCOP.QD26.2026 p19 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| targeted:edge:HAS_OPTION:04 | passed | VN.OCOP.QD26.2026 p28, VN.OCOP.QD26.2026 p29 | correct | none | Matching printed parent/child scope; no score or star value is certified. |
| targeted:edge:HAS_OPTION:05 | passed | VN.OCOP.QD26.2026 p19, VN.OCOP.QD26.2026 p20 | correct | none | Matching printed parent/child scope; no score or star value is certified. |

Limits: 52 passed LLM EvidenceTypes still lack passed semantic edges. Source mentions include outputs, scoring alternatives, conditional requests and nominal dossier lists without an accepted ProcedureStep parent; no edge is fabricated. Generic applicant actors and cross-page inherited actors need a stronger scope verifier. Condition/HAS_CONDITION/StarLevel/MINIMUM_FOR remain conservative. SUSPENDS has synthetic positive/negative coverage but no occurrence in the 39-page input. OCR label damage remains verbatim.
