from pathlib import Path

import pytest
import yaml

from muletrace.reporting import RenderError, load_sources, render, render_documents, resolve

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCES = {
    "backtest_HI-Small": {
        "hold_out": {
            "m": [
                {"alerts_per_10k": 20.0, "recall": 0.1845},
                {"alerts_per_10k": 5.0, "recall": 0.1},
            ]
        },
        "bootstrap": {"recall": {"m": {"ci95": [0.1703, 0.2004]}}},
        "n": 2152,
    }
}


def test_resolve_walks_keys_and_selectors() -> None:
    assert resolve("backtest_HI-Small.hold_out.m[alerts_per_10k=20].recall", SOURCES) == 0.1845
    assert resolve("backtest_HI-Small.hold_out.m[1].recall", SOURCES) == 0.1


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("{{ backtest_HI-Small.hold_out.m[alerts_per_10k=20].recall | pct }}", "18.4%"),
        ("{{backtest_HI-Small.bootstrap.recall.m.ci95|ci}}", "17.0 to 20.0%"),
        ("{{ backtest_HI-Small.n | int }} positives", "2,152 positives"),
        ("{{ backtest_HI-Small.n }}", "2152"),
    ],
)
def test_render_filters(template: str, expected: str) -> None:
    assert render(template, SOURCES) == expected


@pytest.mark.parametrize(
    "template",
    [
        "{{ nowhere.x }}",
        "{{ backtest_HI-Small.missing }}",
        "{{ backtest_HI-Small.hold_out.m[alerts_per_10k=99] }}",
        "{{ backtest_HI-Small.n | nofilter }}",
        "{{ backtest_HI-Small.hold_out.m[a[b] }}",
    ],
)
def test_unresolvable_placeholders_fail_loudly(template: str) -> None:
    with pytest.raises(RenderError):
        render(template, SOURCES)


def test_render_documents(tmp_path: Path) -> None:
    (tmp_path / "templates").mkdir()
    (tmp_path / "generated").mkdir()
    (tmp_path / "out").mkdir()
    (tmp_path / "generated" / "x.yaml").write_text(yaml.safe_dump({"v": 0.5}), "utf-8")
    (tmp_path / "templates" / "doc.md").write_text("Value: {{ x.v | pct }}\n", "utf-8")
    written = render_documents(tmp_path / "templates", (tmp_path / "generated",), tmp_path / "out")
    assert written[0].read_text("utf-8") == "Value: 50.0%\n"


def test_committed_documents_match_their_templates() -> None:
    """Published numbers cannot be edited by hand or go stale."""
    sources = load_sources(REPO_ROOT / "docs" / "generated", REPO_ROOT / "configs" / "calibration")
    for template in sorted((REPO_ROOT / "docs" / "templates").glob("*.md")):
        committed = (REPO_ROOT / "docs" / template.name).read_text(encoding="utf-8")
        assert committed == render(template.read_text(encoding="utf-8"), sources), template.name


def test_duplicate_source_names_are_rejected(tmp_path: Path) -> None:
    for folder in ("a", "b"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "same.yaml").write_text("x: 1\n", "utf-8")
    with pytest.raises(RenderError, match="duplicate"):
        load_sources(tmp_path / "a", tmp_path / "b")
