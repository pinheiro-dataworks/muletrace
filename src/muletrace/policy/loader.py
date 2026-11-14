"""Load the policy library and look entries up by topic words.

With fewer than a dozen entries a vector database would be overkill: lookup scores entries by
how many query words appear in their topics and title.
"""

from __future__ import annotations

import re
from functools import cache
from importlib import resources

import yaml
from pydantic import BaseModel, ConfigDict

_WORD = re.compile(r"[a-z0-9]+")


class PolicyEntry(BaseModel):
    """One summarised regulatory reference."""

    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    jurisdiction: str
    topics: tuple[str, ...]
    summary: str
    source: str


@cache
def load_policies() -> tuple[PolicyEntry, ...]:
    """Every entry of ``policy_library.yaml``, shipped with the package."""
    text = resources.files("muletrace.policy").joinpath("policy_library.yaml").read_text("utf-8")
    return tuple(PolicyEntry.model_validate(entry) for entry in yaml.safe_load(text)["entries"])


def lookup(query: str, limit: int = 3) -> list[PolicyEntry]:
    """Entries ranked by overlap between the query words and their topics and title."""
    words = set(_WORD.findall(query.lower()))
    scored = []
    for entry in load_policies():
        vocabulary = set(entry.topics) | set(_WORD.findall(entry.title.lower()))
        score = len(words & vocabulary)
        if score:
            scored.append((score, entry.id, entry))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [entry for _, _, entry in scored[:limit]]


def policy_ids() -> frozenset[str]:
    """Identifiers a case file may cite."""
    return frozenset(entry.id for entry in load_policies())
