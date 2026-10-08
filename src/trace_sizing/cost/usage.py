"""The usage contract: every quantity the cost step prices, month by month.

The sizing report writes this as its "usage" block (trace-sizing --format
json); the cost step reads it with load_usage(). Nothing here knows about
prices. Units: GB are decimal (10^9 bytes), hours per month follow AWS's
730 h convention, and every series has one value per project month.
"""

from __future__ import annotations

import dataclasses
import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = "trace-usage/1"
HOURS_PER_MONTH = 730
DAYS_PER_MONTH = 365 / 12
TIERS = ("standard", "glacier_ir", "deep_archive")
GLUE_JOBS = ("etl", "maintenance", "features")


@dataclass
class VMUsage:
    name: str
    instance_type: str
    hours_per_month: float = HOURS_PER_MONTH
    ebs_gb: float = 0.0


@dataclass
class Usage:
    months: int
    vms: list[VMUsage]
    storage_gb: dict[str, list[float]]        # tier -> average GB stored during each month
    s3_requests: dict[str, list[float]]       # "put" / "get" -> requests per month
    transitions: dict[str, list[float]]       # tier -> objects moved into it per month
    glue_dpu_hours: dict[str, list[float]]    # job kind -> DPU-hours per month
    public_ipv4: int = 0
    nat_instances: int = 0
    egress_gb: list[float] = field(default_factory=list)
    retrieval_gb: dict[str, list[float]] = field(default_factory=dict)   # tier -> GB read back per month
    source: dict[str, Any] = field(default_factory=dict)                 # provenance, informational

    def __post_init__(self) -> None:
        if not self.egress_gb:
            self.egress_gb = [0.0] * self.months
        self.validate()

    def validate(self) -> None:
        if self.months <= 0:
            raise ValueError("usage: months must be positive")

        def check(name: str, series: list[float]) -> None:
            if len(series) != self.months:
                raise ValueError(f"usage: {name} has {len(series)} values, expected {self.months} (one per month)")
            if any(v < 0 for v in series):
                raise ValueError(f"usage: {name} has negative values")

        for kind, groups, allowed in [("storage_gb", self.storage_gb, TIERS),
                                      ("s3_requests", self.s3_requests, ("put", "get")),
                                      ("transitions", self.transitions, TIERS),
                                      ("glue_dpu_hours", self.glue_dpu_hours, None),
                                      ("retrieval_gb", self.retrieval_gb, TIERS)]:
            for key, series in groups.items():
                if allowed and key not in allowed:
                    raise ValueError(f"usage: unknown {kind} key {key!r} (expected one of {', '.join(allowed)})")
                check(f"{kind}.{key}", series)
        check("egress_gb", self.egress_gb)
        names = [v.name for v in self.vms]
        if len(names) != len(set(names)):
            raise ValueError("usage: VM names must be unique")

    # ---- serialisation
    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA, **dataclasses.asdict(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Usage":
        data = dict(data)
        schema = data.pop("schema", None)
        if schema != SCHEMA:
            raise ValueError(f"usage: schema is {schema!r}, expected {SCHEMA!r}")
        known = {f.name for f in dataclasses.fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"usage: unknown key(s): {', '.join(sorted(unknown))}")
        vms = [VMUsage(**v) for v in data.pop("vms", [])]
        return cls(vms=vms, **data)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n")

    # ---- VM overrides
    def with_vm_overrides(self, overrides: list[dict[str, Any]]) -> "Usage":
        """Return a copy with VMs changed, added or removed, matched by name.

        Each override is {"name": ..., plus any of instance_type, ebs_gb,
        hours_per_month, remove}. A name not in the usage adds a VM (it then
        needs instance_type); remove = true drops one.
        """
        vms = {v.name: dataclasses.replace(v) for v in self.vms}
        order = [v.name for v in self.vms]
        fields = {"instance_type", "ebs_gb", "hours_per_month"}
        for o in overrides:
            o = dict(o)
            name = o.pop("name", None)
            if not name:
                raise ValueError("VM override needs a name")
            remove = o.pop("remove", False)
            unknown = set(o) - fields
            if unknown:
                raise ValueError(f"VM override {name}: unknown field(s) {', '.join(sorted(unknown))}")
            if remove:
                if name not in vms:
                    raise ValueError(f"VM override {name}: can't remove, no VM of that name")
                del vms[name]
                order.remove(name)
                continue
            if name in vms:
                vms[name] = dataclasses.replace(vms[name], **o)
            else:
                if "instance_type" not in o:
                    raise ValueError(f"VM override {name}: new VM needs an instance_type")
                vms[name] = VMUsage(name=name, **o)
                order.append(name)
        return dataclasses.replace(self, vms=[vms[n] for n in order])


def load_usage(path: str | Path) -> Usage:
    """Read usage from a trace-sizing JSON report (its "usage" block) or from
    a standalone usage file (.json or .toml)."""
    path = Path(path)
    if path.suffix.lower() == ".toml":
        with open(path, "rb") as f:
            data = tomllib.load(f)
    else:
        data = json.loads(path.read_text())
    if "usage" in data and isinstance(data["usage"], dict):
        data = data["usage"]
    elif "schema" not in data:
        raise ValueError(
            f"{path}: not a usage file or trace-sizing JSON report. "
            "Create one with: trace-sizing config/trace_workload.toml --format json -o report.json"
        )
    return Usage.from_dict(data)


# --------------------------------------------------------------------------- from the sizing model

def usage_from_sizing(p, r) -> Usage:
    """Build the usage block from the sizing calculator's params and result."""
    from ..model import GB, STREAMS, stored_by_stream

    n = p.sizing.project_months
    w = r.workload
    steps = 30

    storage = {t: [] for t in TIERS}
    for m in range(n):
        acc = dict.fromkeys(TIERS, 0.0)
        for k in range(steps):                       # average over the month
            by_stream = stored_by_stream(p, w, (m + (k + 0.5) / steps) * DAYS_PER_MONTH)
            for t in TIERS:
                acc[t] += sum(by_stream[s][t] for s in STREAMS) / GB / steps
        for t in TIERS:
            storage[t].append(acc[t])

    cubes_per_day = w.hsi.cubes_per_day * p.hsi.operating_days_per_year / 365
    rq = p.requests
    puts = (cubes_per_day + w.lakehouse.iceberg_commits_per_day
            * (p.lakehouse.iceberg_objects_per_commit + rq.data_files_per_commit)) * DAYS_PER_MONTH

    retention_days = (p.sizing.retention_months * 365 / 12) if p.sizing.retention_months is not None else float("inf")

    def moved(threshold: float, m: int) -> float:
        if threshold >= retention_days:
            return 0.0                                # deleted before it would move
        cum = lambda t: cubes_per_day * max(0.0, t - threshold)
        return cum((m + 1) * DAYS_PER_MONTH) - cum(m * DAYS_PER_MONTH)

    g = p.glue
    glue = {
        "etl": g.etl_runs_per_hour * HOURS_PER_MONTH * g.etl_dpus * g.etl_minutes_per_run / 60,
        "maintenance": g.maintenance_runs_per_day * DAYS_PER_MONTH * g.maintenance_dpus
                       * g.maintenance_minutes_per_run / 60,
        "features": cubes_per_day * DAYS_PER_MONTH * g.feature_vcpu_seconds_per_cube / g.vcpu_per_dpu / 3600,
    }
    net = p.network
    return Usage(
        months=n,
        vms=[VMUsage(v.name, v.instance_type, HOURS_PER_MONTH, v.disk_gb) for v in p.vms],
        storage_gb=storage,
        s3_requests={"put": [puts] * n, "get": [puts * rq.gets_per_put] * n},
        transitions={"glacier_ir": [moved(p.storage.hsi_standard_days, m) for m in range(n)],
                     "deep_archive": [moved(p.storage.hsi_glacier_ir_until_days, m) for m in range(n)]},
        glue_dpu_hours={k: [v] * n for k, v in glue.items()},
        public_ipv4=net.public_ipv4_count,
        nat_instances=net.nat_instances,
        egress_gb=[net.egress_gb_month] * n,
        retrieval_gb={"glacier_ir": [net.glacier_ir_retrieval_gb_month] * n},
        source={"from": "trace-sizing", "project_months": n},
    )
