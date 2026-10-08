"""Load config/cost.toml: region, price overrides, terms, fixed monthly items,
and VM overrides. Everything in it is about money, not workload."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from .estimate import FixedItem, Terms
from .prices import PriceBook

_TOP = {"region", "terms", "prices", "fixed", "vms"}


@dataclass
class CostConfig:
    prices: PriceBook
    terms: Terms
    vm_overrides: list[dict[str, Any]] = field(default_factory=list)


def from_dict(data: dict[str, Any]) -> CostConfig:
    unknown = set(data) - _TOP
    if unknown:
        raise ValueError(f"cost config: unknown key(s) {', '.join(sorted(unknown))}; expected {', '.join(sorted(_TOP))}")

    prices = PriceBook.for_region(data.get("region", "eu-west-1"))
    rate_overrides = dict(data.get("prices", {}))
    vm_prices = rate_overrides.pop("vm_hourly", {})
    prices = prices.override(**rate_overrides).with_vm_prices(vm_prices)

    t = dict(data.get("terms", {}))
    known = {f.name for f in fields(Terms)} - {"fixed"}
    unknown = set(t) - known
    if unknown:
        raise ValueError(f"cost config [terms]: unknown key(s) {', '.join(sorted(unknown))}")
    if t.get("budget_eur") == 0:
        t["budget_eur"] = None                      # 0 = no budget to compare against
    if "fixed" in data:
        t["fixed"] = [FixedItem(**f) for f in data["fixed"]]
    return CostConfig(prices=prices, terms=Terms(**t), vm_overrides=list(data.get("vms", [])))


def load(path: str | Path | None) -> CostConfig:
    """Load a cost config; with no path, the built-in eu-west-1 defaults."""
    if path is None:
        return from_dict({})
    with open(path, "rb") as f:
        return from_dict(tomllib.load(f))
