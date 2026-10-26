"""OEE Analytics: Overall Equipment Effectiveness from manufacturing event logs."""

# Defined before the imports below because report.py imports it from here.
__version__ = "0.1.0"

from oee_analytics.analysis import compare_machines, compare_shifts, downtime_pareto  # noqa: E402
from oee_analytics.generator import GeneratorConfig, generate  # noqa: E402
from oee_analytics.io import load_dataset  # noqa: E402
from oee_analytics.metrics import compute_oee, compute_overall  # noqa: E402
from oee_analytics.report import build_report  # noqa: E402

__all__ = [
    "GeneratorConfig",
    "__version__",
    "build_report",
    "compare_machines",
    "compare_shifts",
    "compute_oee",
    "compute_overall",
    "downtime_pareto",
    "generate",
    "load_dataset",
]
