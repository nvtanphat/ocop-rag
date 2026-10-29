"""The semantic tier of the router: example utterances, embedding similarity, and where the rules yield to it."""

from types import SimpleNamespace

import numpy as np
import pytest

from ai_core.orchestration.ocop import semantic_route
from ai_core.orchestration.ocop.contracts import Intent
from ai_core.orchestration.ocop.router import route_query

WEAK_RULE = "Mẫu hồ sơ cần điền những gì?"  # a general procedure cue scores 50 (below the confident 60)
STRONG_RULE = "Điều 6 Quyết định 26/2026/QĐ-TTg quy định gì?"  # a document and a locator score 88


def proposes(intent, score=0.8, margin=0.2):
    return lambda text: SimpleNamespace(intent=intent, score=score, margin=margin)


def test_a_weak_rule_yields_to_clearly_closer_example_utterances():
    assert route_query(WEAK_RULE).intent == Intent.PROCEDURE_FORM
    route = route_query(WEAK_RULE, semantic_route=proposes("CRITERIA_LOOKUP"))
    assert route.intent == Intent.CRITERIA_LOOKUP
    assert route.capabilities == ["criteria"] and "semantic_override" in route.reason_codes


@pytest.mark.parametrize(
    "proposal",
    [
        proposes("CRITERIA_LOOKUP", score=0.3),  # not close enough
        proposes("CRITERIA_LOOKUP", margin=0.0),  # not ahead of the next intent
        proposes("OCOP_OVERVIEW"),  # the catch-all is no evidence against a specific intent
        proposes("not-an-intent"),
        lambda text: None,
    ],
)
def test_an_unclear_or_catch_all_proposal_leaves_the_rules_alone(proposal):
    assert route_query(WEAK_RULE, semantic_route=proposal) == route_query(WEAK_RULE)


def test_a_rule_that_is_sure_is_never_overruled():
    asked = []
    route = route_query(STRONG_RULE, semantic_route=lambda text: asked.append(text) or proposes("OUT_OF_SCOPE")(text))
    assert route.intent == Intent.EXACT_LOOKUP == route_query(STRONG_RULE).intent
    assert asked == []  # the cheap path stays cheap: no embedding is computed for it


def test_a_continuation_is_proposed_only_when_there_is_something_to_continue():
    prior = {"last_query": "Hồ sơ đăng ký lần đầu gồm những gì?", "slots": {}, "intent": "PROCEDURE_FORM"}
    question = "Nộp ở đâu vậy bạn?"
    assert route_query(question, session=prior, semantic_route=proposes("FOLLOWUP")).intent == Intent.FOLLOWUP
    assert route_query(question, semantic_route=proposes("FOLLOWUP")) == route_query(question)


def test_the_help_question_with_a_closing_particle_is_still_a_greeting_not_a_task():
    assert route_query("Bạn có thể giúp mình những việc gì vậy?").intent == Intent.CONVERSATION


class Vectors:
    """Words as one-hot dimensions, so that similarity is the share of words two utterances have in common."""

    def __init__(self):
        self.vocabulary = {}

    def __call__(self, texts):
        rows = []
        for text in texts:
            words = text.lower().split()
            for word in words:
                self.vocabulary.setdefault(word, len(self.vocabulary))
            rows.append(words)
        out = np.zeros((len(rows), 64))
        for row, words in enumerate(rows):
            for word in words:
                out[row, self.vocabulary[word]] = 1
            out[row] /= max(np.linalg.norm(out[row]), 1)
        return out


def test_the_closest_intent_wins_with_its_score_and_its_lead():
    router = semantic_route.SemanticRouter(
        {"PROCEDURE_FORM": ["nop ho so o dau", "han nop ho so"], "OUT_OF_SCOPE": ["gia vang hom nay", "nau canh chua"]},
        Vectors(),
    )
    near = router.classify("nop ho so khi nao")
    assert near.intent == "PROCEDURE_FORM" and near.score > 0.5 and near.margin > 0.5
    far = router.classify("gia vang bao nhieu")
    assert far.intent == "OUT_OF_SCOPE"


def test_without_a_dense_index_the_semantic_tier_proposes_nothing(tmp_path):
    assert semantic_route.for_index(tmp_path)("Nộp ở đâu?") is None
    (tmp_path / "manifest.json").write_text('{"dense": {"enabled": false}}')
    assert semantic_route.for_index(tmp_path)("Nộp ở đâu?") is None


def test_the_example_utterances_name_only_intents_the_router_accepts():
    examples = semantic_route.load_examples()
    assert set(examples) <= {intent.value for intent in Intent}
    assert all(len(texts) >= 4 for texts in examples.values())
    assert len({text for texts in examples.values() for text in texts}) == sum(len(t) for t in examples.values())
