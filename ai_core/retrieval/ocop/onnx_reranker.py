"""The cross-encoder as an int8 ONNX graph on onnxruntime: same scores shape as ``CrossEncoder.predict``, about twice as fast on CPU.

Built once by ``tools/export_reranker_onnx.py`` next to the torch model; ``search._load_reranker`` uses it when the
directory exists and falls back to the torch model otherwise, so a missing file never breaks a question.
"""

from __future__ import annotations

from pathlib import Path


class OnnxCrossEncoder:
    def __init__(self, onnx_dir: str | Path, tokenizer_dir: str, threads: int) -> None:
        import onnxruntime as ort
        from transformers import AutoTokenizer

        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        self.session = ort.InferenceSession(
            str(Path(onnx_dir) / "model.onnx"), options, providers=["CPUExecutionProvider"]
        )
        self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_dir, local_files_only=True)
        self.max_length = 512

    def predict(self, pairs, batch_size: int = 4, show_progress_bar: bool = False) -> list[float]:
        # Short pairs batched together waste no padding; scores go back to the caller's order.
        order = sorted(range(len(pairs)), key=lambda i: len(pairs[i][1]))
        scores = [0.0] * len(pairs)
        for start in range(0, len(order), batch_size):
            chunk = order[start : start + batch_size]
            encoded = self.tokenizer(
                [pairs[i][0] for i in chunk],
                [pairs[i][1] for i in chunk],
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="np",
            )
            logits = self.session.run(
                ["logits"],
                {"input_ids": encoded["input_ids"].astype("int64"), "attention_mask": encoded["attention_mask"].astype("int64")},
            )[0].reshape(-1)
            for i, value in zip(chunk, logits, strict=True):
                scores[i] = float(value)
        return scores
