# OEE Analytics

Python library and CLI that computes OEE, downtime Paretos and shift comparisons from manufacturing event logs.

OEE Analytics is a Python library and command-line tool that computes Overall Equipment Effectiveness (Availability × Performance × Quality) from manufacturing event logs stored as CSV files: machine state changes, good-part counts and scrap counts. It includes a seeded synthetic data generator that simulates a small plant with 4 machines running 3 shifts. On top of that data it builds a downtime Pareto by reason code and side-by-side comparisons of shifts and machines, and it renders a self-contained HTML report with charts. Everything runs locally on synthetic data, with no external services, so the analysis is easy to reproduce, test and extend.

## Setup

Requires Python 3.11 or newer.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # or: pip install -e .[dev]
```

## Usage

```bash
oee generate --out data/plant [--days 7] [--seed 42] [--start 2026-01-05]
oee summary data/plant [--by machine|shift|date|machine,shift]
oee pareto data/plant [--machine M1] [--shift C] [--top 3]
oee compare data/plant --by machine|shift
oee report data/plant --out report.html [--title TEXT]
```

Every command except `report` accepts `--format table|csv|json` (default `table`). In tables, availability, performance, quality and OEE are shown as percentages with one decimal. If a CSV file fails validation, the command prints a one-line `oee: error: ...` message to stderr and exits with code 2.

## Input data

A dataset is a directory with three CSV files:

| File | Columns | Rules |
| --- | --- | --- |
| `machines.csv` | `machine_id,name,ideal_cycle_time_s` | unique ids, cycle time > 0 |
| `states.csv` | `timestamp,machine_id,state,reason_code` | ISO 8601 timestamps; `state` is one of `RUNNING`, `IDLE`, `DOWN`, `PLANNED_STOP`; `reason_code` is required for `DOWN` and must be empty otherwise. Each row lasts until the next row for the same machine. |
| `production.csv` | `timestamp,machine_id,good_count,scrap_count` | ISO 8601 timestamps; counts are non-negative integers |

Every `machine_id` in `states.csv` and `production.csv` must also appear in `machines.csv`.

```python
from oee_analytics.io import load_dataset

ds = load_dataset("tests/fixtures/valid")
ds.machines, ds.states, ds.production
```

If a file breaks these rules, the loaders raise `DataValidationError` (a `ValueError`). The message names the file, the row number and the problem.

## Synthetic data

`oee_analytics.generator` simulates a plant with 4 machines (M1-M4, ideal cycle times of 30, 45, 60 and 90 s) running the three default shifts. Output depends only on the config, so a given seed always produces the same CSV bytes.

```python
import datetime
from oee_analytics.generator import GeneratorConfig, generate, write_dataset

config = GeneratorConfig(start=datetime.datetime(2026, 1, 5, 6, 0), days=7, seed=42)
write_dataset(generate(config), "data/plant")
```

Each machine switches between RUNNING, IDLE and DOWN. DOWN events get a weighted reason code: `MECHANICAL_FAILURE`, `MATERIAL_SHORTAGE`, `CHANGEOVER`, `NO_OPERATOR`, `QUALITY_HOLD` or `ELECTRICAL_FAULT`. Every machine also has a 30-minute `PLANNED_STOP` each day. Machines differ a little in reliability and scrap rate, and the night shift (C) breaks down more often and produces more scrap. Production is reported at most every 15 minutes of RUNNING time, at 75-98% of the ideal rate. The last state of each machine lasts until `config.end`.

## OEE metrics

`oee_analytics.metrics` computes OEE per machine, shift and day:

```python
from oee_analytics.metrics import compute_oee, compute_overall

compute_oee(ds)                                   # one row per machine
compute_oee(ds, group_by=("machine_id", "shift"))  # any mix of machine_id, shift, date
compute_oee(ds, group_by=())                       # whole plant
compute_overall(ds)                                # plant-level OeeResult
```

- planned time = total time minus `PLANNED_STOP` time
- run time = `RUNNING` time; downtime = `DOWN` + `IDLE` time
- availability = run time / planned time
- performance = Σ(ideal cycle time × parts) / run time, capped at 1.0
- quality = good / total parts; OEE = availability × performance × quality

Groups are aggregated by summing times and counts, so ratios are never averaged. A zero denominator gives 0.0. States are split at shift boundaries, and production rows are assigned to a shift by timestamp. For the overnight shift, `date` is the day the shift started. The last state of each machine lasts until `end`, which defaults to the latest timestamp in the dataset. Pass `end=config.end` to cover the whole generated period.

## Downtime Pareto and comparisons

`oee_analytics.analysis` builds on the metric engine:

```python
from oee_analytics.analysis import compare_machines, compare_shifts, downtime_pareto, format_table

downtime_pareto(ds)                      # reason_code, events, downtime_min, share_pct, cumulative_pct
downtime_pareto(ds, machine_id="M1", shift="C")
compare_shifts(ds)                       # OEE per shift plus rank and oee_delta_pts
print(format_table(compare_machines(ds)))
```

The Pareto uses DOWN intervals only, split at shift boundaries, and sorts reasons by downtime, largest first. `events` counts DOWN intervals, so one that spans a shift change counts once (or once in each shift when you filter by shift). In the comparisons, `rank` 1 is the best OEE, and `oee_delta_pts` is the group OEE minus the plant OEE, in percentage points.

## HTML report

`oee_analytics.report` renders a single HTML file with inline CSS and inline SVG charts, so it opens offline and loads nothing from the network:

```python
from oee_analytics.report import build_report, write_report

html = build_report(ds, title="OEE Report")
write_report(ds, "report.html")
```

The report has a header with the data period and generation time, KPIs for plant OEE, availability, performance and quality, four charts (OEE components per machine and per shift, the downtime Pareto with its cumulative line and 80% mark, and daily plant OEE), and tables for machines, shifts and downtime reasons. Percentages have one decimal and durations are in minutes. The charts come from `oee_analytics.charts`, which uses matplotlib's Agg backend and returns each chart as an `<svg>` string. The Jinja2 template ships as package data (`oee_analytics/templates/report.html.j2`) and is loaded with `importlib.resources`.

## Tests

```bash
.venv/Scripts/python -m pytest -q
```
