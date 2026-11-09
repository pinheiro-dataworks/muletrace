"""Fetch public Pix aggregates from the BCB open-data API and freeze them as calibration targets.

The Pix-layer simulator is calibrated only to public aggregate figures. This script downloads
them from the Banco Central do Brasil open-data service (Olinda OData API), computes the
handful of targets the simulator uses and writes ``configs/calibration/bcb_public_figures.yaml``
with the source URL, the period covered and the access date. Run it again to refresh the
targets; the YAML is committed so that results are reproducible without network access.

Usage:
    uv run python scripts/fetch_bcb_calibration.py [--first-month 202510 --last-month 202609]
"""

from __future__ import annotations

import argparse
import json
import statistics
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

BASE_URL = "https://olinda.bcb.gov.br/olinda/servico/Pix_DadosAbertos/versao/v1/odata"
OUTPUT = Path("configs/calibration/bcb_public_figures.yaml")
TIMEOUT_SECONDS = 300


def fetch(resource: str, parameter: str, value: str, select: str | None = None) -> list[Any]:
    """Call one Olinda function and return its ``value`` list."""
    query = {f"@{parameter}": f"'{value}'", "$format": "json"}
    if select:
        query["$select"] = select
    url = f"{BASE_URL}/{resource}({parameter}=@{parameter})?{urllib.parse.urlencode(query)}"
    if not url.startswith("https://"):
        raise ValueError("only HTTPS endpoints are allowed")
    with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310  # nosec B310
        rows: list[Any] = json.load(response)["value"]
    return rows


def med_targets(first_month: int, last_month: int) -> dict[str, Any]:
    """Summarise MED dispute statistics over a closed range of months.

    The ``Database`` parameter of this endpoint is the first month returned; every later
    month is included, so the range is closed on the right here.
    """
    rows = [
        row
        for row in fetch("EstatisticasFraudesPix", "Database", str(first_month))
        if first_month <= row["AnoMes"] <= last_month
    ]
    months = sorted(row["AnoMes"] for row in rows)

    def total(field: str) -> float:
        return float(sum(row[field] for row in rows))

    accepted_value = total("ValorPixcontestadosaceitos")
    returned_value = total("ValorPixdevolvidosintegralmente") + total(
        "ValorPixdevolvidosparcialmente"
    )
    return {
        "source": f"{BASE_URL}/EstatisticasFraudesPix",
        "period": {"first_month": months[0], "last_month": months[-1], "n_months": len(months)},
        "disputes_filed": int(total("QtdePixcontestados")),
        "disputes_accepted": int(total("Qtdecontestacoesaceitas")),
        "disputes_rejected": int(total("Qtdecontestacoesrejeitadas")),
        "accepted_value_brl": round(accepted_value, 2),
        "accepted_per_100k_transfers_monthly_median": round(
            statistics.median(float(row["Qtdecontestacoesaceitasacada100mil"]) for row in rows), 4
        ),
        "rejection_share": round(
            total("Qtdecontestacoesrejeitadas") / total("QtdePixcontestados"), 4
        ),
        "mean_accepted_ticket_brl": round(accepted_value / total("Qtdecontestacoesaceitas"), 2),
        "returned_value_share": round(returned_value / accepted_value, 4),
        "not_returned_insufficient_balance_value_share": round(
            total("ValorPixnaodevolvidossaldoinsuficiente") / accepted_value, 4
        ),
    }


def key_mix_targets(stock_date: str) -> dict[str, Any]:
    """Share of each Pix key type in the stock of registered keys, by user type."""
    rows = fetch("ChavesPix", "Data", stock_date, select="Data,NaturezaUsuario,TipoChave,qtdChaves")
    latest = max(row["Data"] for row in rows)
    counts: Counter[tuple[str, str]] = Counter()
    for row in rows:
        if row["Data"] == latest:
            counts[(row["NaturezaUsuario"], row["TipoChave"])] += int(row["qtdChaves"])
    shares: dict[str, dict[str, float]] = {}
    for nature in sorted({nature for nature, _ in counts}):
        nature_total = sum(c for (n, _), c in counts.items() if n == nature)
        shares[nature] = {
            key_type: round(count / nature_total, 4)
            for (n, key_type), count in sorted(counts.items())
            if n == nature
        }
    return {
        "source": f"{BASE_URL}/ChavesPix",
        "stock_date": latest,
        "total_keys": sum(counts.values()),
        "share_by_user_type": shares,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--first-month", type=int, default=202510)
    parser.add_argument("--last-month", type=int, default=202609)
    parser.add_argument("--key-stock-date", default="2026-10-31")
    args = parser.parse_args()

    figures = {
        "publisher": "Banco Central do Brasil, Portal de Dados Abertos (Pix_DadosAbertos)",
        "accessed_on": datetime.now(tz=UTC).date().isoformat(),
        "med_disputes": med_targets(args.first_month, args.last_month),
        "pix_key_stock": key_mix_targets(args.key_stock_date),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    header = "# Generated by scripts/fetch_bcb_calibration.py. Do not edit by hand.\n"
    OUTPUT.write_text(
        header + yaml.safe_dump(figures, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
