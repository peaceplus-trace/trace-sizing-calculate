"""Sizing calculations: workload volumes -> per-component load and allocation -> VM fit."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .params import Params

KB, MB, GB, TB = 1e3, 1e6, 1e9, 1e12
GIB = 2**30
DAY_S = 86_400


@dataclass
class IoTLoad:
    sensors: float
    msg_per_s: float
    bytes_per_s: float
    msgs_per_day: float
    bytes_per_day: float


@dataclass
class HSILoad:
    cube_bytes: float
    cubes_per_site_per_day: float
    cubes_per_day: float
    cubes_per_s_24h: float
    bytes_per_day_per_site: float
    bytes_per_day: float
    pointer_bytes_per_day: float
    # Peak figures: during upload_window_hours_per_day if set, else the same
    # as the 24h average (is_peak_window tells you which).
    cubes_per_s_peak: float
    site_bytes_per_s_peak: float
    total_bytes_per_s_peak: float
    is_peak_window: bool


@dataclass
class Accumulated:
    day_bytes: float
    month_bytes: float
    year_bytes: float
    project_bytes: float          # total ever produced over the whole project
    retention_months: float       # effective retention window (capped at project_months)
    retained_bytes: float         # steady-state storage to provision for, at retention_months
    is_capped: bool                # True if retention_months < project_months (data rolls off)


@dataclass
class LakehouseVolume:
    """Bronze/Silver/Gold daily volume (Data Lake pipeline branch). Informational
    only - like `Accumulated`, this isn't counted in VM `Fit` (S3/Glue, not the
    VM fleet)."""
    bronze_hsi_bytes_per_day: float    # == HSILoad.bytes_per_day (claim-check, landed as-is)
    bronze_iot_bytes_per_day: float
    bronze_bytes_per_day: float
    silver_hsi_bytes_per_day: float    # feature vectors/indices only, not a second full cube
    silver_iot_bytes_per_day: float
    silver_bytes_per_day: float
    gold_iot_bytes_per_day: float
    gold_hsi_bytes_per_day: float
    gold_bytes_per_day: float
    iceberg_commits_per_day: float
    iceberg_objects_per_day: float     # drives S3 request cost / Glue Catalog limits, not bytes
    iceberg_metadata_bytes_per_day: float


@dataclass
class MLVolume:
    """AI/ML Pipeline training + predictions (Real-time Inference branch)."""
    model_artifact_total_bytes: float  # fixed, versioned store - not a daily rate
    prediction_events_per_day: float
    prediction_bytes_per_day: float


@dataclass
class Workload:
    iot: IoTLoad
    hsi: HSILoad
    accumulated: Accumulated
    lakehouse: LakehouseVolume
    ml: MLVolume
    peak_events_per_s: float
    peak_bytes_per_s: float
    hsi_byte_share: float


@dataclass
class Component:
    name: str
    cpu_load: float       # vCPU actually consumed (estimate)
    vcpu: float           # vCPU to allocate
    ram_load_gb: float    # memory actually used (estimate)
    ram_gb: float         # memory to allocate
    data_gb: float        # data held on local disk
    disk_gb: float        # disk to allocate (data + headroom, or a floor)
    notes: dict = field(default_factory=dict)


@dataclass
class Fit:
    vms: int
    capacity_vcpu: float
    capacity_ram_gb: float
    capacity_disk_gb: float
    required_vcpu: float
    required_ram_gb: float
    required_disk_gb: float

    @property
    def fits(self) -> bool:
        return (
            self.required_vcpu <= self.capacity_vcpu
            and self.required_ram_gb <= self.capacity_ram_gb
            and self.required_disk_gb <= self.capacity_disk_gb
        )


@dataclass
class Result:
    workload: Workload
    components: list[Component]
    total: Component
    fit: Fit

    def to_dict(self) -> dict:
        d = asdict(self)
        d["fit"]["fits"] = self.fit.fits
        return d


# --------------------------------------------------------------------------- workload

def iot_load(p: Params) -> IoTLoad:
    i = p.iot
    sensors = i.pilot_sites * i.sensors_per_site
    msg_per_s = sensors / i.reporting_interval_s
    msgs_per_day = msg_per_s * i.operating_hours_per_day * 3600
    return IoTLoad(
        sensors=sensors,
        msg_per_s=msg_per_s,
        bytes_per_s=msg_per_s * i.message_bytes,
        msgs_per_day=msgs_per_day,
        bytes_per_day=msgs_per_day * i.message_bytes,
    )


def cube_bytes(p: Params) -> float:
    h = p.hsi
    dims = (h.pixels, h.lines, h.bands, h.bytes_per_value)
    if all(d is not None for d in dims):
        return float(h.pixels * h.lines * h.bands * h.bytes_per_value)
    if h.cube_mb is None:
        raise ValueError("[hsi] set cube_mb, or all of pixels/lines/bands/bytes_per_value")
    return h.cube_mb * MB


def hsi_load(p: Params) -> HSILoad:
    h = p.hsi
    cube = cube_bytes(p)
    per_site = h.samples_per_day * h.scans_per_sample      # #9 x #10
    per_day = per_site * h.sites_with_camera                # x #7
    is_peak_window = h.upload_window_hours_per_day is not None
    window_s = h.upload_window_hours_per_day * 3600 if is_peak_window else DAY_S
    return HSILoad(
        cube_bytes=cube,
        cubes_per_site_per_day=per_site,
        cubes_per_day=per_day,
        cubes_per_s_24h=per_day / DAY_S,
        bytes_per_day_per_site=per_site * cube,
        bytes_per_day=per_day * cube,
        pointer_bytes_per_day=per_day * h.pointer_event_bytes,
        cubes_per_s_peak=per_day / window_s,
        site_bytes_per_s_peak=per_site * cube / window_s,
        total_bytes_per_s_peak=per_day * cube / window_s,
        is_peak_window=is_peak_window,
    )


def lakehouse_volume(p: Params, iot: IoTLoad, hsi: HSILoad) -> LakehouseVolume:
    lh = p.lakehouse
    bronze_hsi = hsi.bytes_per_day                              # claim-check: landed as-is
    bronze_iot = iot.bytes_per_day * lh.bronze_iot_size_ratio
    silver_hsi = hsi.cubes_per_day * lh.silver_hsi_kb_per_cube * KB
    silver_iot = iot.bytes_per_day * lh.silver_iot_size_ratio
    gold_iot = iot.sensors * lh.gold_iot_rows_per_sensor_per_day * lh.gold_iot_bytes_per_row
    gold_hsi = hsi.cubes_per_day * lh.gold_hsi_bytes_per_record
    commits_per_day = DAY_S / 60 / lh.iceberg_commit_interval_min * lh.iceberg_tables
    return LakehouseVolume(
        bronze_hsi_bytes_per_day=bronze_hsi,
        bronze_iot_bytes_per_day=bronze_iot,
        bronze_bytes_per_day=bronze_hsi + bronze_iot,
        silver_hsi_bytes_per_day=silver_hsi,
        silver_iot_bytes_per_day=silver_iot,
        silver_bytes_per_day=silver_hsi + silver_iot,
        gold_iot_bytes_per_day=gold_iot,
        gold_hsi_bytes_per_day=gold_hsi,
        gold_bytes_per_day=gold_iot + gold_hsi,
        iceberg_commits_per_day=commits_per_day,
        iceberg_objects_per_day=commits_per_day * lh.iceberg_objects_per_commit,
        iceberg_metadata_bytes_per_day=commits_per_day * lh.iceberg_metadata_kb_per_commit * KB,
    )


def ml_volume(p: Params, iot: IoTLoad, hsi: HSILoad) -> MLVolume:
    m = p.ml
    events = iot.sensors * m.predictions_per_sensor_per_day + hsi.cubes_per_day * m.predictions_per_hsi_sample
    return MLVolume(
        model_artifact_total_bytes=m.model_variants * m.model_mb_per_variant * m.model_versions_retained * MB,
        prediction_events_per_day=events,
        prediction_bytes_per_day=events * m.prediction_bytes,
    )


def workload(p: Params) -> Workload:
    iot, hsi = iot_load(p), hsi_load(p)
    year = (
        hsi.bytes_per_day * p.hsi.operating_days_per_year
        + iot.bytes_per_day * p.iot.operating_days_per_year
    )
    day = hsi.bytes_per_day + iot.bytes_per_day
    s = p.sizing
    retention_months = s.project_months if s.retention_months is None else min(s.retention_months, s.project_months)
    return Workload(
        iot=iot,
        hsi=hsi,
        accumulated=Accumulated(
            day_bytes=day,
            month_bytes=year / 12,
            year_bytes=year,
            project_bytes=year * s.project_months / 12,
            retention_months=retention_months,
            retained_bytes=year / 12 * retention_months,
            is_capped=retention_months < s.project_months,
        ),
        lakehouse=lakehouse_volume(p, iot, hsi),
        ml=ml_volume(p, iot, hsi),
        peak_events_per_s=iot.msg_per_s + hsi.cubes_per_s_peak,
        peak_bytes_per_s=iot.bytes_per_s + hsi.total_bytes_per_s_peak,
        hsi_byte_share=hsi.bytes_per_day / day if day else 0.0,
    )


# --------------------------------------------------------------------------- components

def kafka(p: Params, w: Workload) -> Component:
    k = p.kafka
    daily = w.iot.bytes_per_day + (
        w.hsi.pointer_bytes_per_day if p.hsi.claim_check else w.hsi.bytes_per_day
    )
    stored = daily * k.retention_days * k.replication_factor
    disk = stored * (1 + p.sizing.disk_headroom)
    msg_per_s = w.peak_events_per_s
    return Component(
        name=f"Kafka ({k.brokers} brokers, RF={k.replication_factor})",
        cpu_load=msg_per_s * k.replication_factor * k.cpu_us_per_message / 1e6,
        vcpu=k.vcpu_per_broker * k.brokers,
        ram_load_gb=k.ram_gb_per_broker * k.brokers,
        ram_gb=k.ram_gb_per_broker * k.brokers,
        data_gb=stored / GB,
        disk_gb=disk / GB,
        notes={
            "daily_volume_gb": daily / GB,
            "data_per_broker_gb": stored / k.brokers / GB,
            "disk_per_broker_gb": disk / k.brokers / GB,
        },
    )


def flink(p: Params, w: Workload) -> Component:
    f = p.flink
    readings_per_window = f.window_s / p.iot.reporting_interval_s
    state = w.iot.sensors * readings_per_window * f.state_bytes_per_reading
    tm = max(f.taskmanager_gb, f.taskmanager_framework_gb + state / GB * f.state_memory_factor)
    return Component(
        name="Flink",
        cpu_load=w.peak_events_per_s * f.cpu_us_per_event / 1e6,
        vcpu=f.vcpu,
        ram_load_gb=f.jobmanager_gb + tm,
        ram_gb=f.jobmanager_gb + tm,
        data_gb=state / GB,
        disk_gb=max(f.min_disk_gb, state * (1 + p.sizing.disk_headroom) / GB),
        notes={
            "state_mb": state / MB,
            "checkpoints_s3_mb": state * f.checkpoints_retained / MB,
            "taskmanager_gb": tm,
            "taskmanager_resized": tm > f.taskmanager_gb,
        },
    )


def prometheus(p: Params, w: Workload) -> Component:
    pr = p.prometheus
    series = (
        (w.iot.sensors * pr.metrics_per_sensor if pr.store_sensor_values else 0)
        + p.hsi.sites_with_camera * pr.hsi_metrics_per_site
        + pr.infrastructure_series
    )
    samples_per_s = series / pr.scrape_interval_s
    data = samples_per_s * DAY_S * pr.bytes_per_sample * pr.retention_days
    ram_load = (series * pr.ram_kb_per_series * KB + pr.process_overhead_mb * MB) / GB
    return Component(
        name="Prometheus",
        cpu_load=samples_per_s * pr.cpu_us_per_sample / 1e6,
        vcpu=pr.vcpu,
        ram_load_gb=ram_load,
        ram_gb=max(pr.min_ram_gb, ram_load * pr.ram_headroom_factor),
        data_gb=data / GB,
        disk_gb=data * (1 + p.sizing.disk_headroom) / GB,
        notes={"active_series": series, "samples_per_s": samples_per_s},
    )


def grafana(p: Params) -> Component:
    g = p.grafana
    return Component("Grafana", 0.0, g.vcpu, g.ram_gb, g.ram_gb, g.disk_gb, g.disk_gb)


def alerting(p: Params) -> Component:
    a = p.alerting
    return Component("Alertmanager + exporters", 0.0, a.vcpu, a.ram_gb, a.ram_gb, 0.0, a.disk_gb)


def redis(p: Params, w: Workload) -> Component:
    r = p.redis
    keys = w.iot.sensors + p.hsi.sites_with_camera
    live = keys * r.bytes_per_key
    ram_load = r.ram_overhead_mb * MB / GB + live / GB
    return Component(
        name="Redis (hot store)",
        cpu_load=0.0,
        vcpu=r.vcpu,
        ram_load_gb=ram_load,
        ram_gb=max(r.ram_overhead_mb * MB / GB, ram_load * r.ram_headroom_factor),
        data_gb=live / GB,
        disk_gb=max(r.min_disk_gb, live / GB),      # RDB snapshot; keys overwritten in place, not accumulated
        notes={"keys": keys},
    )


def _sum(name: str, comps: list[Component]) -> Component:
    return Component(
        name=name,
        cpu_load=sum(c.cpu_load for c in comps),
        vcpu=sum(c.vcpu for c in comps),
        ram_load_gb=sum(c.ram_load_gb for c in comps),
        ram_gb=sum(c.ram_gb for c in comps),
        data_gb=sum(c.data_gb for c in comps),
        disk_gb=sum(c.disk_gb for c in comps),
    )


def calculate(p: Params) -> Result:
    w = workload(p)
    comps = [kafka(p, w), flink(p, w), prometheus(p, w), grafana(p), alerting(p), redis(p, w)]
    comps += [
        Component(e.name, e.vcpu, e.vcpu, e.ram_gb, e.ram_gb, e.disk_gb, e.disk_gb, {"extra": True})
        for e in p.extra_components
    ]
    total = _sum("Total (excluding OS)", comps)
    n = len(p.vms)
    fit = Fit(
        vms=n,
        capacity_vcpu=sum(v.vcpu for v in p.vms),
        capacity_ram_gb=sum(v.ram_gib for v in p.vms) * GIB / GB,
        capacity_disk_gb=sum(v.disk_gb for v in p.vms),
        required_vcpu=total.vcpu,
        required_ram_gb=total.ram_gb + n * p.sizing.os_ram_gb_per_vm,
        required_disk_gb=total.disk_gb + n * p.sizing.os_disk_gb_per_vm,
    )
    return Result(workload=w, components=comps, total=total, fit=fit)


def scaling_table(p: Params, factors: list[float] | None = None) -> list[tuple[float, Params, Result]]:
    factors = factors if factors is not None else p.sizing.scale_factors
    out = []
    for f in factors:
        sp = p.scaled(f)
        out.append((f, sp, calculate(sp)))
    return out
