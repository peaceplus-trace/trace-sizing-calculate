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
class ExtraComponent:
    """Anything the model does not derive (CKAN, PostgreSQL, Solr, Redis, MQTT, API...)."""
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


@dataclass
class Sizing:
    disk_headroom: float = 0.5             # 45 (+50 %)
    os_ram_gb_per_vm: float = 1.0          # 46
    os_disk_gb_per_vm: float = 20.0        # 46
    project_months: int = 36
    scale_factors: list[float] = field(default_factory=lambda: [0.1, 0.5, 1, 2, 10, 100])


@dataclass
class Params:
    iot: IoT = field(default_factory=IoT)
    hsi: HSI = field(default_factory=HSI)
    kafka: Kafka = field(default_factory=Kafka)
    flink: Flink = field(default_factory=Flink)
    prometheus: Prometheus = field(default_factory=Prometheus)
    grafana: Grafana = field(default_factory=Grafana)
    alerting: AlertingExporters = field(default_factory=AlertingExporters)
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
    "sizing": Sizing,
}


def _build(cls: type, data: dict[str, Any], where: str):
    known = {f.name for f in dataclasses.fields(cls)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"[{where}] unknown key(s): {', '.join(sorted(unknown))}")
    return cls(**data)


def from_dict(data: dict[str, Any]) -> Params:
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
