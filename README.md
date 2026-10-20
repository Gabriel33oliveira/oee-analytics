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

## Tests

```bash
.venv/Scripts/python -m pytest -q
```
