"""Render documents whose numbers come from ``docs/generated/*.yaml``.

Published documents with results (``docs/eval_report.md`` and others) are rendered from
templates in ``docs/templates/``. A template is ordinary Markdown with placeholders::

    Recall is {{ backtest_HI-Small.hold_out.rules_tuned[alerts_per_10k=20].recall | pct }}.

* the first path segment names a source file by its stem (``backtest_HI-Small`` →
  ``docs/generated/backtest_HI-Small.yaml``; ``bcb_public_figures`` →
  ``configs/calibration/bcb_public_figures.yaml``);
* dotted segments walk dictionaries; ``[key=value]`` picks the list item whose ``key`` equals
  ``value``; ``[n]`` picks the n-th item;
* an optional filter formats the value.

A test re-renders every template and fails if a committed document differs, so a number cannot
be edited by hand or go stale.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

_PLACEHOLDER = re.compile(r"\{\{\s*(?P<path>[^|}]+?)\s*(?:\|\s*(?P<filter>\w+)\s*)?\}\}")
_SELECTOR = re.compile(r"^(?P<key>[^\[\]]+)?(?:\[(?P<selector>[^\]]+)\])?$")


class RenderError(KeyError):
    """Raised when a placeholder does not resolve."""


def _percent(digits: int) -> Callable[[Any], str]:
    return lambda value: f"{100 * float(value):.{digits}f}%"


def _interval(value: Any) -> str:  # noqa: ANN401 - a two-item list from YAML
    low, high = value
    return f"{100 * float(low):.1f} to {100 * float(high):.1f}%"


FILTERS: dict[str, Callable[[Any], str]] = {
    "pct": _percent(1),
    "pct2": _percent(2),
    "ci": _interval,
    "int": lambda value: f"{round(float(value)):,}",
    "billions": lambda value: f"{float(value) / 1e9:.2f}",
    "f2": lambda value: f"{float(value):.2f}",
    "f3": lambda value: f"{float(value):.3f}",
    "f4": lambda value: f"{float(value):.4f}",
    "raw": str,
}


def _select(items: list[Any], selector: str) -> Any:  # noqa: ANN401 - YAML values
    if selector.isdigit():
        return items[int(selector)]
    key, _, expected = selector.partition("=")
    for item in items:
        if str(item.get(key)) == expected or _same_number(item.get(key), expected):
            return item
    raise RenderError(f"no item with {selector}")


def _same_number(value: Any, expected: str) -> bool:  # noqa: ANN401 - YAML values
    try:
        return float(value) == float(expected)
    except (TypeError, ValueError):
        return False


def resolve(path: str, sources: dict[str, Any]) -> Any:  # noqa: ANN401 - YAML values
    """Walk ``path`` through the generated sources."""
    source, _, rest = path.strip().partition(".")
    if source not in sources:
        raise RenderError(f"unknown source {source!r}")
    value = sources[source]
    for segment in filter(None, rest.split(".")):
        match = _SELECTOR.match(segment)
        if match is None:
            raise RenderError(f"bad segment {segment!r} in {path!r}")
        if match["key"]:
            try:
                value = value[match["key"]]
            except (KeyError, TypeError) as error:
                raise RenderError(f"{path!r}: missing {match['key']!r}") from error
        if match["selector"]:
            value = _select(value, match["selector"])
    return value


def render(template: str, sources: dict[str, Any]) -> str:
    """Replace every placeholder in ``template``."""

    def substitute(match: re.Match[str]) -> str:
        value = resolve(match["path"], sources)
        name = match["filter"] or "raw"
        if name not in FILTERS:
            raise RenderError(f"unknown filter {name!r}")
        return FILTERS[name](value)

    return _PLACEHOLDER.sub(substitute, template)


def load_sources(*source_dirs: Path) -> dict[str, Any]:
    """Every YAML file in ``source_dirs``, keyed by its stem (stems must be unique)."""
    sources: dict[str, Any] = {}
    for folder in source_dirs:
        for path in sorted(folder.glob("*.yaml")):
            if path.stem in sources:
                raise RenderError(f"duplicate source name {path.stem!r}")
            sources[path.stem] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return sources


def render_documents(
    template_dir: Path, source_dirs: tuple[Path, ...], output_dir: Path
) -> list[Path]:
    """Render every ``*.md`` template into ``output_dir``; returns the written paths."""
    sources = load_sources(*source_dirs)
    written = []
    for template in sorted(template_dir.glob("*.md")):
        target = output_dir / template.name
        target.write_text(
            render(template.read_text(encoding="utf-8"), sources), encoding="utf-8", newline="\n"
        )
        written.append(target)
    return written
