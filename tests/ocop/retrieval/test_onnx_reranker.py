
import numpy as np

from ai_core.retrieval.ocop.onnx_reranker import OnnxCrossEncoder


def test_scores_come_back_in_the_callers_order_whatever_the_batching():
    class Tokenizer:
        def __call__(self, queries, passages, **kwargs):
            ids = np.array([[len(p)] for p in passages])
            return {"input_ids": ids, "attention_mask": np.ones_like(ids)}

    class Session:
        def run(self, names, feed):
            return [feed["input_ids"].astype("float32")]  # the score of a pair is its passage length

    encoder = OnnxCrossEncoder.__new__(OnnxCrossEncoder)
    encoder.session, encoder.tokenizer, encoder.max_length = Session(), Tokenizer(), 512
    pairs = [("q", "aaaa"), ("q", "a"), ("q", "aaaaaaaa"), ("q", "aa"), ("q", "aaa")]
    assert encoder.predict(pairs, batch_size=2) == [4.0, 1.0, 8.0, 2.0, 3.0]
