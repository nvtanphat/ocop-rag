"""Vietnamese wording that decides behaviour lives in configs/ocop_language.yaml, not in regular expressions in code.

A cue written into a pattern in Python drifts from the vocabulary file (one negation list for the claim checks, another
for the quote check) and cannot be tuned or reviewed in one place. Patterns are built from the vocabulary with
``Language.alternation``/``Language.words``; this test fails when an accented word reappears inside a ``re`` call.
"""

import ast
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
# Files whose bytes decide the evidence/graph/index versions are never edited for style (docs/DEVELOPMENT.md).
FINGERPRINTED = re.compile(
    r"^ai_core/(knowledge/ocop/|processing/ocop/(knowledge_extract|business_candidates|temporal_candidates)"
    r"|graph/ocop/(builder|ontology|review|grounding)|retrieval/ocop/(index_pipeline|structure_chunker|graph_context)"
    r"|domain/ocop_citations)"
)
RUNTIME = re.compile(r"^(ai_core/(orchestration|retrieval|graph|system|evaluation)/|backend/|tools/)")
# "À-ỹ" is the Unicode range of Latin letters with marks; "Đ" is a letter of identifiers such as "QĐ-TTg".
LETTERS = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I)
REGEX_CALLS = {"compile", "search", "match", "fullmatch", "sub", "subn", "findall", "finditer", "split"}


def _strings(node: ast.AST):
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            yield child.lineno, child.value


def test_no_accented_wording_in_regular_expressions_outside_the_vocabulary_file():
    tracked = subprocess.check_output(["git", "ls-files", "*.py"], cwd=ROOT, text=True, encoding="utf-8").split()
    offences = []
    for name in tracked:
        if not RUNTIME.match(name) or FINGERPRINTED.match(name) or name.endswith("language.py"):
            continue
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
            func = call.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            owner = getattr(func.value, "id", "") if isinstance(func, ast.Attribute) else ""
            if called not in REGEX_CALLS or owner not in {"re", "_re"}:
                continue
            for line, text in (s for argument in call.args for s in _strings(argument)):
                words = text.replace("À-ỹ", "").replace("Đ", "")
                if LETTERS.search(words):
                    offences.append(f"{name}:{line}: {text[:70]!r}")
    assert not offences, "Vietnamese wording in a pattern; add it to configs/ocop_language.yaml:\n" + "\n".join(offences)
