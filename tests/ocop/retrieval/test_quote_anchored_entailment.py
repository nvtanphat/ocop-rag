import json

from ai_core.orchestration.ocop.entailment import anchored, review

EXCERPT = (
    "Cột: STT | Tổ chức/cá nhân | Sản phẩm | Chủ thể | Điểm\n"
    "13 | Hợp tác xã Thụy Hương | Gạo ruộng rươi giống HANA | Nguyễn Thị Hà | 74,6 | 4 sao"
)


class Judge:
    def __init__(self, verdicts):
        self.verdicts = verdicts

    def chat_structured(self, system, user, **kw):
        return json.dumps({"verdicts": self.verdicts})


def test_quote_must_be_verbatim_in_the_excerpt():
    claim = "Gạo ruộng rươi giống HANA do Hợp tác xã Thụy Hương đứng tên."
    assert anchored(claim, "Gạo ruộng rươi giống HANA | Nguyễn Thị Hà", EXCERPT)
    assert not anchored(claim, "Gạo ruộng rươi giống HANA | Trần Văn B", EXCERPT)
    assert not anchored(claim, "quá ngắn", EXCERPT)


def test_numbers_negation_and_names_of_the_claim_must_be_in_the_quote():
    quote = "Gạo ruộng rươi giống HANA | Nguyễn Thị Hà"
    assert not anchored("Gạo ruộng rươi giống HANA có 99 sản phẩm.", quote, EXCERPT)
    assert not anchored("Gạo ruộng rươi giống HANA không thuộc Nguyễn Thị Hà.", quote, EXCERPT)
    assert not anchored("Gạo ruộng rươi giống HANA của Nguyễn Văn Lâm.", quote, EXCERPT)


def test_judge_verdict_without_an_anchoring_quote_is_ignored():
    items = [{"claim": "Gạo HANA thuộc Nguyễn Thị Hà.", "excerpt": EXCERPT}]
    assert (
        review(Judge([{"id": 0, "entails": True, "quote": "câu bịa không có trong đoạn trích"}]), items) == {}
    )
    assert review(Judge([{"id": 0, "entails": False, "quote": ""}]), items) == {}
    assert 0 in review(
        Judge([{"id": 0, "entails": True, "quote": "Gạo ruộng rươi giống HANA | Nguyễn Thị Hà"}]), items
    )


def test_judge_failure_leaves_the_claim_rejected():
    class Broken:
        def chat_structured(self, *a, **k):
            raise RuntimeError("down")

    assert review(Broken(), [{"claim": "x", "excerpt": EXCERPT}]) == {}
    assert review(None, [{"claim": "x", "excerpt": EXCERPT}]) == {}
