"""Expected values are the hand calculations in the TRACE WP3 cost-estimate doc."""

import json
from pathlib import Path

import pytest

from trace_sizing import Params, calculate, from_dict, load, scaling_table
from trace_sizing.cli import main
from trace_sizing.model import GB, KB, MB, TB
from trace_sizing.html_report import full_html
from trace_sizing.report import params_md

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
    # No retention_months set by default: retained == the whole project, nothing capped.
    assert a.retention_months == 36
    assert not a.is_capped
    assert a.retained_bytes == approx(a.project_bytes)


def test_retention_months_caps_storage():
    p = from_dict({"sizing": {"retention_months": 12}})
    a = calculate(p).workload.accumulated
    assert a.is_capped
    assert a.retention_months == 12
    assert a.retained_bytes == approx(a.year_bytes)        # 12 months == 1 year
    assert a.retained_bytes < a.project_bytes


def test_retention_months_above_project_is_not_capped():
    p = from_dict({"sizing": {"retention_months": 999}})
    a = calculate(p).workload.accumulated
    assert not a.is_capped
    assert a.retention_months == p.sizing.project_months
    assert a.retained_bytes == approx(a.project_bytes)


def test_retention_months_must_be_positive():
    with pytest.raises(ValueError, match="retention_months"):
        from_dict({"sizing": {"retention_months": 0}})


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


def test_redis(r):
    red = comp(r, "Redis")
    assert red.notes["keys"] == 510                     # 500 sensors + 10 HSI sites
    assert red.vcpu == 0.25
    assert red.ram_gb == approx(0.1, abs=0.01)
    assert red.disk_gb == approx(0.1, abs=0.01)          # floor; live data is ~0.15 MB


def test_lakehouse_volume(r):
    lh = r.workload.lakehouse
    assert lh.bronze_hsi_bytes_per_day / GB == approx(96)         # == raw HSI, landed as-is
    assert lh.bronze_iot_bytes_per_day / GB == approx(0.72)       # ratio 1.0 by default
    assert lh.silver_hsi_bytes_per_day / MB == approx(4.8)        # 480 cubes x 10 KB
    assert lh.silver_iot_bytes_per_day / MB == approx(216)        # 0.72 GB x 0.3
    assert lh.gold_iot_bytes_per_day / MB == approx(0.96, abs=0.01)   # 500 x 24 x 80 B
    assert lh.gold_hsi_bytes_per_day / MB == approx(0.72, abs=0.01)   # 480 x 1500 B
    assert lh.iceberg_commits_per_day == approx(288)              # (1440/15) x 3 tables
    assert lh.iceberg_objects_per_day == approx(864)
    assert lh.iceberg_metadata_bytes_per_day / MB == approx(5.76, abs=0.01)


def test_ml_volume(r):
    ml = r.workload.ml
    assert ml.model_artifact_total_bytes / MB == approx(150)      # 5 variants x 10 MB x 3 versions
    assert ml.prediction_events_per_day == approx(12_480)         # 500x24 + 480x1
    assert ml.prediction_bytes_per_day / MB == approx(1.248, abs=0.001)


def test_totals_and_fit(r):
    t = r.total
    assert t.cpu_load < 0.2
    assert t.vcpu == approx(5.2)
    assert t.ram_gb == approx(10.9, abs=0.05)
    assert t.data_gb == approx(17, abs=0.1)
    assert t.disk_gb == approx(26.7, abs=0.1)
    assert r.fit.fits
    assert r.fit.required_ram_gb == approx(13.9, abs=0.05)
    assert r.fit.required_disk_gb == approx(86.7, abs=0.1)


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
    assert r.total.vcpu == approx(7.2)
    assert r.total.ram_gb == approx(16.9, abs=0.05)


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


def test_params_md_renders_every_section():
    out = params_md(Params())
    for section in ["iot", "hsi", "kafka", "flink", "prometheus", "grafana",
                     "alerting", "redis", "lakehouse", "ml", "sizing"]:
        assert f"**[{section}]**" in out
    assert "| pilot_sites | 10 |" in out
    assert "| pixels | none |" in out        # None -> "none", not "None" or blank
    assert "| claim_check | true |" in out   # bool -> "true"/"false"


def test_cli_shows_params_with_overrides_by_default(capsys):
    assert main(["--scale", "none", "--set", "iot.pilot_sites=5"]) == 0
    out = capsys.readouterr().out
    assert "## Parameters used" in out
    assert "| pilot_sites | 5 |" in out      # the override, not the default of 10


def test_cli_no_params_hides_section(capsys):
    assert main(["--scale", "none", "--no-params"]) == 0
    assert "## Parameters used" not in capsys.readouterr().out


def test_full_html_well_formed_and_matches_md_numbers(r):
    out = full_html(Params(), r)
    assert out.startswith("<!doctype html>")
    assert out.count("<table>") == out.count("</table>")
    assert out.count("<section>") == out.count("</section>")
    assert "<h1>TRACE sizing report</h1>" in out
    assert ">FITS<" in out                      # VM fit badge
    assert "<td>16.67 msg/s</td>" in out         # same number as the md report
    assert "<td>96 GB</td>" in out                # Bronze HSI == raw HSI


def test_full_html_escapes_vm_names():
    p = from_dict({"vms": [{"name": "<script>alert(1)</script>", "vcpu": 1, "ram_gib": 1, "disk_gb": 1}]})
    out = full_html(p, calculate(p))
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


def test_cli_html_format(capsys):
    assert main(["--format", "html", "--scale", "none"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("<!doctype html>")
    assert "## Parameters used" not in out        # that's the md section marker, not html's


def test_formulas_cover_every_derived_section(r):
    from trace_sizing.formulas import formulas
    sections = {f.section for f in formulas(Params(), r)}
    assert {"IoT", "HSI", "Accumulated", "Data Lake", "ML", "Kafka", "Flink",
            "Prometheus", "Redis", "VM fit"} <= sections


def test_formula_worked_values_match_results(r):
    from trace_sizing.formulas import formulas
    by_key = {(f.section, f.quantity): f for f in formulas(Params(), r)}
    assert by_key[("IoT", "Sensors")].result == "500"
    assert by_key[("HSI", "Cubes per day (all sites)")].worked.endswith("= 480")
    assert by_key[("Kafka", "Disk to allocate")].worked.endswith("22.69 GB")   # as in the report
    assert by_key[("VM fit", "Fits")].result == "FITS"


def test_md_report_includes_formulas_by_default(capsys):
    assert main(["--scale", "none", "--no-params"]) == 0
    out = capsys.readouterr().out
    assert "## Formulas" in out
    assert "`sites x sensors_per_site`" in out


def test_cli_no_formulas_hides_section(capsys):
    assert main(["--scale", "none", "--no-params", "--no-formulas"]) == 0
    assert "## Formulas" not in capsys.readouterr().out


def test_html_report_has_formulas_section(r):
    out = full_html(Params(), r)
    assert "<h2>Formulas</h2>" in out
    assert "<code>sites x sensors_per_site</code>" in out


def test_storage_end_of_project_matches_policy(r):
    end = r.storage.end_by_stream
    # 60 days Standard, 305 days Glacier IR, 730 days Deep Archive for raw HSI
    assert end["hsi_raw"]["standard"] / GB == approx(4103, rel=1e-3)
    assert end["hsi_raw"]["glacier_ir"] / GB == approx(20857, rel=1e-3)
    assert end["hsi_raw"]["deep_archive"] / GB == approx(49920, rel=1e-3)
    assert end["iot_raw"]["glacier_ir"] / GB == approx(788.4, rel=1e-3)   # all raw scalar in IR
    assert sum(end["iot_raw"][t] for t in ("standard", "deep_archive")) == 0
    # Silver/Gold stay Standard, +10% overhead
    assert end["silver"]["standard"] / GB == approx(264.3, rel=1e-3)
    assert end["gold"]["standard"] / GB == approx(1.77, rel=1e-2)


def test_storage_total_is_raw_plus_overhead(r):
    # Over 36 months (1095 days): HSI on 260 of every 365 days, IoT on all 365,
    # Silver/Gold carry the 10% overhead.
    lh, w = r.workload.lakehouse, r.workload
    days = 36 * 365 / 12
    hsi_raw = w.hsi.bytes_per_day * 260 / 365 * days
    iot_raw = lh.bronze_iot_bytes_per_day * days
    silver = (lh.silver_hsi_bytes_per_day * 260 / 365 + lh.silver_iot_bytes_per_day) * days * 1.10
    gold = (lh.gold_hsi_bytes_per_day * 260 / 365 + lh.gold_iot_bytes_per_day) * days * 1.10
    end = r.storage.end_by_stream
    assert sum(end["hsi_raw"].values()) == approx(hsi_raw)
    assert sum(end["iot_raw"].values()) == approx(iot_raw)
    assert sum(end["silver"].values()) == approx(silver)
    assert sum(end["gold"].values()) == approx(gold)


def test_storage_milestones_grow_then_deep_archive_starts(r):
    m = {x["label"].split(" ")[0]: x for x in r.storage.milestones}
    assert m["2"]["deep_archive"] == 0
    assert m["12"]["deep_archive"] == 0
    assert m["24"]["deep_archive"] > 0
    totals = [x["standard"] + x["glacier_ir"] + x["deep_archive"] for x in r.storage.milestones]
    assert totals == sorted(totals)


def test_storage_retention_cap_deletes_old_data():
    p = from_dict({"sizing": {"retention_months": 12}})
    r12 = calculate(p)
    end = r12.storage.end_by_stream
    # only the last 12 months survive: no Deep Archive, 365 days of HSI in tiers
    assert end["hsi_raw"]["deep_archive"] == 0
    assert end["hsi_raw"]["glacier_ir"] / GB == approx(20857, rel=1e-3)   # 305 days of HSI still in IR


def test_storage_validation():
    with pytest.raises(ValueError, match="iot_raw_tier"):
        from_dict({"storage": {"iot_raw_tier": "tape"}})
    with pytest.raises(ValueError, match="hsi_standard_days"):
        from_dict({"storage": {"hsi_standard_days": 400, "hsi_glacier_ir_until_days": 365}})


def test_storage_section_in_reports(r, capsys):
    assert main(["--scale", "none", "--no-params"]) == 0
    out = capsys.readouterr().out
    assert "## S3 storage by tier (retention policy)" in out
    assert "Glacier Deep Archive" in out
    assert "<h2>S3 storage by tier" not in out
    assert "<h2>S3 storage by tier" in full_html(Params(), r)


def test_format_markdown_alias_and_extension_inference(tmp_path, capsys):
    assert main(["--format", "markdown", "--scale", "none"]) == 0
    assert capsys.readouterr().out.startswith("# TRACE sizing report")
    out_md = tmp_path / "report.md"
    assert main(["--scale", "none", "-o", str(out_md)]) == 0
    assert out_md.read_text().startswith("# TRACE sizing report")
    out_html = tmp_path / "report.html"
    assert main(["--scale", "none", "-o", str(out_html)]) == 0
    assert out_html.read_text().startswith("<!doctype html>")


def test_explicit_format_overrides_extension(tmp_path):
    out = tmp_path / "report.md"
    assert main(["--format", "html", "--scale", "none", "-o", str(out)]) == 0
    assert out.read_text().startswith("<!doctype html>")
