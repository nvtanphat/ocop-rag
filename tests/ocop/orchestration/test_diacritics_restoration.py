import json

from ai_core.orchestration.ocop import diacritics_model


class Model:
    def __init__(self, text):
        self.text = text

    def chat_structured(self, system, user, **kwargs):
        return json.dumps({"text": self.text})


CORPUS = {"sp": "san pham", "htx": "hop tac xa"}
ASKED = "cho hoi htx minh lam tra atiso thi dang ky ocop can nhung giay to gi"


def test_only_a_question_typed_without_any_diacritic_is_restored():
    assert diacritics_model.needs_restoring(ASKED)
    assert not diacritics_model.needs_restoring("Cho hỏi HTX mình làm trà atiso cần giấy tờ gì")
    assert not diacritics_model.needs_restoring("QD 26/2026")


def test_a_restoration_that_only_adds_marks_is_taken():
    restored = "cho hỏi HTX mình làm trà atiso thì đăng ký OCOP cần những giấy tờ gì"
    assert diacritics_model.propose(Model(restored), ASKED, CORPUS) == restored


def test_a_restoration_that_changes_a_word_or_adds_one_is_refused():
    assert diacritics_model.propose(Model("cho hỏi HTX Minh Lâm làm trà atiso thì đăng ký OCOP cần giấy tờ gì"), ASKED, CORPUS) is None
    assert diacritics_model.propose(Model("cho hỏi HTX mình làm trà atiso đỏ thì đăng ký OCOP cần những giấy tờ gì"), ASKED, CORPUS) is None


def test_an_abbreviation_may_be_written_out_only_as_the_words_its_initials_name():
    asked = "sp minh dat 4 sao roi muon len 5 sao thi phai lam gi"
    good = "Sản phẩm mình đạt 4 sao rồi, muốn lên 5 sao thì phải làm gì"
    assert diacritics_model.propose(Model(good), asked, CORPUS) == good
    assert diacritics_model.propose(Model("Siro phúc mình đạt 4 sao rồi, muốn lên 5 sao thì phải làm gì"), asked, CORPUS) is None


def test_a_restored_spelling_the_corpus_never_writes_yields_to_the_one_beside_the_same_neighbours():
    from collections import Counter

    from ai_core.orchestration.ocop.diacritics_model import settle

    pairs = Counter({("của", "bộ"): 40, ("bộ", "sản"): 90, ("bó", "hoa"): 0, ("hàng", "hóa"): 20, ("hóa", "được"): 5})
    spellings = {"bo": frozenset({"bộ"}), "hoa": frozenset({"hoa", "hóa"})}
    assert settle("tiêu chí của bó chè tươi", pairs, spellings) == "tiêu chí của bộ chè tươi"
    # "hoa" is a spelling the corpus writes: the user's word stays even where "hóa được" is more common.
    assert settle("Bó hoa được không", pairs, spellings) == "Bó hoa được không"


def test_a_lower_case_question_is_not_given_capitalised_names():
    import json as _json

    class Model:
        def chat_structured(self, system, prompt, schema=None, max_tokens=0):
            return _json.dumps({"text": "sản phẩm Minh Đạt 68 điểm, cần thêm bao nhiêu để lên 4 sao"})

    restored = diacritics_model.propose(Model(), "sp minh dat 68 diem, can them bao nhieu de len 4 sao", {"sp": "san pham"})
    assert restored == "sản phẩm minh đạt 68 điểm, cần thêm bao nhiêu để lên 4 sao"
