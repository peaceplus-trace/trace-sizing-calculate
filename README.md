# trace-sizing

Sizing calculator for the TRACE WP3 platform. You give it the workload parameters
(sites, sensors, reporting interval, HSI cube size and scan rate, Kafka/Flink/Prometheus
settings), and it calculates:

- **Usage**: message rates, throughput, daily volume, peak HSI upload bandwidth, and
  accumulated raw volume per day, month, year and project.
- **Spec required**: CPU load vs vCPU to allocate, RAM in use vs RAM to allocate, and data
  stored vs disk with headroom, for Kafka, Flink, Prometheus, Grafana, Alertmanager/exporters
  and the Redis hot store.
- **Data Lake pipeline & ML volume**: Bronze/Silver/Gold daily bytes, Iceberg commit/object
  counts, and ML model artifact + prediction volume — informational (S3/Glue aren't part of
  the VM fleet), but shows what the Data Lake pipeline and Real-time Inference branches add.
- **VM fit**: whether the totals plus OS overhead fit the VM fleet (by default 3 × 4 vCPU / 16 GiB).
- **Scaling**: the same figures at 0.1× to 100× the number of sites.

Every run also prints a **Parameters used** section with every resolved input value — the
TOML file plus any `--set` overrides — so a report states exactly what it was computed from
(`--no-params` to hide it). Output is Markdown by default; `--format html` renders the same
report as a single, dependency-free HTML page (light/dark, usage-percentage bars, collapsible
parameters) you can open directly or send to someone.

Each report also has a **Formulas** section: every derived number (IoT rates, HSI cubes, Kafka/Flink/Prometheus/Redis sizing, Bronze/Silver/Gold, ML, VM fit) with its formula, the formula with this run's values substituted in, and the result. The formulas are listed in `src/trace_sizing/formulas.py`; if you change a calculation in `model.py`, update its formula there too.

These map onto the three branches off the single streaming backbone: **Monitoring & Alerting**
(Kafka → Flink → Prometheus → Grafana → paging), **Real-time Inference** (Kafka → Flink →
Redis hot store → API, plus the AI/ML Pipeline's model artifacts and predictions), and the
**TRACE Data Lake pipeline** (Kafka → Bronze → Silver → Gold via Iceberg + Spark/Glue).

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
trace-sizing config/trace_workload.toml
```

You can also run it without installing:

```bash
PYTHONPATH=src python3 -m trace_sizing config/trace_workload.toml
```

For a report you can open in a browser or send to someone:

```bash
trace-sizing config/trace_workload.toml --format html -o report.html
```

Common options:

| Option | Effect |
|---|---|
| `--set iot.pilot_sites=5` | Override one parameter (repeatable) |
| `--scale 0.5,1,2,10` | Scale factors for the scaling table (`none` to skip it) |
| `--format md` (or `markdown`) | Markdown report; the default. Inferred from `-o report.md` if `--format` is omitted |
| `--format html` | Single self-contained HTML page (light/dark, collapsible params, usage bars) |
| `--format json` | Machine-readable output (params + result + scaling) |
| `--no-params` | Hide the "Parameters used" section (md/html only; json always includes params) |
| `--no-formulas` | Hide the "Formulas" section (md/html only; json always includes formulas) |
| `-o report.md` | Write to a file |

Example: what changes if HSI runs at 3 sites with 100 MB cubes, 20 samples/day?

```bash
trace-sizing --set hsi.sites_with_camera=3 --set hsi.cube_mb=100 --set hsi.samples_per_day=20
```

### Published pages

The GitHub Pages build (`.github/workflows/pages.yml`) publishes, side by side:

| Page | URL |
|---|---|
| Sizing report | https://peaceplus-trace.github.io/trace-sizing-calculate/ |
| Cost estimate | https://peaceplus-trace.github.io/trace-sizing-calculate/cost.html |
| Markdown / JSON | `report.md`, `report.json` (the JSON is what `trace-cost` reads) |

Both HTML pages share a top bar linking to each other. It comes from `--link LABEL=URL`,
which both `trace-sizing` and `trace-cost` accept; without it (e.g. local runs) there's no bar.
To add another page, generate it in the build step and add a `--link` for it.

### Sharing a link to part of the HTML report

Every section, sub-heading and table row in the HTML report has an `id`. Hover over one and
click the `#` that appears: the page copies a link to that element, e.g.
`https://peaceplus-trace.github.io/trace-sizing-calculate/#storage--deep-archive`. Opening the
link scrolls to the element, highlights it, and expands the Parameters section if it's inside.

Ids come from fixed keys, not displayed values, so links keep working after the config
changes and the report is regenerated. Examples: `#storage`, `#storage--by-stream--hsi-raw`,
`#components--kafka`, `#vm-fit--disk`, `#params--storage--hsi-standard-days`,
`#formulas--kafka--disk-to-allocate`. A link breaks only if what it points to is removed or
renamed in the code.

## AWS cost estimate (pipeline)

Cost is a separate stage that only reads the sizing report, so you can price the same sizing
several ways without re-running it:

```
trace_workload.toml ──► trace-sizing ──► report.json ──► trace-cost ──► cost.html / .md / .json
                                       (usage block)    ▲
                                          cost.toml ────┘  region, prices, VAT, budget, VM overrides
```

```bash
trace-sizing config/trace_workload.toml --format json -o build/report.json
trace-cost build/report.json -o build/cost.html
trace-cost build/report.json --vm portal=m7g.2xlarge --vm app=none -o build/cost-alt.html
trace-cost build/report.json --region us-east-1 --price glue_dpu_hour=0.308 -o build/cost-us.json
```

- **Usage** (`report.json`'s `usage` block, schema `trace-usage/1`): per-month quantities —
  VMs and hours, GB stored per S3 tier, S3 requests, lifecycle transitions, Glue DPU-hours,
  IPv4/NAT, egress, retrievals. A hand-written `usage.json`/`.toml` in the same shape works too.
- **Prices** (`config/cost.toml`): `region` picks a built-in price book
  (`src/trace_sizing/cost/prices.py`, checked against AWS's public price list); `[prices]` and
  `[prices.vm_hourly]` override or add rates.
- **Terms** (`config/cost.toml`): `[terms]` exchange rate, discount, VAT, budget; `[[fixed]]`
  monthly items such as ML training.
- **VM overrides**: `[[vms]]` in `cost.toml` or `--vm` change, add (`--vm staging=t4g.large`) or
  remove (`--vm app=none`) VMs by name; `--vm portal.ebs_gb=200` and `.hours_per_month` work too.
  The cost step doesn't re-check VM fit; re-run `trace-sizing` for that.
- `--emit-usage used.json` writes the usage actually priced, after overrides.

From Python:

```python
from trace_sizing.cost import load_usage, PriceBook, Terms, estimate

usage  = load_usage("build/report.json").with_vm_overrides([{"name": "portal", "instance_type": "m7g.2xlarge"}])
result = estimate(usage, PriceBook.for_region("eu-west-1").override(glue_dpu_hour=0.308), Terms(vat=0.23))
result.save("build/cost.json")
```

`trace-sizing` still includes the cost section in its own report, priced the same way using
`config/cost.toml` (`--cost-config PATH` to choose another, `--no-cost` to leave it out).

## Parameter file

The parameter file is TOML. [config/trace_workload.toml](config/trace_workload.toml)
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
- `sizing.retention_months`: months of data to keep across all services (S3/Iceberg), separate
  from Kafka's and Prometheus's own short operational retention. Unset (default) keeps
  everything for the whole project; set it below `project_months` to see the "Retained" row
  in the workload report plateau instead of growing with the project.
- `[redis]`: the streaming hot store (Real-time Inference branch) — latest reading + prediction
  per sensor/HSI site, overwritten in place, so it's sized as a fixed key count, not a growing
  stream. The separate CKAN Redis instance isn't modeled; add it under `[[extra_components]]`.
- `[lakehouse]`: Bronze/Silver/Gold volume (Data Lake pipeline branch). Bronze HSI is assumed
  landed as-is (claim-check, straight to S3); `silver_hsi_kb_per_cube` assumes Silver stores
  HSI **feature vectors/indices only**, not a second full-resolution cube — confirm this
  matches your actual Silver ETL design before trusting the numbers, since storing a corrected
  full cube instead would roughly double total Lakehouse HSI volume. `iceberg_*` fields turn
  commit cadence into an objects/day figure — watch that number for S3 request cost and Glue
  Catalog limits; the bytes themselves are tiny.
- `[ml]`: the AI/ML Pipeline (Real-time Inference branch) — model artifact size is a fixed,
  versioned store (retraining is periodic, not continuous), while predictions written back to
  the lake are a daily rate tied to sensor count and HSI samples.
- `[storage]`: the S3 retention policy. Raw HSI stays in S3 Standard for `hsi_standard_days` (60),
  then Glacier Instant Retrieval until `hsi_glacier_ir_until_days` (365), then Deep Archive.
  Raw IoT sits in one tier for life (`iot_raw_tier`, default `glacier_ir`). Silver and Gold stay in
  Standard for the whole project, plus `silver_gold_overhead` (10%) for versioning and Iceberg
  snapshots. If `sizing.retention_months` is set, data older than that is deleted from every tier.
- `[glue]`, `[network]`, `[requests]`: quantities the cost step prices: the Glue ETL job shape,
  public IPv4/NAT counts, egress and Glacier IR retrieval GB, and S3 request assumptions. They
  end up in the report's `usage` block. Prices are in `config/cost.toml`.
- `[[vms]]`: the fleet to check against.
- `[[extra_components]]`: CKAN, PostgreSQL, Solr, the CKAN Redis instance, MQTT, and anything
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
| Retained storage | per-year rate × min(`sizing.retention_months`, `sizing.project_months`) ÷ 12 |
| Storage in tier at T | stream/day x max(0, min(window end, T) − window start), with windows from `[storage]` |
| Redis keys | sensors + HSI sites (one "latest" key each) |
| Bronze | HSI: same as raw. IoT: raw × `bronze_iot_size_ratio` |
| Silver | HSI: cubes/day × `silver_hsi_kb_per_cube`. IoT: raw × `silver_iot_size_ratio` |
| Gold | IoT: sensors × rows/sensor/day × bytes/row. HSI: cubes/day × bytes/record |
| Iceberg objects/day | (1440 ÷ `iceberg_commit_interval_min`) × `iceberg_tables` × `iceberg_objects_per_commit` |
| ML model artifacts | `model_variants` × MB/variant × `model_versions_retained` (fixed, not a rate) |
| ML predictions/day | sensors × predictions/sensor/day + cubes/day × predictions/HSI sample |

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
- `[lakehouse]` and `[ml]` are estimates, not measurements — unlike Kafka/Flink/Prometheus
  (which trace back to hand calculations in the cost-estimate doc), the Silver/Gold row sizes,
  Iceberg commit overhead, and ML model/prediction sizes are reasoned defaults. Revisit them
  once the actual Glue ETL and training pipeline exist. `[lakehouse]`/`[ml]` also aren't counted
  in VM `Fit`, since they're S3/Glue-based, not part of the VM fleet.

## Tests

```bash
python3 -m pytest -q
```
