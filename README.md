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
oee --version
```

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

## Tests

```bash
.venv/Scripts/python -m pytest -q
```
