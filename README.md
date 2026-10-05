# trace-sizing

Sizing calculator for the TRACE WP3 platform. You give it the workload parameters
(sites, sensors, reporting interval, HSI cube size and scan rate, Kafka/Flink/Prometheus
settings), and it calculates:

- **Usage**: message rates, throughput, daily volume, peak HSI upload bandwidth, and
  accumulated raw volume per day, month, year and project.
- **Spec required**: CPU load vs vCPU to allocate, RAM in use vs RAM to allocate, and data
  stored vs disk with headroom, for Kafka, Flink, Prometheus, Grafana and Alertmanager/exporters.
- **VM fit**: whether the totals plus OS overhead fit the VM fleet (by default 3 × 4 vCPU / 16 GiB).
- **Scaling**: the same figures at 0.1× to 100× the number of sites.

`[iot]` and `[hsi]` implement the canonical 11-parameter **System Parameters** table used
across the TRACE chats (IoT #1-6, HSI #7-11; see [Parameter file](#parameter-file)).
The remaining sections (`[kafka]`, `[flink]`, `[prometheus]`, ...) are downstream component
settings from *TRACE – AWS Cost Estimate (EUR)* ("Volume calculation" and the doc's own,
differently-numbered "System parameter assumptions" table for Kafka/Flink/Prometheus sizing).
The tests check the results against the hand calculations in that doc.

## Quick start

Needs Python 3.11 or later and has no runtime dependencies.

```bash
pip install -e '.[dev]'
```

```bash
trace-sizing examples/trace_10_sites.toml
```

You can also run it without installing:

```bash
PYTHONPATH=src python3 -m trace_sizing examples/trace_10_sites.toml
```

Common options:

| Option | Effect |
|---|---|
| `--set iot.pilot_sites=5` | Override one parameter (repeatable) |
| `--scale 0.5,1,2,10` | Scale factors for the scaling table (`none` to skip it) |
| `--format json` | Machine-readable output (params + result + scaling) |
| `-o report.md` | Write to a file |

Example: what changes if HSI runs at 3 sites with 100 MB cubes, 20 samples/day?

```bash
trace-sizing --set hsi.sites_with_camera=3 --set hsi.cube_mb=100 --set hsi.samples_per_day=20
```

## Parameter file

The parameter file is TOML. [examples/trace_10_sites.toml](examples/trace_10_sites.toml)
lists every key, with the parameter's # from the System Parameters table in a comment next
to each `[iot]`/`[hsi]` field. Omitted keys use the defaults, and unknown keys are rejected
so typos don't pass silently.

The 11 system parameters:

| # | Section | Field | Parameter |
|---|---|---|---|
| 1 | `[iot]` | `pilot_sites` | Pilot site count |
| 2 | `[iot]` | `sensors_per_site` | Sensor count per site |
| 3 | `[iot]` | `reporting_interval_s` | Reporting interval (s) |
| 4 | `[iot]` | `message_bytes` | Message size and format (bytes/reading) |
| 5 | `[iot]` | `operating_hours_per_day` | Operating hours (24 if 24/7) |
| 6 | `[iot]` | `operating_days_per_year` | Operating days per year |
| 7 | `[hsi]` | `sites_with_camera` | Number of sites with HSI camera |
| 8 | `[hsi]` | `cube_mb` (or `pixels`/`lines`/`bands`/`bytes_per_value`) | Image size (cube size, MB) and format |
| 9 | `[hsi]` | `scans_per_sample` | Scans per sample (incl. repeats/reference scans) |
| 10 | `[hsi]` | `samples_per_day` | Number of samples per day, **per HSI site** |
| 11 | `[hsi]` | `operating_days_per_year` | HSI operating days per year |

- `[hsi]`: set `cube_mb` directly, or all four of `pixels`/`lines`/`bands`/`bytes_per_value`
  (cube size is then derived). See [examples/trace_5_sites_50_scans.toml](examples/trace_5_sites_50_scans.toml).
- `hsi.upload_window_hours_per_day` is **not** one of the 11 parameters — it only turns the
  daily cube count into a peak MB/s figure for network sizing. Set it to `none` (or omit it with
  `--set hsi.upload_window_hours_per_day=none`) to get a 24h average rate instead of a peak.
- `[[vms]]`: the fleet to check against.
- `[[extra_components]]`: CKAN, PostgreSQL, Solr, Redis, MQTT, the inference API, and anything
  else the model doesn't derive. Add measured figures here so they count toward the totals
  and the fit check.

## Formulas

| Quantity | Formula |
|---|---|
| IoT msg/s | sites × sensors ÷ interval |
| HSI cubes/site/day | samples/day × scans/sample |
| HSI upload per site (peak) | cubes/site/day × cube size ÷ upload window (seconds) |
| Kafka data | daily volume through Kafka × retention × RF (claim-check: IoT + HSI pointer events only) |
| Kafka disk | data × (1 + headroom) |
| Flink state | sensors × (window ÷ interval) × bytes per reading |
| Flink TaskManager | max(default 1.7 GB, 1.2 GB + 4 × state) |
| Prometheus series | sensors × metrics/sensor + HSI sites × 4 + infrastructure series |
| Prometheus disk | series ÷ scrape × 86400 × bytes/sample × retention × (1 + headroom) |
| Prometheus RAM | series × 4 KB + 150 MB in use; allocate max(1 GB, 2 × in use) |
| Accumulated per year | HSI/day × HSI days + IoT/day × IoT days |

Scaling multiplies the number of sites (and HSI camera sites). Sensors and cameras per site
stay the same.

## Known limits

- CPU *load* figures use per-event cost estimates (`cpu_us_per_message`, `cpu_us_per_event`,
  `cpu_us_per_sample`). These are not measured. Allocation is set by each tool's minimum footprint.
- The Flink TaskManager and Prometheus RAM growth rules are my own reading of the doc's
  "about 4 GB" and "2–4 GB" notes. At 100× the model allocates about 15 GB of RAM, while the doc
  estimates about 19 GB. Tune `[flink]` and `[prometheus]` if you settle on different rules.
- The fit check compares totals against the whole fleet. It does not place components on
  individual VMs.
- Costs (EC2, S3 tiers, Glue) are not included yet.

## Tests

```bash
python3 -m pytest -q
```
