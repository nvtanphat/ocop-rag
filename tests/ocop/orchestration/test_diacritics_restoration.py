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
