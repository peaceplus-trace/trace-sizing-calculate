"""Render a Result as Markdown (readable in a terminal, pasteable into a doc)."""

from __future__ import annotations

import dataclasses

from .fmt import _n
from .formulas import formulas
from .model import GB, KB, MB, TB, Result
from .params import Params


def _table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def _value(x) -> str:
    if x is None:
        return "none"
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, float):
        return _n(x, 4)
    if isinstance(x, list):
        return ", ".join(_value(v) for v in x)
    return str(x)


_SECTIONS = ["iot", "hsi", "kafka", "flink", "prometheus", "grafana",
             "alerting", "redis", "lakehouse", "ml", "storage", "sizing"]


def params_md(p: Params) -> str:
    """Every resolved input value (TOML file + any --set overrides), so a
    report states exactly what it was computed from."""
    lines = ["## Parameters used", ""]
    for name in _SECTIONS:
        obj = getattr(p, name)
        rows = [[f.name, _value(getattr(obj, f.name))] for f in dataclasses.fields(obj)]
        lines += [f"**[{name}]**", "", _table(["Key", "Value"], rows), ""]
    if p.vms:
        rows = [[v.name, _n(v.vcpu), f"{_n(v.ram_gib)} GiB", f"{_n(v.disk_gb)} GB"] for v in p.vms]
        lines += ["**[[vms]]**", "", _table(["Name", "vCPU", "RAM", "Disk"], rows), ""]
    if p.extra_components:
        rows = [[e.name, _n(e.vcpu), f"{_n(e.ram_gb)} GB", f"{_n(e.disk_gb)} GB"] for e in p.extra_components]
        lines += ["**[[extra_components]]**", "", _table(["Name", "vCPU", "RAM", "Disk"], rows), ""]
    return "\n".join(lines).rstrip()


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


def lakehouse_md(r: Result) -> str:
    lh, ml = r.workload.lakehouse, r.workload.ml
    return "\n".join(
        [
            "## Data Lake pipeline & ML (Bronze/Silver/Gold)",
            "",
            "_Informational - like Accumulated raw volume above, S3/Glue aren't part of the VM fleet_",
            "_so none of this counts toward VM fit._",
            "",
            _table(
                ["Layer", "HSI", "IoT", "Total/day"],
                [
                    ["Bronze (landed as-is)", f"{_n(lh.bronze_hsi_bytes_per_day / GB, 1)} GB",
                     f"{_n(lh.bronze_iot_bytes_per_day / GB, 2)} GB", f"{_n(lh.bronze_bytes_per_day / GB, 1)} GB"],
                    ["Silver (conformed; HSI = feature vectors only)", f"{_n(lh.silver_hsi_bytes_per_day / MB)} MB",
                     f"{_n(lh.silver_iot_bytes_per_day / MB)} MB", f"{_n(lh.silver_bytes_per_day / MB)} MB"],
                    ["Gold (curated aggregates)", f"{_n(lh.gold_hsi_bytes_per_day / MB)} MB",
                     f"{_n(lh.gold_iot_bytes_per_day / MB)} MB", f"{_n(lh.gold_bytes_per_day / MB)} MB"],
                ],
            ),
            "",
            f"- Iceberg metadata: {_n(lh.iceberg_commits_per_day, 0)} commits/day across the "
            f"Bronze/Silver/Gold tables, {_n(lh.iceberg_objects_per_day, 0)} new objects/day, "
            f"{_n(lh.iceberg_metadata_bytes_per_day / MB)} MB/day of metadata bytes "
            "(watch the object count, not the bytes - it drives S3 request cost and Glue Catalog limits; "
            "see the compaction/snapshot-expiry item in the Storage Scalability checklist)",
            f"- ML model artifacts: {_n(ml.model_artifact_total_bytes / MB)} MB total "
            "(fixed, versioned store - retraining is periodic, not a daily rate)",
            f"- ML predictions written back: {_n(ml.prediction_events_per_day, 0)} events/day, "
            f"{_n(ml.prediction_bytes_per_day / MB)} MB/day",
        ]
    )


def storage_md(p: Params, r: Result) -> str:
    st = r.storage
    sp = p.storage
    labels = {"standard": "S3 Standard", "glacier_ir": "Glacier Instant Retrieval", "deep_archive": "Glacier Deep Archive"}
    milestone_rows = []
    for tier in ("standard", "glacier_ir", "deep_archive"):
        milestone_rows.append([labels[tier]] + [f"{_n(m[tier] / GB, 1)} GB" for m in st.milestones])
    totals = [m["standard"] + m["glacier_ir"] + m["deep_archive"] for m in st.milestones]
    milestone_rows.append(["**Total stored**"] + [f"**{_n(t / GB, 1)} GB**" for t in totals])
    headers = ["Tier"] + [m["label"] for m in st.milestones]

    names = {"hsi_raw": "Raw HSI cubes", "iot_raw": "Raw IoT scalar data",
             "silver": "Silver (incl. overhead)", "gold": "Gold (incl. overhead)"}
    stream_rows = []
    for stream in ("hsi_raw", "iot_raw", "silver", "gold"):
        e = st.end_by_stream[stream]
        row_total = e["standard"] + e["glacier_ir"] + e["deep_archive"]
        stream_rows.append([names[stream]] + [f"{_n(e[t] / GB, 1)} GB" for t in ("standard", "glacier_ir", "deep_archive")]
                           + [f"**{_n(row_total / GB, 1)} GB**"])
    return "\n".join([
        "## S3 storage by tier (retention policy)",
        "",
        f"_Raw HSI: Standard for the first {_n(sp.hsi_standard_days)} days, Glacier IR until "
        f"{_n(sp.hsi_glacier_ir_until_days)} days, then Deep Archive. "
        f"Raw IoT: {sp.iot_raw_tier} for its whole life. "
        f"Silver and Gold: Standard, with {_n(sp.silver_gold_overhead * 100)}% versioning overhead._",
        "",
        _table(headers, milestone_rows),
        "",
        "**At end of project, by stream**",
        "",
        _table(["Stream", "S3 Standard", "Glacier IR", "Deep Archive", "Total"], stream_rows),
    ])


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
        elif c.name.startswith("Redis"):
            notes.append(
                f"- Redis: {_n(c.notes['keys'], 0)} keys (latest reading/prediction per sensor + "
                f"HSI site), overwritten in place - not an accumulating stream"
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
            "Components not modelled (CKAN, PostgreSQL, Solr, the CKAN Redis instance, MQTT, API) are only counted if "
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


def formulas_md(p: Params, r: Result) -> str:
    """Every derived number, its formula, and this run's values substituted in."""
    out = ["## Formulas", "",
           "_Each derived number, its formula (as in `model.py`), and this run's values substituted in._", ""]
    by_section: dict[str, list] = {}
    for f in formulas(p, r):
        by_section.setdefault(f.section, []).append(
            [f.quantity, f"`{f.formula}`", f.worked, f"**{f.result}**"]
        )
    for section, rows in by_section.items():
        out += [f"**{section}**", "", _table(["Quantity", "Formula", "This run", "Result"], rows), ""]
    return "\n".join(out).rstrip()


def _cost_summary_rows(c, money):
    rows = [["Subtotal (USD)", money(c.total_usd, "$")],
            [f"In EUR (x {_n(c.usd_to_eur)})", money(c.total_eur, "EUR ")]]
    if c.discount:
        rows.append([f"After {_n(c.discount * 100)}% discount", money(c.after_discount_eur, "EUR ")])
    rows.append([f"Incl. {_n(c.vat * 100)}% VAT", money(c.total_incl_vat_eur, "EUR ")])
    if c.budget_eur:
        diff = c.budget_eur - c.total_incl_vat_eur
        rows.append([f"Budget (EUR {c.budget_eur:,.0f})",
                     (f"under by EUR {diff:,.0f}" if diff >= 0 else f"OVER by EUR {-diff:,.0f}")])
    return rows


def cost_md(r: Result) -> str:
    c = r.cost
    money = lambda x, cur="$": f"{cur}{x:,.0f}"
    line_rows = [[l.category, l.item, l.basis, money(l.total_usd / c.months), f"**{money(l.total_usd)}**"]
                 for l in c.lines]
    years = c.year_totals_usd()
    cats = c.category_totals_usd()
    return "\n".join([
        f"## AWS cost estimate ({c.months} months, {c.region})",
        "",
        "_On-demand list prices from AWS's public price list (USD, ex. tax), applied to the volumes above. "
        "Assumes every site is live from month 1, so it errs high for a phased roll-out._",
        "",
        _table(["", "Amount"], [[k, f"**{v}**" if i == 0 or k.startswith("Incl") else v]
                                for i, (k, v) in enumerate(_cost_summary_rows(c, money))]),
        "",
        "**By year**",
        "",
        _table(["Year", "USD", "EUR"], [[f"Year {i + 1}", money(y), money(y * c.usd_to_eur, "EUR ")]
                                         for i, y in enumerate(years)]),
        "",
        "**By category**",
        "",
        _table(["Category", "USD", "Share"], [[k, money(v), f"{v / c.total_usd * 100:.0f}%"] for k, v in cats.items()]),
        "",
        "**Line items**",
        "",
        _table(["Category", "Item", "Basis", "Avg/month", "Total"], line_rows),
    ])


def full_md(p: Params, r: Result, table=None, show_params: bool = True, show_formulas: bool = True) -> str:
    parts = ["# TRACE sizing report", ""]
    if show_params:
        parts += [params_md(p), ""]
    parts += [
        workload_md(p, r), "",
        lakehouse_md(r), "",
        storage_md(p, r), "",
        components_md(r), "",
        fit_md(p, r), "",
        cost_md(r),
    ]
    if show_formulas:
        parts += ["", formulas_md(p, r)]
    if table:
        parts += ["", scaling_md(table)]
    return "\n".join(parts) + "\n"
