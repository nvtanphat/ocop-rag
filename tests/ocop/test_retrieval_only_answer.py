from __future__ import annotations

import json
from pathlib import Path

from ai_core.orchestration.ocop.answer import assemble
from ai_core.orchestration.ocop.workflow import OcopAgent
from ai_core.retrieval.ocop.index_pipeline import build_chunks,create_bm25


def _jsonl(path:Path,rows:list[dict])->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text("".join(json.dumps(row,ensure_ascii=False)+"\n" for row in rows),encoding="utf-8")


def _rowspan_table()->dict:
    cells=[
        {"row":0,"col":0,"text":"STT","is_header":True},
        {"row":0,"col":1,"text":"Tổ chức/cá nhân","is_header":True},
        {"row":0,"col":2,"text":"Sản phẩm","is_header":True},
        {"row":0,"col":3,"text":"Điểm đánh giá","is_header":True},
        {"row":0,"col":4,"text":"Xếp loại","is_header":True},
        {"row":1,"col":0,"text":"1"},
        {"row":1,"col":1,"text":"Công ty TNHH Quang Hải","rowspan":4,
         "bbox":[80,20,180,100],"merged_extent_unknown":False},
        {"row":1,"col":2,"text":"Nước mắm Chắt cao cấp","bbox":[180,20,330,40]},
        {"row":1,"col":3,"text":"83,8"},{"row":1,"col":4,"text":"4 sao"},
        {"row":2,"col":0,"text":"2"},{"row":2,"col":2,"text":"Nước mắm Cá Thu","bbox":[180,40,330,60]},
        {"row":2,"col":3,"text":"84,1"},{"row":2,"col":4,"text":"4 sao"},
        {"row":3,"col":0,"text":"3"},{"row":3,"col":2,"text":"Nước mắm Cao đạm","bbox":[180,60,330,80]},
        {"row":3,"col":3,"text":"84,1"},{"row":3,"col":4,"text":"4 sao"},
        {"row":4,"col":0,"text":"4"},{"row":4,"col":2,"text":"Nước mắm Đặc Biệt","bbox":[180,80,330,100]},
        {"row":4,"col":3,"text":"84,0"},{"row":4,"col":4,"text":"4 sao"},
    ]
    return {"unit_id":"evidence:quang-hai","source_id":"VN.HAIPHONG.QD525.2026",
        "unit_kind":"table","text":"recognition decision table",
        "review_status":"needs_review","spans":[{"pdf_page":3,"bbox":[30,0,400,120],
            "table_id":"table:native:0","source_sha256":"b"*64}],
        "structured":{"table_id":"table:native:0","cells":cells}}


def test_retrieval_only_answer_keeps_long_relevant_row_context():
    relevant="3.3. Sử dụng lao động địa phương | 3\nCó sử dụng từ 25% đến dưới 50% lao động là người trên địa bàn cấp xã | 1"
    excerpt="Thông tin bảng đã trích xuất. "*25+relevant
    result=assemble("Tiêu chí sử dụng lao động địa phương được chấm mấy điểm?",[
        {"tool":"search_regulations","output":{"results":[{
            "source_id":"VN.OCOP.QD26.2026","evidence_unit_id":"unit:criterion",
            "chunk_id":"chunk:criterion","text":excerpt,"review_status":"needs_review",
            "spans":[{"pdf_page":29,"bbox":[10,20,300,40],"source_sha256":"c"*64}],
        }]}}
    ],llm=None)
    assert relevant in result["answer"]
    assert "review=needs_review" in result["answer"]
    assert "điểm số OCR chưa xác minh không phải kết luận" in result["answer"]


def test_agent_lists_each_product_in_a_merged_producer_rowspan(tmp_path):
    index=tmp_path/"data/processed/ocop/index"
    chunks=build_chunks([_rowspan_table()],"recognition-debug")
    _jsonl(index/"chunks.jsonl",chunks)
    bm25=create_bm25(chunks,index/"bm25.json.gz")
    (index/"manifest.json").write_text(json.dumps({"corpus_version":"recognition-debug",
        "status":"sparse_ready","dense":{"enabled":False},"counts":{"chunks":len(chunks)},
        "bm25":bm25}),encoding="utf-8")

    result=OcopAgent(tmp_path,llm=None).ask("Công ty TNHH Quang Hải có những sản phẩm OCOP nào?")
    for product in ("Nước mắm Chắt cao cấp","Nước mắm Cá Thu",
                    "Nước mắm Cao đạm","Nước mắm Đặc Biệt"):
        assert product in result.answer
    assert all(score in result.answer for score in ("83,8", "84,1", "84,0"))
    assert result.status=="retrieval_only"
    assert all(citation["pdf_page"]==3 for citation in result.citations)
