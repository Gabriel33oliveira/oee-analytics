# OEE Analytics

OEE Analytics is a Python library and command-line tool that computes Overall Equipment Effectiveness (OEE) from manufacturing event logs stored as CSV files: machine state changes, good-part counts and scrap counts. A seeded generator simulates a small plant (4 machines, 3 shifts) so you can try everything without real data. On top of the metric engine it builds a downtime Pareto by reason code, ranks shifts and machines side by side, and renders a self-contained HTML report with charts. It runs locally and calls no external services.

Want to see the output first? Open [`examples/sample_report.html`](examples/sample_report.html) in a browser. It was built from the 7-day, seed-42 dataset in [`examples/sample_data/`](examples/sample_data/).

## Overview

OEE answers one question about a machine: of the time it was scheduled to make parts, how much of that time went into good parts made at full speed? A score of 100% means no stops, no slow cycles and no scrap. World-class discrete manufacturing is often quoted at around 85%, and many plants sit between 40% and 60%.

The number is useful because it splits into three factors, and each one points at a different kind of loss:

| Factor | Loss it measures | Typical causes |
| --- | --- | --- |
| Availability | stops | breakdowns, material shortages, changeovers, missing operators |
| Performance | speed | slow cycles, micro-stops, running below the rated rate |
| Quality | defects | scrap and rework |

A plant that knows its availability is the weak factor, and that mechanical failures cause half of the downtime, knows where to spend its next maintenance hour. This project gets you from raw logs to that answer.

## OEE formulas

For each machine, shift or day:

```text
planned time  = total time - PLANNED_STOP time
run time      = RUNNING time
downtime      = DOWN time + IDLE time

availability  = run time / planned time
performance   = sum(ideal cycle time x parts produced) / run time    (capped at 100%)
quality       = good parts / parts produced
OEE           = availability x performance x quality
```

Parts produced is good plus scrap. When you aggregate several machines or shifts, the library sums the times and counts first and then divides, so ratios are never averaged. A zero denominator gives 0.0.

### Worked example

One machine with an ideal cycle time of 30 s runs an 8-hour shift (480 min). It has a 30-minute planned maintenance stop and is down or idle for 60 minutes. It produces 700 parts, 20 of them scrap.

```text
planned time  = 480 - 30          = 450 min
run time      = 450 - 60          = 390 min
availability  = 390 / 450         = 86.7%
performance   = 700 x 30 s / 60   = 350 min of ideal time
              = 350 / 390         = 89.7%
quality       = 680 / 700         = 97.1%
OEE           = 0.867 x 0.897 x 0.971 = 75.6%
```

As a check, OEE also equals good parts times ideal cycle time over planned time: 680 x 30 s = 340 min, and 340 / 450 = 75.6%.

## Input formats

A dataset is a directory with three CSV files. Timestamps are ISO 8601 (for example `2026-01-05T06:00:00`).

### `machines.csv`

| Column | Type | Rules |
| --- | --- | --- |
| `machine_id` | text | unique, required |
| `name` | text | display name |
| `ideal_cycle_time_s` | number | seconds per part at rated speed, > 0 |

```csv
machine_id,name,ideal_cycle_time_s
M1,Stamping Press,30
M2,CNC Lathe,45
```

### `states.csv`

| Column | Type | Rules |
| --- | --- | --- |
| `timestamp` | ISO 8601 | when the machine entered the state |
| `machine_id` | text | must exist in `machines.csv` |
| `state` | text | `RUNNING`, `IDLE`, `DOWN` or `PLANNED_STOP` |
| `reason_code` | text | required for `DOWN`, empty for every other state |

Each row is a state change. The state lasts until the next row for the same machine.

```csv
timestamp,machine_id,state,reason_code
2026-01-05T06:00:00,M1,RUNNING,
2026-01-05T06:31:00,M1,IDLE,
2026-01-05T08:00:00,M1,PLANNED_STOP,
2026-01-05T23:18:00,M1,DOWN,CHANGEOVER
```

### `production.csv`

| Column | Type | Rules |
| --- | --- | --- |
| `timestamp` | ISO 8601 | end of the counting interval |
| `machine_id` | text | must exist in `machines.csv` |
| `good_count` | integer | >= 0 |
| `scrap_count` | integer | >= 0 |

```csv
timestamp,machine_id,good_count,scrap_count
2026-01-05T06:15:00,M1,28,0
2026-01-05T06:30:00,M1,22,1
```

If a file breaks these rules, the loaders raise `DataValidationError` (a subclass of `ValueError`) with the file name, the CSV line number and the problem. The CLI prints the same message as `oee: error: ...` on stderr and exits with code 2.

## Setup

You need Python 3.11 or newer.

Windows (PowerShell or cmd):

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\oee --help
```

macOS and Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/oee --help
```

`pip install -e ".[dev]"` installs the package in editable mode with pytest. The quotes keep zsh from expanding the brackets. `requirements.txt` pins the same dependencies if you prefer `pip install -r requirements.txt`. After activating the virtual environment (`.venv\Scripts\activate` or `source .venv/bin/activate`) you can type `oee` directly, as in the examples below.

## CLI usage

```text
oee generate --out DIR [--days 7] [--seed 42] [--start 2026-01-05]
oee summary DATA_DIR [--by machine|shift|date|machine,shift]
oee pareto DATA_DIR [--machine ID] [--shift NAME] [--top N]
oee compare DATA_DIR --by machine|shift
oee report DATA_DIR --out FILE [--title TEXT]
```

Every command except `report` accepts `--format table|csv|json` (default `table`). Tables show availability, performance, quality and OEE as percentages with one decimal; CSV and JSON keep the raw 0-1 ratios. The outputs below come from the seed-42, 7-day dataset, which is byte-for-byte the same as `examples/sample_data/`.

### `generate`

Writes a synthetic dataset. The simulation starts at the first shift (06:00) of `--start`.

```console
$ oee generate --out data/plant --days 7 --seed 42
file                      rows
------------------------  ----
data/plant/machines.csv      4
data/plant/states.csv      834
data/plant/production.csv  2357
```

### `summary`

OEE grouped by machine (the default), shift, date or machine and shift.

```console
$ oee summary data/plant
machine_id  planned_time_s  run_time_s  downtime_s  total_count  good_count  scrap_count  availability  performance  quality    oee
----------  --------------  ----------  ----------  -----------  ----------  -----------  ------------  -----------  -------  -----
M1                592200.0    448620.0    143580.0        12591       12387          204         75.8%        84.2%    98.4%  62.8%
M2                592200.0    435720.0    156480.0         8083        7861          222         73.6%        83.5%    97.3%  59.7%
M3                592200.0    452400.0    139800.0         6204        6083          121         76.4%        82.3%    98.0%  61.6%
M4                592200.0    472380.0    119820.0         4241        4159           82         79.8%        80.8%    98.1%  63.2%
```

```console
$ oee summary data/plant --by shift --format csv
shift,planned_time_s,run_time_s,downtime_s,total_count,good_count,scrap_count,availability,performance,quality,oee
A,781200.0,616320.0,164880.0,10481,10335,146,0.7889400921658987,0.8250340732087228,0.9860700314855453,0.6418354070147563
B,793800.0,619980.0,173820.0,10934,10758,176,0.7810279667422525,0.8320187747991871,0.9839034205231388,0.6393698928263458
C,793800.0,572820.0,220980.0,9704,9397,307,0.7216175359032502,0.8223787577249397,0.968363561417972,0.5746685118354385
```

### `pareto`

Downtime by reason code, largest first, with each reason's share and the running total. `--machine` and `--shift` filter the DOWN intervals before ranking.

```console
$ oee pareto data/plant --top 3
reason_code         events  downtime_min  share_pct  cumulative_pct
------------------  ------  ------------  ---------  --------------
MECHANICAL_FAILURE      91        4042.0       52.8            52.8
MATERIAL_SHORTAGE       51        1098.0       14.3            67.1
CHANGEOVER              38         951.0       12.4            79.6
```

```console
$ oee pareto data/plant --machine M1 --shift C --format json
[
  {
    "reason_code": "MECHANICAL_FAILURE",
    "events": 12,
    "downtime_min": 714.0,
    "share_pct": 67.6777251185,
    "cumulative_pct": 67.6777251185
  },
  {
    "reason_code": "CHANGEOVER",
    "events": 3,
    "downtime_min": 131.0,
    "share_pct": 12.4170616114,
    "cumulative_pct": 80.0947867299
  },
  ...
]
```

### `compare`

Ranks machines or shifts by OEE. `rank` 1 is the best, and `oee_delta_pts` is the group's OEE minus the plant OEE (61.9% here) in percentage points.

```console
$ oee compare data/plant --by machine
machine_id  planned_time_s  run_time_s  downtime_s  total_count  good_count  scrap_count  availability  performance  quality    oee  rank  oee_delta_pts
----------  --------------  ----------  ----------  -----------  ----------  -----------  ------------  -----------  -------  -----  ----  -------------
M4                592200.0    472380.0    119820.0         4241        4159           82         79.8%        80.8%    98.1%  63.2%     1           +1.4
M1                592200.0    448620.0    143580.0        12591       12387          204         75.8%        84.2%    98.4%  62.8%     2           +0.9
M3                592200.0    452400.0    139800.0         6204        6083          121         76.4%        82.3%    98.0%  61.6%     3           -0.2
M2                592200.0    435720.0    156480.0         8083        7861          222         73.6%        83.5%    97.3%  59.7%     4           -2.1
```

```console
$ oee compare data/plant --by shift
shift  planned_time_s  run_time_s  downtime_s  total_count  good_count  scrap_count  availability  performance  quality    oee  rank  oee_delta_pts
-----  --------------  ----------  ----------  -----------  ----------  -----------  ------------  -----------  -------  -----  ----  -------------
A            781200.0    616320.0    164880.0        10481       10335          146         78.9%        82.5%    98.6%  64.2%     1           +2.3
B            793800.0    619980.0    173820.0        10934       10758          176         78.1%        83.2%    98.4%  63.9%     2           +2.1
C            793800.0    572820.0    220980.0         9704        9397          307         72.2%        82.2%    96.8%  57.5%     3           -4.4
```

The night shift (C) loses about 4 points of OEE, mostly through availability and scrap. The generator builds that in on purpose so the comparison has something to find.

### `report`

Writes one HTML file with inline CSS and inline SVG charts. It loads nothing from the network, so you can email it or open it offline.

```console
$ oee report data/plant --out report.html --title "Week 2 OEE"
file         bytes
-----------  -----
report.html  72831
```

The report has KPI cards for plant OEE and its three factors, four charts (factors per machine, factors per shift, the downtime Pareto with its cumulative line and 80% mark, and daily plant OEE), and tables for machines, shifts and downtime reasons.

## Python API

The main functions are re-exported from the package root:

```python
from oee_analytics import (
    GeneratorConfig,
    build_report,
    compare_machines,
    compare_shifts,
    compute_oee,
    compute_overall,
    downtime_pareto,
    generate,
    load_dataset,
)

ds = load_dataset("examples/sample_data")      # validated Dataset

compute_oee(ds)                                 # DataFrame, one row per machine
compute_oee(ds, group_by=("machine_id", "shift"))  # any mix of machine_id, shift, date
plant = compute_overall(ds)                     # OeeResult dataclass for the whole plant
print(f"Plant OEE: {plant.oee:.1%}")            # Plant OEE: 61.9%

downtime_pareto(ds, machine_id="M1", shift="C")
compare_shifts(ds)
compare_machines(ds)

html = build_report(ds, title="OEE Report")     # complete HTML document as a string

synthetic = generate(GeneratorConfig(days=3, seed=7))  # Dataset built in memory
```

To write files, use the helpers in the submodules:

```python
from oee_analytics import GeneratorConfig, compare_machines, generate, load_dataset
from oee_analytics.analysis import format_table
from oee_analytics.generator import write_dataset
from oee_analytics.report import write_report

write_dataset(generate(GeneratorConfig(days=7, seed=42)), "data/plant")
ds = load_dataset("data/plant")
print(format_table(compare_machines(ds)))       # same table the CLI prints
write_report(ds, "report.html", title="OEE Report")
```

All metric functions accept `shifts=` (a sequence of `Shift` objects, default A 06-14, B 14-22, C 22-06) and `end=`, the time that closes the last state of each machine. `end` defaults to the latest timestamp in the dataset; pass `GeneratorConfig.end` to cover the full simulated period.

## Architecture

```text
generator ─┐
           v
       CSV files ──> io ──> Dataset ──> metrics ──> analysis ──> charts ──> report ──> HTML
                                           │            │                     ^
                                           └────────────┴─────────────────────┘
cli: parses arguments, calls one of these stages and prints a table, CSV or JSON
```

| Module | Role |
| --- | --- |
| `models.py` | `Machine`, `MachineState` and `Shift` value types with validation. |
| `shifts.py` | Shift calendar: finds the shift for a timestamp and splits a time range at shift boundaries, including the overnight shift. |
| `io.py` | Reads and validates the three CSV files into a `Dataset` (a list of machines plus two pandas DataFrames). |
| `generator.py` | Seeded simulation of 4 machines over 3 shifts. It writes CSVs that pass through `io` validation, so generated data always loads. |
| `metrics.py` | Turns state changes into intervals, splits them by shift, assigns production rows to shifts and computes OEE for any grouping. |
| `analysis.py` | Downtime Pareto, shift and machine comparisons, and the plain-text table formatter. |
| `charts.py` | Matplotlib (Agg backend) charts returned as inline `<svg>` strings. |
| `report.py` | Renders the Jinja2 template in `templates/report.html.j2` with KPIs, charts and tables. |
| `cli.py` | `argparse` front end; each subcommand loads a dataset, calls the library and prints a table, CSV or JSON. |

Data flows one way. `io` produces a `Dataset`, `metrics` and `analysis` turn it into DataFrames, and `charts` and `report` turn those into SVG and HTML. The CLI only parses arguments and formats results, so anything it does is also available from Python.

## Assumptions and limitations

- The project ships with synthetic data only. The generator's reason codes, rates and shift effects are invented to make the analysis interesting and are not taken from any real plant.
- `states.csv` uses state-change semantics. A state lasts until the next row for the same machine, and the last state lasts until `end` (by default the latest timestamp in the dataset). Gaps are not detected: if a machine has no new row for a day, it stays in its last state for that day.
- IDLE time counts as downtime and lowers availability. Only `PLANNED_STOP` is excluded from planned time. If your plant treats idle as planned, record it as `PLANNED_STOP`.
- Performance is capped at 100%. Without the cap, an ideal cycle time set longer than the machine really needs would push OEE above 100%. The cap hides that error, so a performance of exactly 100% usually means the cycle time in `machines.csv` needs checking.
- Production rows are assigned to a shift by their timestamp, which marks the end of the counting interval. An interval that straddles a shift change is counted entirely in the later shift.
- For the overnight shift, `date` is the day the shift started, so 02:00 on Tuesday belongs to Monday's shift C.
- Timestamps are treated as naive local time. Time zones and daylight-saving changes are not handled.
- Everything is computed in memory with pandas, which is fine for months of data from a handful of machines but is not designed for plant-wide historian exports.

## Testing

```bash
.venv/Scripts/python -m pytest -q
```

On macOS and Linux use `.venv/bin/python -m pytest -q`. The suite covers the loaders, generator, metrics, analysis, charts, report and CLI. `tests/test_end_to_end.py` runs the whole pipeline through `oee_analytics.cli.main` (generate, summary, pareto, compare, report) and checks that the committed files in `examples/` match what `examples/generate_sample.py` produces. `tests/test_readme.py` runs every `oee` command and Python block in this README.

To rebuild the sample after changing the generator or report:

```bash
python examples/generate_sample.py
```

## License

MIT. See [LICENSE](LICENSE).
