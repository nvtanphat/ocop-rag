"""Rating ladder (star levels) read from configs/ocop_language.yaml, shared by extraction, graph and routing.

Regex fragments are built from the configured ladder so no module spells "1-5" or "3-5" itself.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_CONFIG = Path(__file__).resolve().parents[1] / 'configs' / 'ocop_language.yaml'


@lru_cache(maxsize=1)
def _ladder() -> tuple[tuple[int, ...], tuple[int, ...]]:
    data = yaml.safe_load(_CONFIG.read_text(encoding='utf-8'))
    return tuple(sorted(data['star_levels'])), tuple(sorted(data['certified_star_levels']))


def star_levels() -> tuple[int, ...]:
    return _ladder()[0]


def certified_levels() -> tuple[int, ...]:
    return _ladder()[1]


def level_class(*, certified: bool = False) -> str:
    """Regex alternation of single-digit levels, e.g. ``(?:1|2|3)``."""
    levels = certified_levels() if certified else star_levels()
    return '(?:' + '|'.join(str(x) for x in levels) + ')'


def asterisk_quantifier() -> str:
    """Regex quantifier for the asterisk legend markers, e.g. ``{3,5}``."""
    levels = certified_levels()
    return '{%d,%d}' % (min(levels), max(levels))
