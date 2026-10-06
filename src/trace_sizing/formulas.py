"""The formula behind each derived number, with the values from this run.

Each entry gives the symbolic formula (as in model.py), the same formula with
this run's inputs substituted, and the result. Built from the same Params and
Result the calculator used, so the worked numbers can't drift from the report.
The symbolic text is the one place that must be kept in step with model.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from .fmt import _n
from .model import GB, MB, Result, DAY_S
from .params import Params


@dataclass
class Formula:
    section: str
    quantity: str
    formula: str    # symbolic
    worked: str     # with this run's values
    result: str


def _comp(r: Result, prefix: str):
    return next(c for c in r.components if c.name.startswith(prefix))


def formulas(p: Params, r: Result) -> list[Formula]:
    w = r.workload
    iot, hsi, acc = w.iot, w.hsi, w.accumulated
    lh, ml = w.lakehouse, w.ml
    out: list[Formula] = []

    def add(section, quantity, formula, worked, result):
        out.append(Formula(section, quantity, formula, worked, result))

    # ---- IoT
    i = p.iot
    add("IoT", "Sensors", "sites x sensors_per_site",
        f"{_n(i.pilot_sites)} x {_n(i.sensors_per_site)} = {_n(iot.sensors, 0)}", _n(iot.sensors, 0))
    add("IoT", "Messages per second", "sensors / reporting_interval_s",
        f"{_n(iot.sensors, 0)} / {_n(i.reporting_interval_s)} = {_n(iot.msg_per_s)}", f"{_n(iot.msg_per_s)} msg/s")
    add("IoT", "Messages per day", "msg/s x operating_hours_per_day x 3600",
        f"{_n(iot.msg_per_s)} x {_n(i.operating_hours_per_day)} x 3600 = {_n(iot.msgs_per_day, 0)}",
        f"{_n(iot.msgs_per_day, 0)}")
    add("IoT", "IoT bytes per day", "messages/day x message_bytes",
        f"{_n(iot.msgs_per_day, 0)} x {_n(i.message_bytes)} B = {_n(iot.bytes_per_day / GB, 2)} GB",
        f"{_n(iot.bytes_per_day / GB, 2)} GB")

    # ---- HSI
    h = p.hsi
    add("HSI", "Cube size", "cube_mb x 10^6  (or pixels x lines x bands x bytes_per_value)",
        f"{_n(h.cube_mb)} x 10^6 B = {_n(hsi.cube_bytes / MB)} MB" if h.cube_mb is not None else
        f"{_n(h.pixels)} x {_n(h.lines)} x {_n(h.bands)} x {_n(h.bytes_per_value)} B",
        f"{_n(hsi.cube_bytes / MB)} MB")
    add("HSI", "Cubes per site per day", "samples_per_day x scans_per_sample",
        f"{_n(h.samples_per_day)} x {_n(h.scans_per_sample)} = {_n(hsi.cubes_per_site_per_day)}",
        _n(hsi.cubes_per_site_per_day))
    add("HSI", "Cubes per day (all sites)", "cubes/site/day x sites_with_camera",
        f"{_n(hsi.cubes_per_site_per_day)} x {_n(h.sites_with_camera)} = {_n(hsi.cubes_per_day)}",
        _n(hsi.cubes_per_day))
    add("HSI", "HSI bytes per day", "cubes/day x cube bytes",
        f"{_n(hsi.cubes_per_day)} x {_n(hsi.cube_bytes / MB)} MB = {_n(hsi.bytes_per_day / GB)} GB",
        f"{_n(hsi.bytes_per_day / GB)} GB")
    window_h = h.upload_window_hours_per_day
    window_s = window_h * 3600 if hsi.is_peak_window else DAY_S
    label = f"{_n(window_h)} h x 3600" if hsi.is_peak_window else "86,400 (24 h average)"
    add("HSI", "Peak cube rate", "cubes/day / (upload_window_hours x 3600)  [24 h average if window unset]",
        f"{_n(hsi.cubes_per_day)} / ({label}) = {_n(hsi.cubes_per_s_peak, 4)}",
        f"{_n(hsi.cubes_per_s_peak, 4)} cubes/s")

    # ---- Accumulated raw volume
    add("Accumulated", "Storage per year",
        "HSI/day x HSI operating_days + IoT/day x IoT operating_days",
        f"{_n(hsi.bytes_per_day / GB)} GB x {_n(h.operating_days_per_year)} + "
        f"{_n(iot.bytes_per_day / GB, 2)} GB x {_n(i.operating_days_per_year)} = {_n(acc.year_bytes / 1e12, 1)} TB",
        f"{_n(acc.year_bytes / 1e12, 1)} TB")
    add("Accumulated", "Total produced over project", "year_bytes x project_months / 12",
        f"{_n(acc.year_bytes / 1e12, 1)} TB x {_n(p.sizing.project_months)} / 12 = {_n(acc.project_bytes / 1e12, 1)} TB",
        f"{_n(acc.project_bytes / 1e12, 1)} TB")
    add("Accumulated", "Retained storage", "year_bytes / 12 x min(retention_months, project_months)",
        f"{_n(acc.year_bytes / 1e12, 1)} TB / 12 x {_n(acc.retention_months, 1)} = {_n(acc.retained_bytes / 1e12, 1)} TB",
        f"{_n(acc.retained_bytes / 1e12, 1)} TB")

    # ---- Data Lake pipeline (Bronze / Silver / Gold) and Iceberg
    lk = p.lakehouse
    add("Data Lake", "Bronze IoT", "IoT bytes/day x bronze_iot_size_ratio",
        f"{_n(iot.bytes_per_day / GB, 2)} GB x {_n(lk.bronze_iot_size_ratio)} = {_n(lh.bronze_iot_bytes_per_day / GB, 2)} GB",
        f"{_n(lh.bronze_iot_bytes_per_day / GB, 2)} GB")
    add("Data Lake", "Silver HSI (feature vectors)", "cubes/day x silver_hsi_kb_per_cube x 10^3",
        f"{_n(hsi.cubes_per_day)} x {_n(lk.silver_hsi_kb_per_cube)} kB = {_n(lh.silver_hsi_bytes_per_day / MB)} MB",
        f"{_n(lh.silver_hsi_bytes_per_day / MB)} MB")
    add("Data Lake", "Silver IoT", "IoT bytes/day x silver_iot_size_ratio",
        f"{_n(iot.bytes_per_day / GB, 2)} GB x {_n(lk.silver_iot_size_ratio)} = {_n(lh.silver_iot_bytes_per_day / MB)} MB",
        f"{_n(lh.silver_iot_bytes_per_day / MB)} MB")
    add("Data Lake", "Gold IoT", "sensors x gold_iot_rows_per_sensor_per_day x gold_iot_bytes_per_row",
        f"{_n(iot.sensors, 0)} x {_n(lk.gold_iot_rows_per_sensor_per_day)} x {_n(lk.gold_iot_bytes_per_row)} B = "
        f"{_n(lh.gold_iot_bytes_per_day / MB, 3)} MB",
        f"{_n(lh.gold_iot_bytes_per_day / MB, 3)} MB")
    add("Data Lake", "Gold HSI", "cubes/day x gold_hsi_bytes_per_record",
        f"{_n(hsi.cubes_per_day)} x {_n(lk.gold_hsi_bytes_per_record)} B = {_n(lh.gold_hsi_bytes_per_day / MB, 3)} MB",
        f"{_n(lh.gold_hsi_bytes_per_day / MB, 3)} MB")
    add("Data Lake", "Iceberg commits per day", "(1440 / iceberg_commit_interval_min) x iceberg_tables",
        f"(1440 / {_n(lk.iceberg_commit_interval_min)}) x {_n(lk.iceberg_tables)} = {_n(lh.iceberg_commits_per_day, 0)}",
        f"{_n(lh.iceberg_commits_per_day, 0)}")
    add("Data Lake", "Iceberg objects per day", "commits/day x iceberg_objects_per_commit",
        f"{_n(lh.iceberg_commits_per_day, 0)} x {_n(lk.iceberg_objects_per_commit)} = {_n(lh.iceberg_objects_per_day, 0)}",
        f"{_n(lh.iceberg_objects_per_day, 0)}")

    # ---- ML pipeline
    m = p.ml
    add("ML", "Model artifact store", "model_variants x model_mb_per_variant x model_versions_retained",
        f"{_n(m.model_variants)} x {_n(m.model_mb_per_variant)} MB x {_n(m.model_versions_retained)} = "
        f"{_n(ml.model_artifact_total_bytes / MB)} MB",
        f"{_n(ml.model_artifact_total_bytes / MB)} MB")
    add("ML", "Predictions per day",
        "sensors x predictions_per_sensor_per_day + cubes/day x predictions_per_hsi_sample",
        f"{_n(iot.sensors, 0)} x {_n(m.predictions_per_sensor_per_day)} + {_n(hsi.cubes_per_day)} x "
        f"{_n(m.predictions_per_hsi_sample)} = {_n(ml.prediction_events_per_day, 0)}",
        f"{_n(ml.prediction_events_per_day, 0)}")

    # ---- Components
    k = _comp(r, "Kafka")
    kc = p.kafka
    daily = k.notes["daily_volume_gb"]
    add("Kafka", "Daily volume through Kafka",
        "IoT bytes/day + (cubes/day x pointer_event_bytes if claim_check, else HSI bytes/day)",
        f"{_n(iot.bytes_per_day / GB, 2)} GB + {_n(hsi.pointer_bytes_per_day / MB, 3)} MB = {_n(daily, 3)} GB"
        if p.hsi.claim_check else f"{_n(daily, 3)} GB",
        f"{_n(daily, 3)} GB")
    add("Kafka", "Stored data", "daily volume x retention_days x replication_factor",
        f"{_n(daily, 3)} GB x {_n(kc.retention_days)} x {_n(kc.replication_factor)} = {_n(k.data_gb)} GB",
        f"{_n(k.data_gb)} GB")
    add("Kafka", "Disk to allocate", "stored data x (1 + disk_headroom)",
        f"{_n(k.data_gb)} GB x (1 + {_n(p.sizing.disk_headroom)}) = {_n(k.disk_gb)} GB",
        f"{_n(k.disk_gb)} GB")
    add("Kafka", "CPU load", "peak events/s x replication_factor x cpu_us_per_message / 10^6",
        f"{_n(w.peak_events_per_s)} x {_n(kc.replication_factor)} x {_n(kc.cpu_us_per_message)} / 10^6 = {_n(k.cpu_load, 4)}",
        _n(k.cpu_load, 4))

    f_ = _comp(r, "Flink")
    fc = p.flink
    readings = fc.window_s / i.reporting_interval_s
    state_bytes = f_.data_gb * GB
    add("Flink", "State size", "sensors x (window_s / reporting_interval_s) x state_bytes_per_reading",
        f"{_n(iot.sensors, 0)} x ({_n(fc.window_s)} / {_n(i.reporting_interval_s)}) x {_n(fc.state_bytes_per_reading)} B = "
        f"{_n(state_bytes / MB)} MB",
        f"{_n(state_bytes / MB)} MB")
    add("Flink", "TaskManager memory", "max(taskmanager_gb, taskmanager_framework_gb + state_GB x state_memory_factor)",
        f"max({_n(fc.taskmanager_gb)}, {_n(fc.taskmanager_framework_gb)} + {_n(state_bytes / GB, 4)} x "
        f"{_n(fc.state_memory_factor)}) = {_n(f_.notes['taskmanager_gb'])} GB",
        f"{_n(f_.notes['taskmanager_gb'])} GB")
    add("Flink", "RAM to allocate", "jobmanager_gb + TaskManager",
        f"{_n(fc.jobmanager_gb)} + {_n(f_.notes['taskmanager_gb'])} = {_n(f_.ram_gb)} GB", f"{_n(f_.ram_gb)} GB")

    pr_c = _comp(r, "Prometheus")
    pm = p.prometheus
    series = pr_c.notes["active_series"]
    add("Prometheus", "Active series",
        "sensors x metrics_per_sensor + HSI sites x hsi_metrics_per_site + infrastructure_series",
        f"{_n(iot.sensors, 0)} x {_n(pm.metrics_per_sensor)} + {_n(h.sites_with_camera)} x {_n(pm.hsi_metrics_per_site)} + "
        f"{_n(pm.infrastructure_series, 0)} = {_n(series, 0)}",
        _n(series, 0))
    add("Prometheus", "Samples per second", "active series / scrape_interval_s",
        f"{_n(series, 0)} / {_n(pm.scrape_interval_s)} = {_n(pr_c.notes['samples_per_s'], 0)}",
        f"{_n(pr_c.notes['samples_per_s'], 0)}")
    add("Prometheus", "Disk to allocate",
        "samples/s x 86,400 x bytes_per_sample x retention_days x (1 + disk_headroom)",
        f"{_n(pr_c.notes['samples_per_s'], 0)} x 86,400 x {_n(pm.bytes_per_sample)} x {_n(pm.retention_days)} x "
        f"(1 + {_n(p.sizing.disk_headroom)}) = {_n(pr_c.disk_gb, 2)} GB",
        f"{_n(pr_c.disk_gb, 2)} GB")
    add("Prometheus", "RAM to allocate",
        "max(min_ram_gb, (series x ram_kb_per_series + process_overhead_mb) x ram_headroom_factor)",
        f"max({_n(pm.min_ram_gb)}, ({_n(series, 0)} x {_n(pm.ram_kb_per_series)} kB + {_n(pm.process_overhead_mb)} MB) x "
        f"{_n(pm.ram_headroom_factor)}) = {_n(pr_c.ram_gb)} GB",
        f"{_n(pr_c.ram_gb)} GB")

    rd = _comp(r, "Redis")
    rc = p.redis
    keys = rd.notes["keys"]
    live_gb = keys * rc.bytes_per_key / GB
    add("Redis", "Keys", "sensors + HSI sites", f"{_n(iot.sensors, 0)} + {_n(h.sites_with_camera)} = {_n(keys, 0)}",
        _n(keys, 0))
    add("Redis", "Live data", "keys x bytes_per_key",
        f"{_n(keys, 0)} x {_n(rc.bytes_per_key)} B = {_n(live_gb * 1e3, 3)} kB", f"{_n(live_gb * 1e3, 3)} kB")
    add("Redis", "RAM to allocate", "max(ram_overhead_mb, (ram_overhead_mb + live) x ram_headroom_factor)",
        f"max({_n(rc.ram_overhead_mb)} MB, ({_n(rc.ram_overhead_mb)} MB + {_n(live_gb * 1e3, 3)} kB) x "
        f"{_n(rc.ram_headroom_factor)}) = {_n(rd.ram_gb)} GB",
        f"{_n(rd.ram_gb)} GB")

    # ---- S3 storage tiers (retention policy)
    sp = p.storage
    rates = r.storage.rates_per_day
    t_days = p.sizing.project_months * 365 / 12
    end = r.storage.end_by_stream
    hsi_days = p.hsi.operating_days_per_year
    add("Storage", "Project length in days", "project_months x 365 / 12",
        f"{_n(p.sizing.project_months)} x 365 / 12 = {_n(t_days, 0)}", _n(t_days, 0))
    add("Storage", "HSI raw, calendar-day average", "HSI bytes/day x HSI operating_days / 365",
        f"{_n(w.hsi.bytes_per_day / GB)} GB x {_n(hsi_days)} / 365 = {_n(rates['hsi_raw'] / GB)} GB",
        f"{_n(rates['hsi_raw'] / GB)} GB/day")
    add("Storage", "HSI raw in S3 Standard", "HSI/day x min(hsi_standard_days, project days)",
        f"{_n(rates['hsi_raw'] / GB)} GB x {_n(sp.hsi_standard_days)} = {_n(end['hsi_raw']['standard'] / GB)} GB",
        f"{_n(end['hsi_raw']['standard'] / GB)} GB")
    add("Storage", "HSI raw in Glacier Instant Retrieval",
        "HSI/day x (min(hsi_glacier_ir_until_days, project days) - hsi_standard_days)",
        f"{_n(rates['hsi_raw'] / GB)} GB x ({_n(sp.hsi_glacier_ir_until_days)} - {_n(sp.hsi_standard_days)}) = "
        f"{_n(end['hsi_raw']['glacier_ir'] / GB)} GB",
        f"{_n(end['hsi_raw']['glacier_ir'] / GB)} GB")
    add("Storage", "HSI raw in Glacier Deep Archive", "HSI/day x (project days - hsi_glacier_ir_until_days)",
        f"{_n(rates['hsi_raw'] / GB)} GB x ({_n(t_days, 0)} - {_n(sp.hsi_glacier_ir_until_days)}) = "
        f"{_n(end['hsi_raw']['deep_archive'] / GB)} GB",
        f"{_n(end['hsi_raw']['deep_archive'] / GB)} GB")
    tier = sp.iot_raw_tier
    add("Storage", f"Raw IoT scalar data (all in {tier})", "IoT raw bytes/day x project days",
        f"{_n(rates['iot_raw'] / GB, 2)} GB x {_n(t_days, 0)} = {_n(end['iot_raw'][tier] / GB)} GB",
        f"{_n(end['iot_raw'][tier] / GB)} GB")
    add("Storage", "Silver in S3 Standard (with overhead)",
        "(Silver HSI/day x HSI days/365 + Silver IoT/day x IoT days/365) x (1 + silver_gold_overhead) x project days",
        f"({_n(w.lakehouse.silver_hsi_bytes_per_day / MB, 2)} MB x {_n(hsi_days)}/365 + "
        f"{_n(w.lakehouse.silver_iot_bytes_per_day / MB)} MB x {_n(p.iot.operating_days_per_year)}/365) x "
        f"(1 + {_n(sp.silver_gold_overhead)}) x {_n(t_days, 0)} = {_n(end['silver']['standard'] / GB)} GB",
        f"{_n(end['silver']['standard'] / GB)} GB")

    # ---- VM fit
    f = r.fit
    n = len(p.vms)
    s = p.sizing
    add("VM fit", "Required vCPU", "sum of component vCPU",
        " + ".join(_n(c.vcpu) for c in r.components) + f" = {_n(f.required_vcpu)}",
        f"{_n(f.required_vcpu)} of {_n(f.capacity_vcpu)}")
    add("VM fit", "Required RAM", f"sum of component RAM + {n} VMs x os_ram_gb_per_vm",
        f"{_n(f.required_ram_gb - n * s.os_ram_gb_per_vm)} + {n} x {_n(s.os_ram_gb_per_vm)} = {_n(f.required_ram_gb)} GB",
        f"{_n(f.required_ram_gb)} of {_n(f.capacity_ram_gb)} GB")
    add("VM fit", "Required disk", f"sum of component disk + {n} VMs x os_disk_gb_per_vm",
        f"{_n(f.required_disk_gb - n * s.os_disk_gb_per_vm)} + {n} x {_n(s.os_disk_gb_per_vm)} = {_n(f.required_disk_gb)} GB",
        f"{_n(f.required_disk_gb)} of {_n(f.capacity_disk_gb)} GB")
    add("VM fit", "Fits", "required <= capacity for vCPU, RAM and disk",
        "all three hold" if f.fits else "at least one exceeded",
        "FITS" if f.fits else "DOES NOT FIT")
    return out
