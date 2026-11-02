# Chẩn đoán nguyên nhân điểm router OCOP thấp

Ngày khảo sát: 2026-11-02. Mã nguồn: `92ec73cd8332609c20677535e70c2b8b69ba05fb`. Đây là nghiên cứu và thí nghiệm chẩn đoán; không sửa router, planner, cấu hình lưu trên đĩa, gold, dữ liệu nguồn hoặc index.

## Kết luận

**48,75% là tỷ lệ khớp đồng thời intent và một nhãn lane trên 80 câu, không phải tỷ lệ chọn đúng công cụ hay trả lời đúng.** Điểm thấp có hai nhóm nguyên nhân cùng tồn tại:

1. **Metric lane không phản ánh đầy đủ mục tiêu thực thi.** Lane được suy ra từ cả công cụ bắt buộc lẫn công cụ phụ, trong khi gold chỉ có một lane. Công cụ phụ có thể làm một kế hoạch đúng bị chấm sai, hoặc làm một kế hoạch thiếu công cụ chính được chấm đúng lane.
2. **Có lỗi router thật.** Phát hiện capability và chấm intent không thống nhất; luật nhận diện phụ thuộc cụm từ; tên địa phương bị dùng như tín hiệu miền; bước mở lại scope bằng bigram có thể vượt qua nhu cầu hỏi rõ đối tượng; điểm luật và ngưỡng semantic chưa được chứng minh đã hiệu chỉnh cho tập câu này. Tầng LLM không đi qua mọi trường hợp sai và không tự sửa các vấn đề cấu trúc đó.

Không có bằng chứng để quy nguyên nhân chính cho OCR, đồ thị bị hỏng hoặc thiếu một framework agent. Phép đo router không thực thi công cụ, và cùng dữ liệu có thể cho nhãn khác nhau chỉ bằng thay đổi biểu đạt hoặc cách tổng hợp lane. Điều này không chứng minh chất lượng OCR/graph hoàn hảo; chúng nằm ngoài phép chẩn đoán này.

Nghiên cứu 11 dự án tham chiếu không tìm được một kết quả benchmark tương đương chứng minh router nào có thể thay vào để giải quyết sẵn vấn đề. Xem [đối chiếu mã nguồn tham chiếu](router-reference-study.md).

## 1. Phạm vi và phương pháp

- Tái lập baseline trên 80 câu; phân tích từng câu chỉ ở **dev 40 câu**. Sealed 40 câu chỉ chạy báo cáo tổng hợp, không in/lưu prediction từng câu để chỉnh router.
- Chạy cùng gold với rules-only, rules + embedding, và rules + embedding + LLM; không thay nhãn chuẩn.
- Ghi trace dev ở các ranh giới: slot, facet, điểm từng intent, đề xuất semantic, capability, required tools, secondary tools, lane trước/sau planning.
- Can thiệp một biến mỗi lần: tắt graph phụ trong bộ nhớ; đổi ngưỡng semantic trong bộ nhớ; chiếu lane từ required tools; thử paraphrase trên câu dev. Khôi phục các giá trị trước khi kết thúc tiến trình; không ghi cấu hình runtime.
- Đọc mã nguồn các repo `reference/` tại commit pin trong báo cáo tham chiếu; không dùng README thay cho implementation.
- Kiểm tra 24 test liên quan semantic routing, lane và scope recovery. Các test đều pass, trong khi lỗi gold vẫn tái hiện.

Phiên bản dữ liệu: corpus `affccebc20166db51141`; graph `ce4db556b0af69a47a97`; knowledge `9d5b479d6a6022de9011`; index `ocop-retrieval-c77940171f8f`; embedding `google/embeddinggemma-300m`. Nguồn: các manifest hiện hành dưới `data/processed/ocop/`. Trọng số/revision model không được benchmark này khóa thành một thí nghiệm tái lập bit-for-bit.

### Lệnh tái lập

Chạy từ thư mục gốc repo:

```powershell
python -X utf8 tools/evaluate_router.py --split dev --no-semantic
python -X utf8 tools/evaluate_router.py --split dev --errors --out D:/AgentAI/ocop-eval-runs/router_dev_rules_embedding.jsonl
python -X utf8 tools/evaluate_router.py --split dev --model --out D:/AgentAI/ocop-eval-runs/router_dev_with_model.jsonl
python -X utf8 tools/evaluate_router.py --split sealed --sealed --no-semantic
python -X utf8 tools/evaluate_router.py --split sealed --sealed
python -X utf8 tools/evaluate_router.py --split sealed --sealed --model
python -X utf8 -m pytest tests/ocop/orchestration/test_semantic_route.py tests/ocop/orchestration/test_retrieval_strategy_routes.py tests/ocop/orchestration/test_indexed_scope_router.py -q
```

`-X utf8` tránh lỗi in tiếng Việt của Python trên terminal Windows. Lần chạy `--errors` đầu tiên không có tùy chọn này bị `UnicodeEncodeError` sau khi đã in tổng điểm, trước khi ghi file; đã chạy lại thành công. Đây là lỗi đầu ra CLI, không phải nguyên nhân dự đoán sai.

Harness can thiệp và artifact dev nằm ngoài repo: `D:/AgentAI/ocop-eval-runs/router_diagnosis_probe.py`, `router_probe_baseline.json`, `router_probe_rules_only.json`, `router_probe_without_secondary_graph.json`, `router_probe_threshold_*.json`, `router_probe_semantic.json`. File baseline có trace điểm/facet/công cụ; file semantic chỉ có những query mà router thực sự hỏi tầng embedding. Không suy diễn rằng những query vắng mặt không thể được embedding phân loại.

Ca tái hiện tối giản, chạy bằng Python từ gốc repo:

```python
from tools.evaluate_router import OcopAgent, ROOT, load, DEFAULT, run_row, score

agent = OcopAgent(ROOT)
agent.semantic_route = None
row = next(r for r in load(DEFAULT) if r["id"] == "RT041")
route, _ = run_row(agent, row)
result = score(row, route)
print(result["intent"], result["gold_lane"], result["lane"])
assert result["intent_ok"] and result["lane_ok"]
```

Đã chạy: in `RECOGNITION_LOOKUP PINPOINT HYBRID_GRAPH`, rồi `AssertionError`; phần route/plan khoảng 0,036 giây, toàn lệnh khoảng 1,18 giây. Bỏ embedding mà triệu chứng vẫn còn giúp thu hẹp nguyên nhân của ca này vào tool-plan/lane, không phải chất lượng embedding. Nghiên cứu này dừng ở chẩn đoán theo yêu cầu, nên ca vẫn fail và không được trình bày như một bản sửa đã hoàn tất.

## 2. Kết quả đo lại

| Cấu hình | Dev intent | Dev lane | Dev cả hai | Sealed intent | Sealed lane | Sealed cả hai |
|---|---:|---:|---:|---:|---:|---:|
| Rules | 26/40 (65%) | 26/40 (65%) | 19/40 (47,5%) | 23/40 (57,5%) | 20/40 (50%) | 16/40 (40%) |
| Rules + embedding, mặc định | 31/40 (77,5%) | 26/40 (65%) | 21/40 (52,5%) | 27/40 (67,5%) | 23/40 (57,5%) | 18/40 (45%) |
| Rules + embedding + LLM | 36/40 (90%) | 29/40 (72,5%) | 26/40 (65%) | 28/40 (70%) | 25/40 (62,5%) | 19/40 (47,5%) |

Gộp hai split:

| Cấu hình | Intent đúng | Lane đúng | Đúng cả hai |
|---|---:|---:|---:|
| Rules | 49/80 (61,25%) | 46/80 (57,5%) | 35/80 (43,75%) |
| Rules + embedding | **58/80 (72,5%)** | **49/80 (61,25%)** | **39/80 (48,75%)** |
| Rules + embedding + LLM | **64/80 (80%)** | **54/80 (67,5%)** | **45/80 (56,25%)** |

Embedding cải thiện intent 9 câu trên toàn bộ 80 câu. Vì vậy nhận định “embedding làm router kém” không được phép đo này hỗ trợ. LLM cải thiện intent 6 câu, nhưng tăng 5 câu ở dev và chỉ 1 câu ở sealed: không được lấy 90% dev làm độ chính xác chung.

Evaluator báo 7 lượt hỏi scope model ở dev và 2 ở sealed. Đây là số lần gọi hàm trong toàn lượt replay, có thể bao gồm các câu history; chưa phải phép đo chi phí token hay tỷ lệ query độc lập chuẩn hóa. Các cuộc gọi model chỉ chạy một lần, không khóa revision/response; chưa đo độ biến thiên hay kiểm chứng ngữ nghĩa của mọi output model.

### Cấu hình thực sự được đo

Phép đo 48,75% ban đầu truyền `llm=None`, nên không gọi model. Với `--model`, `OcopAgent` có client thật và bật `llm_scope`; biến `OCOP_LLM_ROUTER` được kiểm tra là **chưa đặt**, nên nhánh `llm_route` vẫn tắt. Hai đường này khác nhau: không nên diễn giải `--model` là đã thử mọi chế độ model router.

Nguồn: [evaluator](../../tools/evaluate_router.py#L143), [workflow route](../../ai_core/orchestration/ocop/workflow.py#L113), [model scope](../../ai_core/orchestration/ocop/scope_model.py#L45), [cấu hình](../CONFIGURATION.md#L20).

## 3. Nguyên nhân A: exact lane vừa phạt công cụ phụ, vừa che lỗi chọn công cụ

`choose_retrieval_path` ưu tiên graph trước; sau đó chỉ cần bất kỳ công cụ pinpoint nào để nhãn thành `PINPOINT`. Nó không nhận vai trò primary/secondary. Router truyền `required + secondary`; workflow planning lại gán lane từ toàn bộ plan. Evaluator so lane bằng phép bằng tuyệt đối với một `gold_lane`.

Nguồn: [phân loại lane](../../ai_core/orchestration/ocop/retrieval_strategy.py#L21), [chọn công cụ phụ](../../ai_core/orchestration/ocop/router.py#L635), [gán lane](../../ai_core/orchestration/ocop/router.py#L1056), [planner](../../ai_core/orchestration/ocop/planner.py#L151), [workflow](../../ai_core/orchestration/ocop/workflow.py#L197), [chấm lane](../../tools/evaluate_router.py#L118).

Trên dev 40 câu, 19 câu không đạt metric kết hợp: **10 chỉ sai lane**, **5 chỉ sai intent**, **4 sai cả hai**. Cả 10 ca chỉ sai lane đều có lane của công cụ bắt buộc khớp gold. Tuy nhiên đây chưa phải chứng nhận toàn bộ công cụ đã đúng, vì gold không gán tool set.

Ví dụ:

- `RT041/043/045/047`: intent nhận đúng công nhận sản phẩm, primary là `lookup_recognition`; optional là `search_graph`, `search_regulations`. Gold `PINPOINT`, kết quả `HYBRID_GRAPH` → sai lane.
- `RT065/067`: primary là `search_regulations`, đúng ý định tổng quan; optional `lookup_product_subgroup` khiến lane thành `PINPOINT` thay vì gold `TEXT`.
- Chiều ngược lại, `RT029/051` có intent sai và primary chỉ `search_regulations`, nhưng công cụ taxonomy phụ khiến lane thành `PINPOINT` và được chấm đúng lane. Metric không nhận ra thiếu công cụ chính phù hợp.

### Can thiệp xác nhận

| Can thiệp riêng trên dev | Intent đúng | Lane đúng | Cả hai đúng |
|---|---:|---:|---:|
| Baseline | 31/40 | 26/40 | 21/40 |
| Tắt `graph_secondary` trong bộ nhớ | 31/40 | 31/40 | 26/40 |
| Giữ nguyên plan, chỉ chấm lane từ required tools | 31/40 | 29/40 | 26/40 |

Tắt graph phụ không đổi intent và không chứng minh truy xuất tốt hơn: nó sửa lane của một số câu nhưng làm lane của `RT057/075` lệch gold. Chiếu required tools sửa 10 mismatch lane nhưng làm 7 match cũ thành mismatch, nên tăng ròng 3 câu lane, không phải 10. **Không nên tắt graph hay sửa hàng loạt gold chỉ để điểm tăng.** Cần metric công cụ và bằng chứng trước.

## 4. Nguyên nhân B: capability và intent chấm bằng hai bộ điều kiện không đồng nhất

### B1. Câu hỏi trang đã chọn đúng công cụ nhưng sai nhãn intent

`RT023`: “Trang 2 của Quyết định 797/QĐ-UBND ở Huế có quy định gì?”

- Slot có `document_code`, `pdf_page=2`, `region=Huế`.
- `_capabilities` coi document + article **hoặc page** là `EXACT_ARTICLE`.
- Khối chấm điểm `EXACT_LOOKUP` lại chỉ kiểm tra authority hoặc document + **article_id**, không có page.
- Không có score, intent rơi về `OCOP_OVERVIEW`; cuối hàm vẫn ép công cụ thành `lookup_legal_unit` vì page + document.
- Embedding đề xuất đúng `EXACT_LOOKUP` nhưng score 0,519 < 0,55 nên không sửa nhãn.

Nguồn: [capability](../../ai_core/orchestration/ocop/router.py#L564), [intent scoring](../../ai_core/orchestration/ocop/router.py#L892), [ép lookup theo trang](../../ai_core/orchestration/ocop/router.py#L1039).

Đây là lỗi nhãn thật, nhưng chưa phải bằng chứng truy xuất sai. Nên thống nhất ý nghĩa exact lookup ở một điểm quyết định, không dựa vào embedding để sửa thiếu sót cấu trúc này.

### B2. Quan hệ văn bản được phát hiện mà không tạo intent tương ứng

`RT055`: “... có thay thế bộ tiêu chí cũ không?” có `criteria=True`, `relation=True`, nhưng không có temporal hoặc multihop. Điểm chỉ còn `CRITERIA_LOOKUP=45`; capability lại gồm criteria và relation. Kết quả có graph đúng dạng nhưng intent sai.

Thử paraphrase `RT053` thành “sửa đổi quyết định...” làm relation/công cụ graph xuất hiện, song intent vẫn `OCOP_OVERVIEW`: phát hiện relation trong capability không bảo đảm có điểm cho intent temporal/multihop. Đây không chỉ là thiếu một từ đồng nghĩa.

Nguồn: [Facets](../../ai_core/orchestration/ocop/router.py#L521), [relation capability](../../ai_core/orchestration/ocop/router.py#L586), [scores](../../ai_core/orchestration/ocop/router.py#L885).

## 5. Nguyên nhân C: cụm từ khóa và điểm luật chưa bao phủ cách hỏi tự nhiên

Các phép thử sau chạy rules-only trên cùng catalog, không sửa gold; chỉ dùng để phân biệt nguyên nhân, không tính thành accuracy mới:

| Ca dev | Biểu đạt ban đầu | Can thiệp biểu đạt | Quan sát |
|---|---|---|---|
| RT029 | “tính mấy điểm” | “điểm tối đa bao nhiêu” | Từ overview/text sang criteria/`lookup_criterion` |
| RT051 | “có nằm trong danh mục sản phẩm...” | “thuộc nhóm sản phẩm...” | Từ overview sang product classification |
| RT063 | “ghi nhãn liên quan thế nào đến...” | “nhãn hàng hóa liên quan đến...” | Từ overview sang multihop, có `search_graph` |

`Language.hits` yêu cầu khớp nguyên cụm. Danh sách criteria có “điểm tối đa”, không có cấu trúc “tính mấy điểm”; classification có “thuộc nhóm”, không có cách hỏi membership trên; compliance có “nhãn hàng hóa”, không có “ghi nhãn”; relation có “liên quan đến”, không khớp khi có phần chen giữa. Khi không khớp, có từ “OCOP” hoặc một entity cũng đủ giữ câu trong miền rồi rơi về overview.

Nguồn: [khớp cue](../../ai_core/orchestration/ocop/language.py#L116), [từ vựng](../../configs/ocop_language.yaml), [fallback capability](../../ai_core/orchestration/ocop/router.py#L588), [fallback intent](../../ai_core/orchestration/ocop/router.py#L949).

Các điểm 45/55/60/65/75/80 là hằng số ưu tiên trong code, không phải xác suất đúng. Ví dụ `RT061` có temporal=75 và relation capability, nhưng không có multihop cue, nên intent temporal thắng và bỏ qua tầng semantic sửa luật yếu. Sửa riêng câu mẫu embedding không tác động đến nhánh đã được xem là chắc.

## 6. Nguyên nhân D: ranh giới scope và tham chiếu hội thoại

### D1. Entity địa phương không tự chứng minh câu hỏi thuộc miền

`RT007`: “Chỉ mình cách nấu bún bò Huế với.” Catalog chỉ match region `Huế`, không có cue nghiệp vụ, nhưng `any(catalog.mentions(q).values())` khiến `in_domain=True`. Semantic đề xuất OUT_OF_SCOPE với score 0,543, margin 0,198, bị loại bởi ngưỡng 0,55. Baseline rơi về overview.

Thay riêng “Huế” bằng “tại nhà” làm rules-only trả `OUT_OF_SCOPE`. Với ngưỡng 0,50 trong bộ nhớ hoặc LLM fallback, câu gốc được từ chối đúng. Quan hệ nhân quả ở đây là entity miền quá rộng cộng ngưỡng fallback; không phải thiếu tài liệu nấu ăn.

Nguồn: [scope theo catalog](../../ai_core/orchestration/ocop/router.py#L798), [semantic threshold](../../ai_core/orchestration/ocop/router.py#L679).

### D2. Bigram corpus không giải quyết được đại từ thiếu antecedent

`RT015`: “Van ban do con ap dung khong?” không có history, có đại từ nhưng content còn 3 từ `van/ap/dung`. Coverage của bigram trong index là **2/3**, vượt 0,60 → mở lại in-domain. Điều kiện hỏi rõ tham chiếu chỉ áp dụng khi `len(content) <= 2`, nên câu chạy vào overview thay vì hỏi “văn bản nào?”.

Giữ nguyên câu/catalog, không cấp callback coverage → `CLARIFY`; cấp callback thật → `OCOP_OVERVIEW`. Có LLM thì thành `TEMPORAL_COMPARE`, vẫn không giải quyết được thiếu đối tượng văn bản. Nhận ra nội dung có liên quan pháp luật khác với biết văn bản được nhắc là văn bản nào.

Nguồn: [coverage](../../ai_core/retrieval/ocop/search.py#L226), [mở scope](../../ai_core/orchestration/ocop/router.py#L846), [điều kiện clarify](../../ai_core/orchestration/ocop/router.py#L868).

### D3. Schema slot địa phương quá gộp

Hai slot miss trên dev: `RT011` yêu cầu `criterion_id=1.6`, trong khi nhánh bare fragment chỉ yêu cầu scope và không giữ criterion slot; `RT037` gold yêu cầu province `Hà Tĩnh`, prediction giữ ward `Thành Sen`. Trường hợp thứ hai chứa cả hai địa danh đúng trong câu, nhưng schema chỉ có `region` nên chưa phân biệt cấp hành chính. Không thể coi mọi mismatch string là entity không được nhận ra.

Nguồn: [slot criterion và region](../../ai_core/orchestration/ocop/router.py#L309), [chấm slot](../../tools/evaluate_router.py#L93), [gold dev](../../data/evaluations/ocop/ocop_router_gold_80.jsonl).

## 7. Nguyên nhân E: semantic fallback hữu ích nhưng ngưỡng và phạm vi gọi hạn chế

Có 70 câu mẫu cho 11 intent, mỗi intent 4–10 câu; không có mô hình classifier được huấn luyện riêng trong `SemanticRouter`. Cách chấm là lấy similarity cao nhất của mỗi nhãn, rồi kiểm tra score >=0,55 và margin >=0,03. Không thấy bước fit/calibration được gọi trong đường chạy này. Score cosine và các điểm luật không cùng thang đo xác suất.

Nguồn: [mẫu](../../configs/ocop_router_examples.yaml), [semantic classifier](../../ai_core/orchestration/ocop/semantic_route.py#L35), [threshold](../../ai_core/orchestration/ocop/router.py#L672), [config](../../configs/ocop_retrieval.yaml#L52).

| Can thiệp ngưỡng trên dev, giữ mọi thứ khác | Intent đúng | Lane đúng | Cả hai |
|---|---:|---:|---:|
| 0,55 / margin 0,03 | 31/40 | 26/40 | 21/40 |
| 0,50 / margin 0,03 | 34/40 | 27/40 | 24/40 |
| 0,45 / margin 0,03 | 34/40 | 28/40 | 24/40 |
| 0,55 / margin 0 | 31/40 | 26/40 | 21/40 |

Ngưỡng 0,50 sửa dev RT007, RT023, RT055. Hạ tiếp không thêm intent đúng: RT053 nhận multihop thay vì gold temporal, RT051 vẫn nhận overview. RT029 bị chặn cả score và margin. Do đó không có bằng chứng rằng “hạ threshold” là giải pháp đầy đủ; các ngưỡng này chưa được triển khai hoặc đem tối ưu theo sealed.

Nguồn bên ngoài để đối chiếu cơ chế: [Aurelio router documentation](https://docs.aurelio.ai/docs/semantic-router/v1/user-guide/components/routers) mô tả similarity router, calibration và threshold như những khái niệm riêng. Đây là căn cứ thiết kế thử nghiệm hiệu chỉnh, không phải bằng chứng thư viện đó sẽ tốt hơn trên OCOP.

## 8. Nguyên nhân F: LLM không phải lớp sửa sai cho mọi quyết định

Trong nhánh đã có score luật nhưng score yếu, code chỉ thử `_semantic_label`; nếu semantic không đạt thì không hỏi `llm_scope`. Trong nhánh score cao, không hỏi cả hai. Nhánh không có score mới có `second_opinion` gồm semantic rồi model.

Nguồn: [luật yếu](../../ai_core/orchestration/ocop/router.py#L939), [không có score](../../ai_core/orchestration/ocop/router.py#L949), [second opinion](../../ai_core/orchestration/ocop/router.py#L808).

Hệ quả đo được trên dev:

- Model sửa đúng RT007, RT023, RT029, RT051, RT063.
- RT055 vẫn criteria vì nhánh luật yếu không fallback model.
- RT061 vẫn temporal vì điểm 75 chặn sửa nhãn.
- RT015 model hiểu temporal nhưng vẫn thiếu antecedent, nên còn sai mục tiêu clarification.
- RT053 model chọn multihop; gold yêu cầu temporal. Prompt mô tả MULTIHOP gồm quan hệ sửa đổi giữa văn bản, TEMPORAL gồm so sánh quy định cũ/mới; ranh giới này có chồng lấn thật trong taxonomy.

Không kết luận gold RT053 sai chỉ từ kết quả model. Cần người gán nhãn độc lập xác định nhiệm vụ chính, hoặc gold cho phép capability/tool set tương đương. Metric đã hỗ trợ `alt_intent` ở một số câu; ví dụ RT073 chấp nhận cả FOLLOWUP và RECOGNITION_LOOKUP, nên RT073 **không phải** lỗi intent trong phép đo này.

Nguồn: [prompt phân loại](../../ai_core/orchestration/ocop/scope_model.py#L30), [alt intent](../../tools/evaluate_router.py#L105). Hướng schema-first routing được trình bày trong [LangGraph workflow docs](https://docs.langchain.com/oss/python/langgraph/workflows-agents); schema bảo đảm dạng dữ liệu, không tự loại bỏ chồng lấn nghĩa giữa nhãn.

## 9. Kiểm kê 19 ca dev không đạt metric kết hợp

| Ca | Trạng thái baseline | Nguồn gốc chính được quan sát |
|---|---|---|
| RT007 | Sai intent + lane | Region Huế mở scope; semantic OOS dưới threshold |
| RT015 | Sai intent + lane | Đại từ không có antecedent; bigram mở scope trước clarification |
| RT023 | Sai intent, lane đúng | Page capability có, page intent score không có |
| RT025 | Intent đúng, lane sai | Taxonomy optional đổi TEXT thành PINPOINT |
| RT029 | Sai intent, lane đúng | Không khớp cue điểm; taxonomy optional che lane primary text |
| RT041 | Intent đúng, lane sai | Recognition primary đúng; graph optional đổi lane |
| RT043 | Intent đúng, lane sai | Như RT041 |
| RT045 | Intent đúng, lane sai | Như RT041 |
| RT047 | Intent đúng, lane sai | Như RT041 |
| RT051 | Sai intent, lane đúng | Membership paraphrase không khớp classification; optional che lane |
| RT053 | Sai intent + lane | Cue sửa đổi không khớp; ranh giới temporal/multihop chồng lấn |
| RT055 | Sai intent, lane đúng | Relation capability không tạo temporal intent; semantic bị chặn score |
| RT059 | Intent đúng, lane sai | Compliance text đúng; graph optional đổi lane |
| RT061 | Sai intent, lane đúng | Temporal score cao; thiếu multihop cue mặc dù có relation |
| RT063 | Sai intent + lane | Compliance/relation paraphrase không khớp cue |
| RT065 | Intent đúng, lane sai | Overview text đúng; taxonomy optional đổi lane |
| RT067 | Intent đúng, lane sai | Như RT065 |
| RT073 | Intent hợp lệ qua alt, lane sai | Recognition primary đúng; graph optional đổi lane |
| RT077 | Intent đúng, lane sai | Follow-up primary text; graph optional đổi lane |

Đây là phân loại chẩn đoán, không phải cộng các đóng góp nhân quả độc lập. Một câu có thể chịu nhiều nguyên nhân; không có cách chia 48,75% thành các phần trăm nguyên nhân cộng được chỉ bằng những can thiệp đã chạy.

## 10. Hướng sửa được ưu tiên

1. **Đo hành động đúng trước khi tối ưu điểm lane.** Giữ metric cũ để so lịch sử; thêm required-tool recall, admissible/prohibited tool sets, slot/version correctness, optional cost, evidence coverage. Tách lane primary và lane toàn kế hoạch; không sửa gold bằng prediction của router.
2. **Sửa tính nhất quán giữa facet, capability và intent.** Page/document exact lookup phải có cùng nghĩa ở mọi bước; quan hệ sửa đổi/thay thế phải được đưa vào quyết định nghiệp vụ rõ ràng; không thêm một lớp fallback che các điều kiện mâu thuẫn.
3. **Giải quyết tham chiếu thiếu trước mở scope.** Có ngữ nghĩa pháp luật nhưng không có văn bản nào làm antecedent phải hỏi rõ; entity địa danh chỉ bổ sung scope, không là chứng cứ nghiệp vụ độc lập. Cần giữ ward/province riêng hoặc công bố rõ cấp của slot.
4. **Hiệu chỉnh tầng hiểu câu trên dữ liệu độc lập.** Định nghĩa ranh giới temporal/multihop và business intent/follow-up; mở rộng paraphrase/negative examples bằng câu độc lập, không chép dev/sealed vào mẫu. Thử threshold theo lớp và đo cả coverage lẫn precision, không đổi thẳng 0,55 thành 0,50 chỉ vì ba ca dev.
5. **Chỉ mở rộng model fallback sau khi thống nhất quyết định.** Thử mô hình trên xung đột hoặc thiếu intent, với output enum/capability có schema; tools vẫn do registry server ánh xạ, tối đa năm calls. Giữ pinned decision, provenance và cổng score/star. Không cần chuyển sang agent tự do hoặc thay toàn framework để sửa các lỗi này.
6. **Đánh giá tác động end-to-end.** Mỗi thay đổi phải được đo lại trên bằng chứng và câu trả lời, không chỉ intent/lane. Tắt graph phụ có thể tăng điểm router nhưng làm mất evidence; mở rộng phạm vi có thể giảm false reject nhưng tăng trả lời sai miền. Chưa có phép đo causal end-to-end trong nghiên cứu này.

## 11. Giới hạn và trạng thái sau nghiên cứu

- 40 câu dev quá ít để chọn threshold/model vĩnh viễn; sealed chỉ được dùng để báo tổng hợp, chưa có tập độc lập thứ ba.
- Chưa có gold tool set và nhãn entailment độc lập cho từng ca router, nên chưa báo được “độ chính xác công cụ thật” thay cho 48,75%.
- Chưa benchmark centroid router, classifier được fine-tune, sparse+dense router hoặc full LLM router trên cùng OCOP; báo cáo reference chỉ chứng minh cơ chế source.
- Chưa đánh giá token/cost, latency router steady-state hoặc variance của model API.
- 24 test hiện hành pass xác nhận một phần hợp đồng implementation; chúng không chứng minh hiểu paraphrase đúng. Các test semantic chủ yếu dùng proposal giả lập, còn test lane kiểm tra tính nhất quán với plan — không thay thế gold ngoài mẫu.
- Hai báo cáo dưới `docs/research/` là thay đổi repo duy nhất của nghiên cứu. Chưa áp dụng sửa runtime hay sửa nhãn, chưa rebuild và chưa push các báo cáo này.

Các nguồn bổ sung và commit pin của 11 repo: [router-reference-study.md](router-reference-study.md).
