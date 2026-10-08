"""estimate(usage, prices, terms) -> CostEstimate.

Pure function: no file or report access. Usage says how much, PriceBook
says the AWS unit rates, Terms carries the non-AWS figures (exchange rate,
discount, VAT, budget, fixed monthly items).
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .prices import PriceBook
from .usage import HOURS_PER_MONTH, Usage


@dataclass
class FixedItem:
    item: str
    usd_month: float
    category: str = "Allowances"


@dataclass
class Terms:
    usd_to_eur: float = 0.87
    discount: float = 0.0                   # e.g. 0.12 for the OCRE AWS discount
    vat: float = 0.23                       # Irish VAT; 0 if recoverable
    budget_eur: float | None = 20000.0      # incl. VAT
    fixed: list[FixedItem] = field(default_factory=lambda: [
        FixedItem("ML training", 25.0),
        FixedItem("Logging and KMS", 10.0),
    ])

    def __post_init__(self) -> None:
        for name in ("usd_to_eur", "discount", "vat"):
            if getattr(self, name) < 0:
                raise ValueError(f"terms: {name} must be >= 0")
        if self.discount >= 1:
            raise ValueError("terms: discount is a fraction, e.g. 0.12 for 12%")


@dataclass
class CostLine:
    category: str
    item: str
    basis: str                  # how it's priced, human-readable
    monthly_usd: list[float]    # one entry per month

    @property
    def total_usd(self) -> float:
        return sum(self.monthly_usd)


@dataclass
class CostEstimate:
    usage: Usage
    prices: PriceBook
    terms: Terms
    lines: list[CostLine]

    @property
    def region(self) -> str:
        return self.prices.region

    @property
    def months(self) -> int:
        return self.usage.months

    @property
    def total_usd(self) -> float:
        return sum(l.total_usd for l in self.lines)

    @property
    def total_eur(self) -> float:
        return self.total_usd * self.terms.usd_to_eur

    @property
    def after_discount_eur(self) -> float:
        return self.total_eur * (1 - self.terms.discount)

    @property
    def total_incl_vat_eur(self) -> float:
        return self.after_discount_eur * (1 + self.terms.vat)

    @property
    def budget_headroom_eur(self) -> float | None:
        b = self.terms.budget_eur
        return None if b is None else b - self.total_incl_vat_eur

    def year_totals_usd(self) -> list[float]:
        return [sum(sum(l.monthly_usd[s:s + 12]) for l in self.lines) for s in range(0, self.months, 12)]

    def category_totals_usd(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for l in self.lines:
            out[l.category] = out.get(l.category, 0.0) + l.total_usd
        return out

    def summary(self) -> dict[str, Any]:
        return {
            "region": self.region, "months": self.months,
            "total_usd": self.total_usd, "total_eur": self.total_eur,
            "after_discount_eur": self.after_discount_eur, "total_incl_vat_eur": self.total_incl_vat_eur,
            "budget_eur": self.terms.budget_eur, "budget_headroom_eur": self.budget_headroom_eur,
            "year_totals_usd": self.year_totals_usd(), "category_totals_usd": self.category_totals_usd(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "lines": [{**dataclasses.asdict(l), "total_usd": l.total_usd} for l in self.lines],
            "prices": dataclasses.asdict(self.prices),
            "terms": dataclasses.asdict(self.terms),
            "usage": self.usage.to_dict(),
        }

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n")


def estimate(usage: Usage, prices: PriceBook, terms: Terms | None = None) -> CostEstimate:
    terms = terms or Terms()
    r = prices.rates
    n = usage.months
    lines: list[CostLine] = []

    def add(category: str, item: str, basis: str, monthly: list[float]) -> None:
        lines.append(CostLine(category, item, basis, monthly))

    # ---- Compute
    for vm in usage.vms:
        rate = prices.vm_rate(vm.instance_type)
        add("Compute", f"VM {vm.name} ({vm.instance_type})",
            f"${rate}/h x {vm.hours_per_month:g} h/month, on-demand",
            [rate * vm.hours_per_month] * n)
    ebs = sum(vm.ebs_gb for vm in usage.vms)
    if ebs:
        add("Compute", "EBS gp3 disks", f"{ebs:g} GB x ${r['ebs_gb_month']}/GB-month", [ebs * r["ebs_gb_month"]] * n)

    # ---- Networking
    if usage.public_ipv4:
        add("Networking", "Public IPv4 addresses", f"{usage.public_ipv4} x ${r['public_ipv4_hour']}/h",
            [usage.public_ipv4 * r["public_ipv4_hour"] * HOURS_PER_MONTH] * n)
    if usage.nat_instances:
        add("Networking", "NAT instance", f"{usage.nat_instances} x ${r['nat_instance_month']}/month",
            [usage.nat_instances * r["nat_instance_month"]] * n)
    if any(usage.egress_gb):
        add("Networking", "Data transfer out", f"GB out x ${r['egress_gb']}/GB",
            [gb * r["egress_gb"] for gb in usage.egress_gb])

    # ---- Storage
    for tier, key, label in [("standard", "s3_standard_gb_month", "S3 Standard"),
                             ("glacier_ir", "s3_glacier_ir_gb_month", "S3 Glacier Instant Retrieval"),
                             ("deep_archive", "s3_deep_archive_gb_month", "S3 Glacier Deep Archive")]:
        series = usage.storage_gb.get(tier, [0.0] * n)
        add("Storage", label, f"{sum(series):,.0f} GB-months x ${r[key]}/GB-month", [gb * r[key] for gb in series])

    put = usage.s3_requests.get("put", [0.0] * n)
    get = usage.s3_requests.get("get", [0.0] * n)
    add("Storage", "S3 requests (PUT + GET)",
        f"{sum(put):,.0f} PUT x ${r['s3_put_per_1000']}/1k + {sum(get):,.0f} GET x ${r['s3_get_per_1000']}/1k",
        [p_ / 1000 * r["s3_put_per_1000"] + g_ / 1000 * r["s3_get_per_1000"] for p_, g_ in zip(put, get)])

    to_ir = usage.transitions.get("glacier_ir", [0.0] * n)
    to_da = usage.transitions.get("deep_archive", [0.0] * n)
    add("Storage", "Lifecycle transitions",
        f"{sum(to_ir):,.0f} to Glacier IR x ${r['transition_glacier_ir_per_1000']}/1k "
        f"+ {sum(to_da):,.0f} to Deep Archive x ${r['transition_deep_archive_per_1000']}/1k",
        [a / 1000 * r["transition_glacier_ir_per_1000"] + b / 1000 * r["transition_deep_archive_per_1000"]
         for a, b in zip(to_ir, to_da)])

    ret = usage.retrieval_gb.get("glacier_ir", [0.0] * n)
    if any(ret):
        add("Storage", "Glacier IR retrievals", f"GB retrieved x ${r['glacier_ir_retrieval_gb']}/GB",
            [gb * r["glacier_ir_retrieval_gb"] for gb in ret])

    # ---- Processing
    if usage.glue_dpu_hours:
        monthly_dpu = [sum(s[m] for s in usage.glue_dpu_hours.values()) for m in range(n)]
        parts = ", ".join(f"{k} {sum(v) / n:.1f}" for k, v in usage.glue_dpu_hours.items())
        add("Processing", "AWS Glue ETL",
            f"{sum(monthly_dpu) / n:,.1f} DPU-h/month ({parts}) x ${r['glue_dpu_hour']}",
            [d * r["glue_dpu_hour"] for d in monthly_dpu])

    # ---- Fixed monthly items (from terms)
    for f in terms.fixed:
        add(f.category, f.item, f"${f.usd_month:g}/month", [f.usd_month] * n)

    return CostEstimate(usage=usage, prices=prices, terms=terms, lines=lines)
