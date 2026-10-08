"""Render a Result as a single, self-contained HTML page (no external assets).

Mirrors report.py's Markdown sections one-for-one and reuses its number
formatting (`_n`, `_value`) so the two formats always agree; this module is
presentation only, same as report.py - no new calculations.
"""

from __future__ import annotations

import dataclasses

from .model import GB, MB, Result
from .params import Params
from .formulas import formulas
from .fmt import _n
from .htmlkit import _anchor, _esc, _h3, _section, _slug, _table, page
from .report import _SECTIONS, _value


def _params_section(p: Params) -> str:
    blocks = []
    for name in _SECTIONS:
        obj = getattr(p, name)
        rows = [[f"<code>{_esc(f.name)}</code>", _esc(_value(getattr(obj, f.name)))]
                for f in dataclasses.fields(obj)]
        blocks.append(_h3(f"[{name}]", "params", _slug(name))
                      + _table(["Key", "Value"], rows, tid=f"params--{name}",
                               keys=[_slug(f.name) for f in dataclasses.fields(obj)]))
    if p.vms:
        rows = [[_esc(v.name), _esc(_n(v.vcpu)), f"{_esc(_n(v.ram_gib))} GiB", f"{_esc(_n(v.disk_gb))} GB"]
                for v in p.vms]
        blocks.append(_h3("[[vms]]", "params", "vms")
                      + _table(["Name", "vCPU", "RAM", "Disk"], rows, tid="params--vms"))
    if p.extra_components:
        rows = [[_esc(e.name), _esc(_n(e.vcpu)), f"{_esc(_n(e.ram_gb))} GB", f"{_esc(_n(e.disk_gb))} GB"]
                for e in p.extra_components]
        blocks.append(_h3("[[extra_components]]", "params", "extra-components")
                      + _table(["Name", "vCPU", "RAM", "Disk"], rows, tid="params--extra-components"))
    body = f"<details><summary>Show all {len(_SECTIONS)} sections</summary>{''.join(blocks)}</details>"
    return _section("Parameters used", body,
                     "Every resolved input value - the TOML file plus any --set overrides.", sid="params")


def _workload_section(p: Params, r: Result) -> str:
    w = r.workload
    i, h, a = w.iot, w.hsi, w.accumulated
    rate_rows = [
        ["IoT events", f"{_n(i.msg_per_s)} msg/s", f"{_n(i.bytes_per_s / 1e3)} KB/s", f"{_n(i.bytes_per_day / GB)} GB"],
        [
            f"HSI cubes ({_n(p.hsi.upload_window_hours_per_day)} h window)" if h.is_peak_window else "HSI cubes (24h average)",
            f"{_n(h.cubes_per_s_peak, 4)} cubes/s" + (" peak" if h.is_peak_window else " avg"),
            f"{_n(h.total_bytes_per_s_peak / MB)} MB/s" + (" peak" if h.is_peak_window else " avg"),
            f"{_n(h.bytes_per_day / GB)} GB",
        ],
        ["<strong>Total</strong>", f"<strong>{_n(w.peak_events_per_s)} events/s</strong>",
         f"<strong>{_n(w.peak_bytes_per_s / MB)} MB/s peak</strong>", f"<strong>{_n(a.day_bytes / GB)} GB</strong>"],
    ]
    accum_rows = [
        ["1 day", f"{_n(a.day_bytes / GB, 1)} GB"],
        ["1 month", f"{_n(a.month_bytes / 1e12)} TB"],
        ["1 year", f"{_n(a.year_bytes / 1e12, 1)} TB"],
        [f"Project, total produced ({p.sizing.project_months} months)", f"{_n(a.project_bytes / 1e12, 1)} TB"],
        [
            f"<strong>Retained ({_n(a.retention_months, 1)} months)</strong>"
            + (" &mdash; storage plateaus here" if a.is_capped else " = whole project, nothing rolls off"),
            f"<strong>{_n(a.retained_bytes / 1e12, 1)} TB</strong>",
        ],
    ]
    body = (
        "<ul>"
        f"<li>Sensors: {_n(i.sensors, 0)} ({_n(p.iot.pilot_sites)} sites x {p.iot.sensors_per_site}), "
        f"{_n(i.msgs_per_day, 0)} messages/day</li>"
        f"<li>HSI: {_n(h.cube_bytes / MB)} MB/cube, {_n(h.cubes_per_site_per_day)} cubes/site/day, "
        f"{_n(h.cubes_per_day)} cubes/day across {_n(p.hsi.sites_with_camera)} camera sites</li>"
        f"<li>HSI share of bytes: {_n(w.hsi_byte_share * 100, 1)} %</li>"
        "</ul>"
        + _table(["", "Write rate", "Throughput", "Daily volume"], rate_rows,
                 tid="workload--rates", keys=["iot", "hsi", "total"])
        + _h3("Accumulated raw volume (S3)", "workload", "accumulated")
        + _table(["Period", "Volume"], accum_rows, tid="workload--accumulated",
                 keys=["1-day", "1-month", "1-year", "project-total", "retained"])
    )
    return _section("Workload", body, sid="workload")


def _lakehouse_section(r: Result) -> str:
    lh, ml = r.workload.lakehouse, r.workload.ml
    rows = [
        ["Bronze (landed as-is)", f"{_n(lh.bronze_hsi_bytes_per_day / GB, 1)} GB",
         f"{_n(lh.bronze_iot_bytes_per_day / GB, 2)} GB", f"{_n(lh.bronze_bytes_per_day / GB, 1)} GB"],
        ["Silver (conformed; HSI = feature vectors only)", f"{_n(lh.silver_hsi_bytes_per_day / MB)} MB",
         f"{_n(lh.silver_iot_bytes_per_day / MB)} MB", f"{_n(lh.silver_bytes_per_day / MB)} MB"],
        ["Gold (curated aggregates)", f"{_n(lh.gold_hsi_bytes_per_day / MB)} MB",
         f"{_n(lh.gold_iot_bytes_per_day / MB)} MB", f"{_n(lh.gold_bytes_per_day / MB)} MB"],
    ]
    body = (
        _table(["Layer", "HSI", "IoT", "Total/day"], rows, tid="data-lake", keys=["bronze", "silver", "gold"])
        + "<ul>"
        + f"<li>Iceberg metadata: {_n(lh.iceberg_commits_per_day, 0)} commits/day across the "
          f"Bronze/Silver/Gold tables, {_n(lh.iceberg_objects_per_day, 0)} new objects/day, "
          f"{_n(lh.iceberg_metadata_bytes_per_day / MB)} MB/day of metadata bytes "
          "(watch the object count, not the bytes)</li>"
        + f"<li>ML model artifacts: {_n(ml.model_artifact_total_bytes / MB)} MB total "
          "(fixed, versioned store)</li>"
        + f"<li>ML predictions written back: {_n(ml.prediction_events_per_day, 0)} events/day, "
          f"{_n(ml.prediction_bytes_per_day / MB)} MB/day</li>"
        + "</ul>"
    )
    return _section("Data Lake pipeline & ML (Bronze/Silver/Gold)", body,
                     "Informational &mdash; S3/Glue aren't part of the VM fleet, so none of this counts toward VM fit.",
                     sid="data-lake")


def _storage_section(p: Params, r: Result) -> str:
    st = r.storage
    sp = p.storage
    labels = {"standard": "S3 Standard", "glacier_ir": "Glacier Instant Retrieval", "deep_archive": "Glacier Deep Archive"}
    rows = [[labels[t]] + [f"{_n(m[t] / GB, 1)} GB" for m in st.milestones] for t in ("standard", "glacier_ir", "deep_archive")]
    totals = [m["standard"] + m["glacier_ir"] + m["deep_archive"] for m in st.milestones]
    rows.append(["<strong>Total stored</strong>"] + [f"<strong>{_n(t / GB, 1)} GB</strong>" for t in totals])
    names = {"hsi_raw": "Raw HSI cubes", "iot_raw": "Raw IoT scalar data",
             "silver": "Silver (incl. overhead)", "gold": "Gold (incl. overhead)"}
    stream_rows = []
    for stream in ("hsi_raw", "iot_raw", "silver", "gold"):
        e = st.end_by_stream[stream]
        row_total = e["standard"] + e["glacier_ir"] + e["deep_archive"]
        stream_rows.append([names[stream]] + [f"{_n(e[t] / GB, 1)} GB" for t in ("standard", "glacier_ir", "deep_archive")]
                           + [f"<strong>{_n(row_total / GB, 1)} GB</strong>"])
    body = (
        _table(["Tier"] + [m["label"] for m in st.milestones], rows, tid="storage",
               keys=["standard", "glacier-ir", "deep-archive", "total"])
        + _h3("At end of project, by stream", "storage", "by-stream")
        + _table(["Stream", "S3 Standard", "Glacier IR", "Deep Archive", "Total"], stream_rows,
                 tid="storage--by-stream", keys=["hsi-raw", "iot-raw", "silver", "gold"])
    )
    return _section("S3 storage by tier (retention policy)", body,
                     f"Raw HSI: Standard for the first {_n(sp.hsi_standard_days)} days, Glacier IR until "
                     f"{_n(sp.hsi_glacier_ir_until_days)} days, then Deep Archive. "
                     f"Raw IoT: {_esc(sp.iot_raw_tier)} for its whole life. "
                     f"Silver and Gold: Standard, with {_n(sp.silver_gold_overhead * 100)}% versioning overhead.",
                     sid="storage")


def _components_section(r: Result) -> str:
    rows = []
    for c in r.components + [r.total]:
        bold = c is r.total
        cells = [_esc(c.name), _n(c.cpu_load, 3), _n(c.vcpu), f"{_n(c.ram_gb)} GB",
                 f"{_n(c.data_gb, 3)} GB", f"{_n(c.disk_gb)} GB"]
        if bold:
            cells = [f"<strong>{x}</strong>" for x in cells]
        rows.append(cells)
    notes = []
    for c in r.components:
        if c.name.startswith("Kafka"):
            notes.append(f"Kafka: {_n(c.notes['daily_volume_gb'], 3)} GB/day through Kafka, "
                         f"{_n(c.notes['data_per_broker_gb'])} GB data / {_n(c.notes['disk_per_broker_gb'])} GB disk per broker")
        elif c.name == "Flink":
            notes.append(f"Flink: state {_n(c.notes['state_mb'])} MB, "
                         f"checkpoints {_n(c.notes['checkpoints_s3_mb'])} MB on S3, "
                         f"TaskManager {_n(c.notes['taskmanager_gb'])} GB")
        elif c.name == "Prometheus":
            notes.append(f"Prometheus: {_n(c.notes['active_series'], 0)} active series, "
                         f"{_n(c.notes['samples_per_s'], 0)} samples/s")
        elif c.name.startswith("Redis"):
            notes.append(f"Redis: {_n(c.notes['keys'], 0)} keys, overwritten in place")
    body = (
        _table(["Component", "CPU (load)", "vCPU (allocate)", "RAM (allocate)", "Data stored", "Disk (w/ headroom)"],
               rows, tid="components",
               keys=[_slug(c.name.split("(")[0]) for c in r.components] + ["total"])
        + "<ul>" + "".join(f"<li>{n}</li>" for n in notes) + "</ul>"
    )
    return _section("Component sizing", body, sid="components")


def _bar(pct: float) -> str:
    width = min(pct, 100)
    cls = "over" if pct > 100 else ""
    return (
        f'<div class="bar-track"><div class="bar-fill {cls}" style="width:{width:.0f}%"></div></div>'
        f'<span class="bar-label">{_n(pct, 0)} %</span>'
    )


def _fit_section(p: Params, r: Result) -> str:
    f = r.fit
    badge_cls = "ok" if f.fits else "bad"
    badge_text = "FITS" if f.fits else "DOES NOT FIT"

    def row(label, req, cap, unit):
        pct = req / cap * 100 if cap else float("inf")
        return [label, f"{_n(req)} {unit}".strip(), f"{_n(cap)} {unit}".strip(),
                f"{_n(cap - req)} {unit}".strip(), _bar(pct)]

    rows = [
        row("vCPU", f.required_vcpu, f.capacity_vcpu, ""),
        row("RAM", f.required_ram_gb, f.capacity_ram_gb, "GB"),
        row("Disk", f.required_disk_gb, f.capacity_disk_gb, "GB"),
    ]
    vms = ", ".join(f"{_esc(v.name)} ({_n(v.vcpu)} vCPU / {_n(v.ram_gib)} GiB / {_n(v.disk_gb)} GB)" for v in p.vms)
    body = (
        f'<p>Fleet: {vms}</p>'
        + _table(["Resource", "Required (incl. OS)", "Capacity", "Remaining", "Used"], rows,
                 tid="vm-fit", keys=["vcpu", "ram", "disk"])
        + f'<p class="note">OS overhead: {_n(p.sizing.os_ram_gb_per_vm)} GB RAM + '
          f'{_n(p.sizing.os_disk_gb_per_vm)} GB disk per VM. Components not modelled (CKAN, PostgreSQL, '
          'Solr, the CKAN Redis instance, MQTT, API) are only counted if listed under [[extra_components]].</p>'
    )
    title_html = f'VM fit: <span class="badge {badge_cls}">{badge_text}</span>'
    return _section("VM fit", body, sid="vm-fit", title_html=title_html)


def _scaling_section(table) -> str:
    rows = []
    for f, sp, r in table:
        k = r.components[0]
        prom = next(c for c in r.components if c.name == "Prometheus")
        fits = "yes" if r.fit.fits else '<strong class="warn">no</strong>'
        rows.append([
            f"{_n(f)}x", f"{_n(r.workload.iot.sensors, 0)} ({_n(sp.iot.pilot_sites)})",
            _n(r.workload.iot.msg_per_s, 1), f"{_n(r.workload.hsi.bytes_per_day / GB, 1)} GB",
            f"{_n(k.notes['disk_per_broker_gb'], 1)} GB", _n(prom.notes["active_series"], 0),
            _n(r.total.cpu_load, 3), _n(r.total.vcpu), f"{_n(r.total.ram_gb, 1)} GB",
            f"{_n(r.total.disk_gb, 1)} GB", fits,
        ])
    body = _table(
        ["Scale", "Sensors (sites)", "Msg/s", "HSI/day", "Kafka disk/broker", "Prom series",
         "CPU load", "vCPU", "RAM", "Disk", "Fits VMs"],
        rows, tid="scaling",
    )
    return _section("Scaling (sites x factor)", body, sid="scaling")


def _formulas_section(p: Params, r: Result, cost=None) -> str:
    blocks = []
    by_section: dict[str, list] = {}
    keys: dict[str, list] = {}
    for f in formulas(p, r, cost):
        keys.setdefault(f.section, []).append(_slug(f.quantity.split("(")[0]))
        by_section.setdefault(f.section, []).append([
            _esc(f.quantity),
            f"<code>{_esc(f.formula)}</code>",
            _esc(f.worked),
            f"<strong>{_esc(f.result)}</strong>",
        ])
    for section, rows in by_section.items():
        sk = _slug(section)
        blocks.append(_h3(section, "formulas", sk)
                      + _table(["Quantity", "Formula", "This run", "Result"], rows,
                               tid=f"formulas--{sk}", keys=keys[section]))
    return _section("Formulas", "".join(blocks),
                     "Each derived number, its formula (as in model.py), and this run's values substituted in.",
                     sid="formulas")


def full_html(p: Params, r: Result, table=None, show_params: bool = True, show_formulas: bool = True,
              cost=None, nav: list[tuple[str, str]] | None = None, current: str | None = None) -> str:
    from .cost.render import cost_section_html
    sections = []
    if show_params:
        sections.append(_params_section(p))
    sections.append(_workload_section(p, r))
    sections.append(_lakehouse_section(r))
    sections.append(_storage_section(p, r))
    sections.append(_components_section(r))
    sections.append(_fit_section(p, r))
    if cost is not None:
        sections.append(cost_section_html(cost))
    if show_formulas:
        sections.append(_formulas_section(p, r, cost))
    if table:
        sections.append(_scaling_section(table))
    body = "\n".join(sections)
    subtitle = (f"Pilot: {_n(p.iot.pilot_sites)} sites &middot; {_n(p.iot.sensors_per_site)} sensors/site "
                f"&middot; {_n(p.hsi.sites_with_camera)} HSI camera sites")
    return page("TRACE sizing report", subtitle, body,
                "Generated by trace-sizing. Tables render best in a modern browser; "
                "this page has no external dependencies.", nav=nav, current=current)
