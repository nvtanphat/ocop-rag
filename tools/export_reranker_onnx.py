"""Build the int8 ONNX copy of the cross-encoder next to the torch model (about twice as fast on CPU).

    python tools/export_reranker_onnx.py [--max-length 512]

Writes ``<models>/bge-reranker-v2-m3-onnx-int8/``; ``search._load_reranker`` picks it up on the next start and the
torch model stays the fallback. Keep TMP/TEMP on drive D: the fp32 graph is ~2.2 GB while it is quantized.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-length", type=int, default=64, help="length of the sample pair used to trace the graph")
    args = parser.parse_args()

    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic

    from ai_core.retrieval.ocop.models_config import DEFAULT_RERANKER_MODEL, resolve_local_model_path

    resolved, is_local = resolve_local_model_path(DEFAULT_RERANKER_MODEL)
    if not is_local:
        raise SystemExit("the torch cross-encoder is not in the local models directory")
    target = Path(resolved).parent / f"{Path(resolved).name}-onnx-int8"
    from sentence_transformers import CrossEncoder

    encoder = CrossEncoder(resolved, device="cpu", trust_remote_code=False, local_files_only=True)
    model, tokenizer = encoder.model.eval(), encoder.tokenizer
    sample = tokenizer(["câu hỏi mẫu"] * 2, ["đoạn văn mẫu"] * 2, padding="max_length", max_length=args.max_length,
                       truncation=True, return_tensors="pt")
    with tempfile.TemporaryDirectory(prefix="reranker-onnx-") as tmp:
        fp32 = Path(tmp) / "model.onnx"
        torch.onnx.export(
            model, (sample["input_ids"], sample["attention_mask"]), str(fp32),
            input_names=["input_ids", "attention_mask"], output_names=["logits"],
            dynamic_axes={"input_ids": {0: "b", 1: "s"}, "attention_mask": {0: "b", 1: "s"}, "logits": {0: "b"}},
            opset_version=17, dynamo=False,
        )
        target.mkdir(exist_ok=True)
        quantize_dynamic(str(fp32), str(target / "model.onnx"), weight_type=QuantType.QInt8, use_external_data_format=True)
    print(f"wrote {target} ({sum(f.stat().st_size for f in target.iterdir()) / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
