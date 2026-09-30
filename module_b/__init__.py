"""Module B - drift predictor and calibrated safety slope (essential-features.md E3).

No router: fusion/pipeline.py (P5) calls `predict` in-process (IMPLEMENTATION_PLAN.md Part 5.7).
"""

from module_b.predictor import predict
from module_b.stub import STUB_RESULTS

__all__ = ["STUB_RESULTS", "predict"]
