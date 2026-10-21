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

## Tests

```bash
.venv/Scripts/python -m pytest -q
```
