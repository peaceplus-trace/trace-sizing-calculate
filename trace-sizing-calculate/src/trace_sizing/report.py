"""Render a Result as Markdown (readable in a terminal, pasteable into a doc)."""

from __future__ import annotations

from .model import GB, KB, MB, TB, Result
from .params import Params


def _n(x: float, d: int = 2) -> str:
    if x == 0:
        return "0"
    if abs(x) < 10 ** -d:
        return f"< {10 ** -d:g}"
    s = f"{x:,.{d}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def workload_md(p: Params, r: Result) -> str:
    w = r.workload
    i, h, a = w.iot, w.hsi, w.accumulated
    rows = [
        ["IoT events", f"{_n(i.msg_per_s)} msg/s", f"{_n(i.bytes_per_s / KB)} KB/s", f"{_n(i.bytes_per_day / GB)} GB"],
        [
            f"HSI cubes ({_n(p.hsi.upload_window_hours_per_day)} h window)"
            if h.is_peak_window
            else "HSI cubes (24h average)",
            f"{_n(h.cubes_per_s_peak, 4)} cubes/s"
            + (" peak" if h.is_peak_window else " avg"),
            f"{_n(h.total_bytes_per_s_peak / MB)} MB/s"
            + (" peak" if h.is_peak_window else " avg"),
            f"{_n(h.bytes_per_day / GB)} GB",
        ],
        [
            "**Total**",
            f"**{_n(w.peak_events_per_s)} events/s**",
            f"**{_n(w.peak_bytes_per_s / MB)} MB/s peak**",
            f"**{_n(a.day_bytes / GB)} GB**",
        ],
    ]
    lines = [
        "## Workload",
        "",
        f"- Sensors: {_n(i.sensors, 0)} ({_n(p.iot.pilot_sites)} sites x {p.iot.sensors_per_site}), "
        f"{_n(i.msgs_per_day, 0)} messages/day",
        f"- HSI: {_n(h.cube_bytes / MB)} MB/cube, {_n(h.cubes_per_site_per_day)} cubes/site/day, "
        f"{_n(h.cubes_per_day)} cubes/day across {_n(p.hsi.sites_with_camera)} camera sites",
        f"- HSI upload rate ({'peak, upload window' if h.is_peak_window else '24h average'}): "
        f"{_n(h.site_bytes_per_s_peak * 8 / MB)} Mbit/s per site, "
        f"{_n(h.total_bytes_per_s_peak * 8 / MB)} Mbit/s all sites",
        f"- HSI share of bytes: {_n(w.hsi_byte_share * 100, 1)} %",
        "",
        _table(["", "Write rate", "Throughput", "Daily volume"], rows),
        "",
        "### Accumulated raw volume (S3)",
        "",
        _table(
            ["Period", "Volume"],
            [
                ["1 day", f"{_n(a.day_bytes / GB, 1)} GB"],
                ["1 month", f"{_n(a.month_bytes / TB)} TB"],
                ["1 year", f"{_n(a.year_bytes / TB, 1)} TB"],
                [f"Project, total produced ({p.sizing.project_months} months)", f"{_n(a.project_bytes / TB, 1)} TB"],
                [
                    f"**Retained ({_n(a.retention_months, 1)} months)**"
                    + (" — storage plateaus here" if a.is_capped else " = whole project, nothing rolls off"),
                    f"**{_n(a.retained_bytes / TB, 1)} TB**",
                ],
            ],
        ),
        "",
        f"_Year = HSI x {p.hsi.operating_days_per_year} days + IoT x {p.iot.operating_days_per_year} days. "
        + (
            f"Retention is capped at {_n(a.retention_months, 1)} months (`sizing.retention_months`); "
            "older data rolls off, so provision storage for the Retained row, not the project total._"
            if a.is_capped
            else "No `sizing.retention_months` set (or it's ≥ project_months), so nothing rolls off and "
            "Retained equals the project total._"
        ),
    ]
    return "\n".join(lines)


def components_md(r: Result) -> str:
    rows = []
    for c in r.components + [r.total]:
        bold = c is r.total
        cells = [
            c.name,
            _n(c.cpu_load, 3),
            _n(c.vcpu),
            f"{_n(c.ram_gb)} GB",
            f"{_n(c.data_gb, 3)} GB",
            f"{_n(c.disk_gb)} GB",
        ]
        rows.append([f"**{x}**" for x in cells] if bold else cells)
    notes = []
    for c in r.components:
        if c.name.startswith("Kafka"):
            notes.append(
                f"- Kafka: {_n(c.notes['daily_volume_gb'], 3)} GB/day through Kafka, "
                f"{_n(c.notes['data_per_broker_gb'])} GB data / {_n(c.notes['disk_per_broker_gb'])} GB disk per broker"
            )
        elif c.name == "Flink":
            tm = f"TaskManager {_n(c.notes['taskmanager_gb'])} GB"
            if c.notes["taskmanager_resized"]:
                tm += " (grown above default — consider RocksDB state backend)"
            notes.append(
                f"- Flink: state {_n(c.notes['state_mb'])} MB, checkpoints {_n(c.notes['checkpoints_s3_mb'])} MB on S3, {tm}"
            )
        elif c.name == "Prometheus":
            notes.append(
                f"- Prometheus: {_n(c.notes['active_series'], 0)} active series, "
                f"{_n(c.notes['samples_per_s'], 0)} samples/s, RAM in use {_n(c.ram_load_gb)} GB"
            )
    return "\n".join(
        [
            "## Component sizing",
            "",
            _table(["Component", "CPU (load)", "vCPU (allocate)", "RAM (allocate)", "Data stored", "Disk (w/ headroom)"], rows),
            "",
            *notes,
        ]
    )


def fit_md(p: Params, r: Result) -> str:
    f = r.fit
    status = "FITS" if f.fits else "DOES NOT FIT"

    def row(label, req, cap, unit):
        pct = req / cap * 100 if cap else float("inf")
        return [label, f"{_n(req)} {unit}".strip(), f"{_n(cap)} {unit}".strip(), f"{_n(cap - req)} {unit}".strip(), f"{_n(pct, 0)} %"]

    vms = ", ".join(f"{v.name} ({_n(v.vcpu)} vCPU / {_n(v.ram_gib)} GiB / {_n(v.disk_gb)} GB)" for v in p.vms)
    return "\n".join(
        [
            f"## VM fit: {status}",
            "",
            f"Fleet: {vms}",
            "",
            _table(
                ["Resource", "Required (incl. OS)", "Capacity", "Remaining", "Used"],
                [
                    row("vCPU", f.required_vcpu, f.capacity_vcpu, ""),
                    row("RAM", f.required_ram_gb, f.capacity_ram_gb, "GB"),
                    row("Disk", f.required_disk_gb, f.capacity_disk_gb, "GB"),
                ],
            ),
            "",
            f"_OS overhead: {_n(p.sizing.os_ram_gb_per_vm)} GB RAM + {_n(p.sizing.os_disk_gb_per_vm)} GB disk per VM. "
            "Components not modelled (CKAN, PostgreSQL, Solr, Redis, MQTT, API) are only counted if "
            "listed under [[extra_components]]._",
        ]
    )


def scaling_md(table) -> str:
    rows = []
    for f, sp, r in table:
        k = r.components[0]
        prom = next(c for c in r.components if c.name == "Prometheus")
        rows.append(
            [
                f"{_n(f)}x",
                f"{_n(r.workload.iot.sensors, 0)} ({_n(sp.iot.pilot_sites)})",
                _n(r.workload.iot.msg_per_s, 1),
                f"{_n(r.workload.hsi.bytes_per_day / GB, 1)} GB",
                f"{_n(k.notes['disk_per_broker_gb'], 1)} GB",
                _n(prom.notes["active_series"], 0),
                _n(r.total.cpu_load, 3),
                _n(r.total.vcpu),
                f"{_n(r.total.ram_gb, 1)} GB",
                f"{_n(r.total.disk_gb, 1)} GB",
                "yes" if r.fit.fits else "**no**",
            ]
        )
    return "\n".join(
        [
            "## Scaling (sites x factor)",
            "",
            _table(
                ["Scale", "Sensors (sites)", "Msg/s", "HSI/day", "Kafka disk/broker", "Prom series",
                 "CPU load", "vCPU", "RAM", "Disk", "Fits VMs"],
                rows,
            ),
        ]
    )


def full_md(p: Params, r: Result, table=None) -> str:
    parts = ["# TRACE sizing report", "", workload_md(p, r), "", components_md(r), "", fit_md(p, r)]
    if table:
        parts += ["", scaling_md(table)]
    return "\n".join(parts) + "\n"
