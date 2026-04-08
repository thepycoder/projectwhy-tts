"""TTS text substitutions: per-word find-and-replace, literal or regex.

Each rule is applied to every WordPosition.text individually, in rule-list order.
Global rules run first, then any document sidecar rules are appended.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from projectwhy.core.models import Block


@dataclass
class SubstitutionRule:
    find: str
    replace: str
    use_regex: bool
    _compiled: re.Pattern | None = None

    def __post_init__(self) -> None:
        if self.use_regex:
            self._compiled = re.compile(self.find)

    def apply(self, text: str) -> str:
        if self.use_regex and self._compiled is not None:
            return self._compiled.sub(self.replace, text)
        return text.replace(self.find, self.replace)


def parse_rules(raw: list[dict]) -> list[SubstitutionRule]:
    """Build SubstitutionRule list from raw TOML dicts.

    Each dict must have 'find' and 'replace' string keys; 'regex' (bool) is optional.
    Raises ValueError for invalid regex patterns so mistakes surface immediately.
    """
    rules: list[SubstitutionRule] = []
    for i, entry in enumerate(raw):
        find = entry.get("find", "")
        replace = entry.get("replace", "")
        use_regex = bool(entry.get("regex", False))
        if not isinstance(find, str) or not isinstance(replace, str):
            raise ValueError(f"Rule #{i}: 'find' and 'replace' must be strings")
        if not find:
            continue
        if use_regex:
            try:
                re.compile(find)
            except re.error as exc:
                raise ValueError(f"Rule #{i}: invalid regex {find!r}: {exc}") from exc
        rules.append(SubstitutionRule(find=find, replace=replace, use_regex=use_regex))
    return rules


def apply_rules_to_word(text: str, rules: list[SubstitutionRule]) -> str:
    for rule in rules:
        text = rule.apply(text)
    return text


def block_tts_parts(block: Block, rules: list[SubstitutionRule]) -> list[str]:
    """Return one substituted string per block.words entry."""
    if not rules:
        return [w.text for w in block.words]
    return [apply_rules_to_word(w.text, rules) for w in block.words]


def block_tts_text(parts: list[str]) -> str:
    return " ".join(parts).strip()
