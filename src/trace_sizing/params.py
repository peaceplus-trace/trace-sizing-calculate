"""Input parameters for the TRACE sizing model.

`IoT` and `HSI` implement the canonical "System Parameters" table (the
11-parameter IoT/HSI list used across the TRACE chats): IoT fields #1-6,
HSI fields #7-11. The number after each field is that parameter's # in the
table. `Kafka`/`Flink`/`Prometheus`/... are downstream component settings
derived from the TRACE WP3 cost-estimate doc, not part of the 11-parameter
list, and keep their own (unrelated) assumption numbers from that doc.

Defaults reproduce the TRACE pilot plan: 10 sites, 50 sensors/site, 30 s IoT
interval, 10 HSI sites, 200 MB cubes, 48 scans/site/day, Kafka RF=3, 7 d
retention.

All units are decimal (1 KB = 1,000 B, 1 GB = 1e9 B) unless noted.
"""

from __future__ import annotations

import dataclasses
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class IoT:
    pilot_sites: int = 10                  # 1  Pilot site count
    sensors_per_site: int = 50             # 2  Sensor count per site
    reporting_interval_s: float = 30.0     # 3  Reporting interval (s)
    message_bytes: float = 500.0           # 4  Message size (bytes/reading)
    operating_hours_per_day: float = 24.0  # 5  Operating hours (24 if 24/7)
    operating_days_per_year: int = 365     # 6  Operating days per year


@dataclass
class HSI:
    sites_with_camera: int = 10            # 7  Number of sites with HSI camera
    # Image size (# 8): either give cube_mb directly, or the four dimensions
    # below (cube_mb is then derived as pixels x lines x bands x bytes_per_value).
    cube_mb: float | None = 200.0          # 8  Image size (cube size, MB)
    pixels: int | None = None
    lines: int | None = None
    bands: int | None = None
    bytes_per_value: int | None = None
    scans_per_sample: int = 1              # 9  Scans per sample (incl. repeats/reference scans)
    samples_per_day: int = 48              # 10 Number of samples per day (per HSI site)
    operating_days_per_year: int = 260     # 11 HSI operating days per year (e.g. 260 weekdays)
    # Not one of the 11 system parameters: only used to turn the daily cube
    # count above into a peak upload rate (MB/s) for network/bandwidth sizing.
    # Leave as None to report an average rate spread over 24h instead.
    upload_window_hours_per_day: float | None = 8.0
    pointer_event_bytes: float = 500.0     # claim-check pointer event size
    claim_check: bool = True               # cubes -> S3, only pointer events -> Kafka


@dataclass
class Kafka:
    retention_days: float = 7.0            # 15
    replication_factor: int = 3            # 16
    brokers: int = 3                       # 17
    ram_gb_per_broker: float = 2.0         # 20
    vcpu_per_broker: float = 1.0           # 21
    cpu_us_per_message: float = 20.0       # load estimate, per replica write


@dataclass
class Flink:
    window_s: float = 3600.0               # 23
    state_bytes_per_reading: float = 100.0 # 24
    checkpoints_retained: int = 3          # 26
    cpu_us_per_event: float = 50.0         # 27
    jobmanager_gb: float = 1.6             # 28
    taskmanager_gb: float = 1.7            # 28 (Flink default)
    # TaskManager is grown to framework_gb + state x state_memory_factor once
    # that exceeds taskmanager_gb (heap state backend needs ~4x the raw state).
    taskmanager_framework_gb: float = 1.2
    state_memory_factor: float = 4.0
    vcpu: float = 1.0                      # 29
    min_disk_gb: float = 1.0


@dataclass
class Prometheus:
    scrape_interval_s: float = 15.0        # 30
    retention_days: float = 15.0           # 31
    metrics_per_sensor: int = 8            # 32
    hsi_metrics_per_site: int = 4          # 33
    infrastructure_series: int = 9600      # 34
    store_sensor_values: bool = True       # 35
    bytes_per_sample: float = 1.5          # 36
    ram_kb_per_series: float = 4.0         # 37
    process_overhead_mb: float = 150.0     # 38
    # Allocation: max(min_ram_gb, load x ram_headroom_factor)
    min_ram_gb: float = 1.0
    ram_headroom_factor: float = 2.0
    vcpu: float = 0.5
    cpu_us_per_sample: float = 5.0


@dataclass
class Grafana:
    ram_gb: float = 0.25                   # 43
    vcpu: float = 0.25                     # 43
    disk_gb: float = 0.1                   # 43


@dataclass
class AlertingExporters:
    ram_gb: float = 0.25                   # 40 + 44 (100 MB + 150 MB)
    vcpu: float = 0.2                      # 40 + 44 (0.1 + 0.1)
    disk_gb: float = 0.1


@dataclass
class Redis:
    """The streaming hot store (Real-time Inference branch): latest reading +
    prediction per sensor/HSI site, overwritten in place - not a growing
    stream. The separate CKAN Redis instance isn't modeled; add it under
    [[extra_components]] if needed."""
    bytes_per_key: float = 300.0           # one key per sensor + per HSI site
    ram_overhead_mb: float = 50.0          # process + replication buffers
    ram_headroom_factor: float = 2.0
    vcpu: float = 0.25
    min_disk_gb: float = 0.1               # RDB snapshot floor


@dataclass
class Lakehouse:
    """Bronze/Silver/Gold volume (TRACE Data Lake pipeline branch).
    Bronze HSI is assumed landed as-is (claim-check straight to S3); the
    other figures are per the confirmed design: Silver keeps HSI feature
    vectors/indices only, not a second full-resolution cube."""
    bronze_iot_size_ratio: float = 1.0        # vs raw IoT bytes; 1.0 = landed as raw JSON
    silver_iot_size_ratio: float = 0.3        # conformed/deduped Parquet vs raw IoT bytes
    silver_hsi_kb_per_cube: float = 10.0      # spectral indices/calibration stats/QC flags only
    gold_iot_rows_per_sensor_per_day: float = 24.0  # hourly aggregates
    gold_iot_bytes_per_row: float = 80.0
    gold_hsi_bytes_per_record: float = 1500.0       # per-sample score/classification + rollups
    # Iceberg manifest-list + manifest file(s) + metadata.json snapshot, written
    # on every commit, across the Bronze/Silver/Gold tables. Bytes are tiny;
    # the object COUNT is what drives S3 request cost and Glue Catalog limits.
    iceberg_tables: int = 3
    iceberg_commit_interval_min: float = 15.0
    iceberg_metadata_kb_per_commit: float = 20.0
    iceberg_objects_per_commit: int = 3


@dataclass
class MLPipeline:
    """AI/ML Pipeline training + Real-time API (Real-time Inference branch):
    model artifacts stored to/loaded from the Data Lake, and predictions
    written back. Artifact size is a fixed, versioned store, not a daily rate
    - retraining is periodic, not continuous."""
    model_variants: int = 5                # e.g. per site-group or crop type
    model_mb_per_variant: float = 10.0      # tabular/LSTM-style model over Silver features
    model_versions_retained: int = 3
    predictions_per_sensor_per_day: float = 24.0   # written back at Gold's aggregate cadence
    predictions_per_hsi_sample: float = 1.0
    prediction_bytes: float = 100.0


@dataclass
class ExtraComponent:
    """Anything the model does not derive (CKAN, PostgreSQL, Solr, the CKAN
    Redis instance, MQTT, API...)."""
    name: str
    vcpu: float = 0.0
    ram_gb: float = 0.0
    disk_gb: float = 0.0


@dataclass
class VM:
    name: str
    vcpu: float = 4.0                      # 48
    ram_gib: float = 16.0                  # 48
    disk_gb: float = 100.0
    instance_type: str = "m7g.xlarge"      # priced in config/cost.toml


@dataclass
class StoragePolicy:
    """S3 storage tiers (retention policy). Ages are days since ingestion.

    Raw HSI cubes: S3 Standard until hsi_standard_days, Glacier Instant
    Retrieval until hsi_glacier_ir_until_days, then Deep Archive.
    Raw scalar (IoT) data: one tier for its whole life (default Glacier IR,
    a shortcut since it's small). Silver and Gold: S3 Standard for the whole
    project, plus silver_gold_overhead for versioning and Iceberg snapshots."""
    hsi_standard_days: float = 60.0
    hsi_glacier_ir_until_days: float = 365.0
    iot_raw_tier: str = "glacier_ir"        # "standard" | "glacier_ir" | "deep_archive"
    silver_gold_overhead: float = 0.10

    def __post_init__(self) -> None:
        if self.iot_raw_tier not in ("standard", "glacier_ir", "deep_archive"):
            raise ValueError("[storage] iot_raw_tier must be standard, glacier_ir or deep_archive")
        if not 0 < self.hsi_standard_days <= self.hsi_glacier_ir_until_days:
            raise ValueError("[storage] need 0 < hsi_standard_days <= hsi_glacier_ir_until_days")
        if self.silver_gold_overhead < 0:
            raise ValueError("[storage] silver_gold_overhead must be >= 0")


@dataclass
class Glue:
    """AWS Glue ETL job shape (Data Lake pipeline). Turns into DPU-hours in the
    usage block; the price per DPU-hour lives in config/cost.toml."""
    etl_runs_per_hour: float = 2.0          # two hourly Spark stages (Bronze->Silver, Silver->Gold)
    etl_dpus: float = 2.0
    etl_minutes_per_run: float = 3.0
    maintenance_runs_per_day: float = 1.0   # Iceberg compaction / snapshot expiry
    maintenance_dpus: float = 2.0
    maintenance_minutes_per_run: float = 10.0
    feature_vcpu_seconds_per_cube: float = 30.0   # HSI feature extraction
    vcpu_per_dpu: float = 4.0


@dataclass
class Network:
    """Network quantities. Prices live in config/cost.toml."""
    public_ipv4_count: int = 3
    nat_instances: int = 1
    egress_gb_month: float = 0.0            # data out to the internet beyond the free 100 GB
    glacier_ir_retrieval_gb_month: float = 0.0   # GB read back from Glacier IR each month


@dataclass
class Requests:
    """S3 request assumptions."""
    data_files_per_commit: int = 1          # Iceberg data files written per commit, per table
    gets_per_put: float = 2.0


@dataclass
class Sizing:
    disk_headroom: float = 0.5             # 45 (+50 %)
    os_ram_gb_per_vm: float = 1.0          # 46
    os_disk_gb_per_vm: float = 20.0        # 46
    project_months: int = 36
    # Months of data to keep in storage across all services (S3/Iceberg,
    # not Kafka's or Prometheus's own short operational retention below).
    # None = keep everything for the whole project (no roll-off). If set
    # below project_months, storage plateaus at a rolling retention_months
    # window instead of growing for the full project.
    retention_months: float | None = None
    scale_factors: list[float] = field(default_factory=lambda: [0.1, 0.5, 1, 2, 10, 100])

    def __post_init__(self) -> None:
        if self.retention_months is not None and self.retention_months <= 0:
            raise ValueError("[sizing] retention_months must be positive (or omitted/none)")


@dataclass
class Params:
    iot: IoT = field(default_factory=IoT)
    hsi: HSI = field(default_factory=HSI)
    kafka: Kafka = field(default_factory=Kafka)
    flink: Flink = field(default_factory=Flink)
    prometheus: Prometheus = field(default_factory=Prometheus)
    grafana: Grafana = field(default_factory=Grafana)
    alerting: AlertingExporters = field(default_factory=AlertingExporters)
    redis: Redis = field(default_factory=Redis)
    lakehouse: Lakehouse = field(default_factory=Lakehouse)
    ml: MLPipeline = field(default_factory=MLPipeline)
    storage: StoragePolicy = field(default_factory=StoragePolicy)
    glue: Glue = field(default_factory=Glue)
    network: Network = field(default_factory=Network)
    requests: Requests = field(default_factory=Requests)
    sizing: Sizing = field(default_factory=Sizing)
    extra_components: list[ExtraComponent] = field(default_factory=list)
    vms: list[VM] = field(
        default_factory=lambda: [
            VM("portal", disk_gb=100),
            VM("data-plane", disk_gb=100),
            VM("app", disk_gb=50),
        ]
    )

    def scaled(self, factor: float) -> "Params":
        """Copy with sites scaled by `factor` (sensors and cameras per site unchanged)."""
        p = dataclasses.replace(
            self,
            iot=dataclasses.replace(self.iot, pilot_sites=self.iot.pilot_sites * factor),
            hsi=dataclasses.replace(self.hsi, sites_with_camera=self.hsi.sites_with_camera * factor),
        )
        return p


_SECTIONS = {
    "iot": IoT,
    "hsi": HSI,
    "kafka": Kafka,
    "flink": Flink,
    "prometheus": Prometheus,
    "grafana": Grafana,
    "alerting": AlertingExporters,
    "redis": Redis,
    "lakehouse": Lakehouse,
    "ml": MLPipeline,
    "storage": StoragePolicy,
    "glue": Glue,
    "network": Network,
    "requests": Requests,
    "sizing": Sizing,
}


def _build(cls: type, data: dict[str, Any], where: str):
    known = {f.name for f in dataclasses.fields(cls)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"[{where}] unknown key(s): {', '.join(sorted(unknown))}")
    return cls(**data)


_MOVED_PRICING = (
    "[pricing] has moved. Region, prices, usd_to_eur, discount, vat, budget_eur and the fixed "
    "monthly items (ML training, logging/KMS) go in config/cost.toml. In this file: the Glue job "
    "shape goes in [glue]; public_ipv4_count, egress_gb_month and glacier_ir_retrieval_gb_month "
    "in [network]; data_files_per_commit and gets_per_put in [requests]."
)


def from_dict(data: dict[str, Any]) -> Params:
    if "pricing" in data:
        raise ValueError(_MOVED_PRICING)
    for vm in data.get("vms", []):
        if "hourly_usd" in vm:
            raise ValueError(
                f"[[vms]] {vm.get('name', '?')}: hourly_usd has moved to config/cost.toml "
                "([prices.vm_hourly], keyed by instance type)."
            )
    unknown = set(data) - set(_SECTIONS) - {"extra_components", "vms"}
    if unknown:
        raise ValueError(f"unknown section(s): {', '.join(sorted(unknown))}")
    kwargs: dict[str, Any] = {
        name: _build(cls, data.get(name, {}), name) for name, cls in _SECTIONS.items()
    }
    kwargs["extra_components"] = [
        _build(ExtraComponent, c, "extra_components") for c in data.get("extra_components", [])
    ]
    if "vms" in data:
        kwargs["vms"] = [_build(VM, v, "vms") for v in data["vms"]]
    return Params(**kwargs)


def load(path: str | Path) -> Params:
    with open(path, "rb") as f:
        return from_dict(tomllib.load(f))
