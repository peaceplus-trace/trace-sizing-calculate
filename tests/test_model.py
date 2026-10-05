"""Expected values are the hand calculations in the TRACE WP3 cost-estimate doc."""

import json
from pathlib import Path

import pytest

from trace_sizing import Params, calculate, from_dict, load, scaling_table
from trace_sizing.cli import main
from trace_sizing.model import GB, KB, MB, TB

ROOT = Path(__file__).parent.parent
EXAMPLES = ROOT / "examples"
CONFIG = ROOT / "config"
approx = pytest.approx


@pytest.fixture(scope="module")
def r():
    return calculate(Params())


def comp(r, prefix):
    return next(c for c in r.components if c.name.startswith(prefix))


def test_iot_volume(r):
    i = r.workload.iot
    assert i.sensors == 500
    assert i.msg_per_s == approx(16.67, abs=0.01)
    assert i.msgs_per_day == approx(1_440_000)
    assert i.bytes_per_s / KB == approx(8.33, abs=0.01)
    assert i.bytes_per_day / GB == approx(0.72)


def test_hsi_volume(r):
    h = r.workload.hsi
    assert h.cubes_per_site_per_day == approx(48)
    assert h.cubes_per_day == approx(480)
    assert h.cubes_per_s_peak == approx(0.0167, abs=1e-4)
    assert h.cubes_per_s_24h == approx(0.0056, abs=1e-4)
    assert h.bytes_per_day_per_site / GB == approx(9.6)
    assert h.bytes_per_day / GB == approx(96)
    assert h.site_bytes_per_s_peak * 8 / MB == approx(2.67, abs=0.01)
    assert h.total_bytes_per_s_peak * 8 / MB == approx(26.7, abs=0.1)
    assert h.is_peak_window
    assert h.pointer_bytes_per_day / MB == approx(0.24)
    assert r.workload.hsi_byte_share == approx(0.993, abs=0.001)


def test_accumulated(r):
    a = r.workload.accumulated
    assert a.day_bytes / GB == approx(96.72)
    assert a.year_bytes / TB == approx(25.2, abs=0.05)
    assert a.month_bytes / TB == approx(2.1, abs=0.05)
    assert a.project_bytes / TB == approx(76, abs=0.5)


def test_kafka(r):
    k = comp(r, "Kafka")
    assert k.notes["data_per_broker_gb"] == approx(5.04, abs=0.01)
    assert k.data_gb == approx(15.1, abs=0.05)
    assert k.disk_gb == approx(22.7, abs=0.05)
    assert (k.vcpu, k.ram_gb) == (3, 6)
    assert k.cpu_load < 0.05


def test_flink(r):
    f = comp(r, "Flink")
    assert f.notes["state_mb"] == approx(6)
    assert f.notes["checkpoints_s3_mb"] == approx(18)
    assert f.ram_gb == approx(3.3)
    assert f.disk_gb == 1
    assert f.cpu_load < 0.01
    assert not f.notes["taskmanager_resized"]


def test_prometheus(r):
    p = comp(r, "Prometheus")
    assert p.notes["active_series"] == 13_640
    assert p.data_gb == approx(1.77, abs=0.01)
    assert p.disk_gb == approx(2.65, abs=0.01)
    assert p.ram_load_gb == approx(0.20, abs=0.01)
    assert p.ram_gb == 1
    assert p.cpu_load < 0.05


def test_totals_and_fit(r):
    t = r.total
    assert t.cpu_load < 0.2
    assert t.vcpu == approx(4.95)
    assert t.ram_gb == approx(10.8)
    assert t.data_gb == approx(17, abs=0.1)
    assert t.disk_gb == approx(26.6, abs=0.1)
    assert r.fit.fits
    assert r.fit.required_ram_gb == approx(13.8)
    assert r.fit.required_disk_gb == approx(86.6, abs=0.1)


@pytest.mark.parametrize(
    "factor, msg_s, broker_gb, cluster_gb, series, prom_ram",
    [
        (0.1, 1.7, 0.5, 2.3, 10_004, 0.19),
        (0.5, 8.3, 2.5, 11.3, 11_620, 0.20),
        (2, 33.3, 10.1, 45.4, 17_680, 0.22),
        (10, 167, 50.4, 227, 50_000, 0.35),
        (100, 1667, 504, 2269, 413_600, 1.8),
    ],
)
def test_scaling_matches_doc(factor, msg_s, broker_gb, cluster_gb, series, prom_ram):
    (_, _, r), = scaling_table(Params(), [factor])
    k, p = comp(r, "Kafka"), comp(r, "Prometheus")
    assert r.workload.iot.msg_per_s == approx(msg_s, rel=0.03)
    assert k.notes["data_per_broker_gb"] == approx(broker_gb, rel=0.03)
    assert k.disk_gb == approx(cluster_gb, rel=0.03)
    assert p.notes["active_series"] == series
    assert p.ram_load_gb == approx(prom_ram, abs=0.01)


def test_100x_grows_flink_and_prometheus():
    (_, _, r), = scaling_table(Params(), [100])
    f, p = comp(r, "Flink"), comp(r, "Prometheus")
    assert f.notes["state_mb"] == approx(600)
    assert f.notes["taskmanager_resized"]
    assert 3 < f.notes["taskmanager_gb"] < 4.5   # doc: "about 4 GB"
    assert 2 <= p.ram_gb <= 4                    # doc: "2-4 GB"
    assert not r.fit.fits                        # ~2.3 TB of Kafka disk


def test_config_file_equals_defaults():
    assert load(CONFIG / "trace_workload.toml") == Params()


def test_cube_from_dimensions():
    p = load(EXAMPLES / "trace_5_sites_50_scans.toml")
    r = calculate(p)
    assert r.workload.hsi.cube_bytes / MB == approx(61.44)
    assert r.workload.hsi.cubes_per_day == 250
    assert r.workload.iot.sensors == 100


def test_hsi_without_upload_window_gives_24h_average():
    p = from_dict({"hsi": {"upload_window_hours_per_day": None}})
    r = calculate(p)
    h = r.workload.hsi
    assert not h.is_peak_window
    assert h.cubes_per_s_peak == approx(h.cubes_per_s_24h)
    assert h.total_bytes_per_s_peak == approx(h.cubes_per_s_24h * h.cube_bytes)


def test_extra_components_counted():
    p = from_dict({"extra_components": [{"name": "CKAN", "vcpu": 2, "ram_gb": 6, "disk_gb": 40}]})
    r = calculate(p)
    assert r.total.vcpu == approx(6.95)
    assert r.total.ram_gb == approx(16.8)


def test_unknown_key_rejected():
    with pytest.raises(ValueError, match="pilot_site"):
        from_dict({"iot": {"pilot_site": 3}})


def test_cli_json_and_overrides(capsys):
    assert main(["--format", "json", "--scale", "none", "--set", "iot.pilot_sites=5"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["params"]["iot"]["pilot_sites"] == 5
    assert doc["result"]["workload"]["iot"]["sensors"] == 250
    assert doc["scaling"] == []


def test_cli_markdown(capsys):
    assert main([str(CONFIG / "trace_workload.toml"), "--scale", "1,10"]) == 0
    out = capsys.readouterr().out
    assert "## VM fit: FITS" in out
    assert "## Scaling" in out
