"""AWS cost estimate over the project (sizing.project_months).

Prices come from PRICE_BOOK, checked against AWS's public price list
(pricing.us-east-1.amazonaws.com/offers) on 2026-10-08: on-demand Linux,
USD, excluding tax. Any price can be overridden in [pricing]. Usage comes
from the same Result the rest of the report uses, so storage cost follows
the [storage] retention policy month by month.

Assumes every site is live from month 1 (no onboarding ramp), so it errs
high against a phased roll-out.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import GB, Result, stored_by_stream, STREAMS
from .params import Params

HOURS_PER_MONTH = 730            # AWS billing convention
DAYS_PER_MONTH = 365 / 12

PRICE_BOOK: dict[str, dict[str, float]] = {
    "us-east-1": {
        "vm_hourly:m7g.xlarge": 0.1632,
        "ebs_gb_month": 0.08,
        "s3_standard_gb_month": 0.023,          # first 50 TB
        "s3_glacier_ir_gb_month": 0.004,
        "s3_deep_archive_gb_month": 0.00099,
        "s3_put_per_1000": 0.005,
        "s3_get_per_1000": 0.0004,
        "transition_glacier_ir_per_1000": 0.02,
        "transition_deep_archive_per_1000": 0.05,
        "glacier_ir_retrieval_gb": 0.03,
        "glue_dpu_hour": 0.44,
    },
    "eu-west-1": {
        "vm_hourly:m7g.xlarge": 0.1819,
        "ebs_gb_month": 0.088,
        "s3_standard_gb_month": 0.023,          # first 50 TB
        "s3_glacier_ir_gb_month": 0.004,
        "s3_deep_archive_gb_month": 0.00099,
        "s3_put_per_1000": 0.005,
        "s3_get_per_1000": 0.0004,
        "transition_glacier_ir_per_1000": 0.02,
        "transition_deep_archive_per_1000": 0.055,
        "glacier_ir_retrieval_gb": 0.03,
        "glue_dpu_hour": 0.44,
    },
}


@dataclass
class CostLine:
    category: str
    item: str
    basis: str                  # how it's priced, human-readable
    monthly_usd: list[float]    # one entry per project month

    @property
    def total_usd(self) -> float:
        return sum(self.monthly_usd)


@dataclass
class CostEstimate:
    region: str
    months: int
    lines: list[CostLine]
    usd_to_eur: float
    discount: float
    vat: float
    budget_eur: float | None
    prices: dict[str, float] = field(default_factory=dict)

    @property
    def total_usd(self) -> float:
        return sum(l.total_usd for l in self.lines)

    @property
    def total_eur(self) -> float:
        return self.total_usd * self.usd_to_eur

    @property
    def after_discount_eur(self) -> float:
        return self.total_eur * (1 - self.discount)

    @property
    def total_incl_vat_eur(self) -> float:
        return self.after_discount_eur * (1 + self.vat)

    def year_totals_usd(self) -> list[float]:
        out = []
        for start in range(0, self.months, 12):
            out.append(sum(sum(l.monthly_usd[start:start + 12]) for l in self.lines))
        return out

    def category_totals_usd(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for l in self.lines:
            out[l.category] = out.get(l.category, 0.0) + l.total_usd
        return out


def prices_for(p: Params) -> dict[str, float]:
    pr = p.pricing
    if pr.region not in PRICE_BOOK:
        raise ValueError(f"[pricing] region must be one of: {', '.join(PRICE_BOOK)}")
    book = dict(PRICE_BOOK[pr.region])
    overrides = {
        "ebs_gb_month": pr.ebs_gb_month_usd,
        "s3_standard_gb_month": pr.s3_standard_gb_month_usd,
        "s3_glacier_ir_gb_month": pr.s3_glacier_ir_gb_month_usd,
        "s3_deep_archive_gb_month": pr.s3_deep_archive_gb_month_usd,
        "glue_dpu_hour": pr.glue_dpu_hour_usd,
    }
    book.update({k: v for k, v in overrides.items() if v is not None})
    return book


def vm_hourly(p: Params, vm, book: dict[str, float]) -> float:
    if vm.hourly_usd is not None:
        return vm.hourly_usd
    key = f"vm_hourly:{vm.instance_type}"
    if key not in book:
        raise ValueError(f"[[vms]] {vm.name}: no price for {vm.instance_type} in {p.pricing.region}; set hourly_usd")
    return book[key]


def _gb_months_by_tier(p: Params, r: Result, month: int) -> dict[str, float]:
    """GB-months stored per tier during one project month (daily integration)."""
    w = r.workload
    steps = 30
    out = {"standard": 0.0, "glacier_ir": 0.0, "deep_archive": 0.0}
    for k in range(steps):
        t = (month + (k + 0.5) / steps) * DAYS_PER_MONTH
        by_stream = stored_by_stream(p, w, t)
        for tier in out:
            out[tier] += sum(by_stream[s][tier] for s in STREAMS) / GB / steps
    return out


def glue_dpu_hours_per_month(p: Params, r: Result) -> dict[str, float]:
    pr = p.pricing
    cubes_per_day = r.workload.hsi.cubes_per_day * p.hsi.operating_days_per_year / 365
    return {
        "etl": pr.etl_runs_per_hour * HOURS_PER_MONTH * pr.etl_dpus * pr.etl_minutes_per_run / 60,
        "maintenance": pr.maintenance_runs_per_day * DAYS_PER_MONTH * pr.maintenance_dpus
                       * pr.maintenance_minutes_per_run / 60,
        "features": cubes_per_day * DAYS_PER_MONTH * pr.feature_vcpu_seconds_per_cube / pr.vcpu_per_dpu / 3600,
    }


def requests_per_month(p: Params, r: Result) -> dict[str, float]:
    pr = p.pricing
    lh = r.workload.lakehouse
    cubes_per_day = r.workload.hsi.cubes_per_day * p.hsi.operating_days_per_year / 365
    puts = (cubes_per_day
            + lh.iceberg_commits_per_day * (p.lakehouse.iceberg_objects_per_commit + pr.data_files_per_commit)
            ) * DAYS_PER_MONTH
    return {"put": puts, "get": puts * pr.gets_per_put, "cubes_per_day": cubes_per_day}


def _transitions(p: Params, cubes_per_day: float, threshold_days: float, month: int) -> float:
    """Cubes whose age crosses threshold_days during this month (lifecycle requests)."""
    retention_days = (p.sizing.retention_months * 365 / 12) if p.sizing.retention_months is not None else float("inf")
    if threshold_days >= retention_days:
        return 0.0                              # deleted before it would move

    def cum(t):
        return cubes_per_day * max(0.0, t - threshold_days)
    return cum((month + 1) * DAYS_PER_MONTH) - cum(month * DAYS_PER_MONTH)


def cost_estimate(p: Params, r: Result) -> CostEstimate:
    pr, sp = p.pricing, p.storage
    book = prices_for(p)
    n = p.sizing.project_months
    lines: list[CostLine] = []

    def add(category, item, basis, per_month):
        lines.append(CostLine(category, item, basis, [per_month(m) for m in range(n)]))

    # ---- Compute and networking (fixed per month)
    for vm in p.vms:
        rate = vm_hourly(p, vm, book)
        add("Compute", f"VM {vm.name} ({vm.instance_type})", f"${rate}/h x {HOURS_PER_MONTH} h/month, on-demand 24/7",
            lambda m, rate=rate: rate * HOURS_PER_MONTH)
    disk = sum(vm.disk_gb for vm in p.vms)
    add("Compute", "EBS gp3 disks", f"{disk:g} GB x ${book['ebs_gb_month']}/GB-month",
        lambda m: disk * book["ebs_gb_month"])
    add("Networking", "Public IPv4 addresses", f"{pr.public_ipv4_count} x ${pr.public_ipv4_hourly_usd}/h",
        lambda m: pr.public_ipv4_count * pr.public_ipv4_hourly_usd * HOURS_PER_MONTH)
    add("Networking", "NAT instance", f"${pr.nat_instance_usd_month}/month",
        lambda m: pr.nat_instance_usd_month)
    if pr.egress_gb_month:
        add("Networking", "Data transfer out", f"{pr.egress_gb_month:g} GB/month x ${pr.egress_gb_usd}/GB",
            lambda m: pr.egress_gb_month * pr.egress_gb_usd)

    # ---- S3 storage (grows month by month, follows the retention policy)
    gbm = [_gb_months_by_tier(p, r, m) for m in range(n)]
    for tier, key, label in [("standard", "s3_standard_gb_month", "S3 Standard"),
                             ("glacier_ir", "s3_glacier_ir_gb_month", "S3 Glacier Instant Retrieval"),
                             ("deep_archive", "s3_deep_archive_gb_month", "S3 Glacier Deep Archive")]:
        add("Storage", label, f"GB-months stored x ${book[key]}/GB-month",
            lambda m, tier=tier, key=key: gbm[m][tier] * book[key])

    # ---- S3 requests, lifecycle transitions, retrievals
    req = requests_per_month(p, r)
    add("Storage", "S3 requests (PUT + GET)",
        f"{req['put']:,.0f} PUT x ${book['s3_put_per_1000']}/1k + {req['get']:,.0f} GET x ${book['s3_get_per_1000']}/1k per month",
        lambda m: req["put"] / 1000 * book["s3_put_per_1000"] + req["get"] / 1000 * book["s3_get_per_1000"])
    cpd = req["cubes_per_day"]
    add("Storage", "Lifecycle transitions",
        f"cubes moving to Glacier IR x ${book['transition_glacier_ir_per_1000']}/1k "
        f"+ to Deep Archive x ${book['transition_deep_archive_per_1000']}/1k",
        lambda m: _transitions(p, cpd, sp.hsi_standard_days, m) / 1000 * book["transition_glacier_ir_per_1000"]
        + _transitions(p, cpd, sp.hsi_glacier_ir_until_days, m) / 1000 * book["transition_deep_archive_per_1000"])
    if pr.glacier_ir_retrieval_gb_month:
        add("Storage", "Glacier IR retrievals",
            f"{pr.glacier_ir_retrieval_gb_month:g} GB/month x ${book['glacier_ir_retrieval_gb']}/GB",
            lambda m: pr.glacier_ir_retrieval_gb_month * book["glacier_ir_retrieval_gb"])

    # ---- Processing
    dpu = glue_dpu_hours_per_month(p, r)
    dpu_total = sum(dpu.values())
    add("Processing", "AWS Glue ETL",
        f"{dpu_total:,.1f} DPU-h/month (ETL {dpu['etl']:.1f}, maintenance {dpu['maintenance']:.1f}, "
        f"HSI features {dpu['features']:.1f}) x ${book['glue_dpu_hour']}",
        lambda m: dpu_total * book["glue_dpu_hour"])

    # ---- Allowances
    add("Allowances", "ML training", f"${pr.ml_training_usd_month}/month", lambda m: pr.ml_training_usd_month)
    add("Allowances", "Logging and KMS", f"${pr.logging_kms_usd_month}/month", lambda m: pr.logging_kms_usd_month)

    return CostEstimate(region=pr.region, months=n, lines=lines, usd_to_eur=pr.usd_to_eur,
                        discount=pr.discount, vat=pr.vat, budget_eur=pr.budget_eur, prices=book)
