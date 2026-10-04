"""fusion/settings.py - the Module B finished-lot role switch (session I3, docs/MODULE_B_ROLE_EXPERIMENT.md).

`MODULE_B_FINISHED_LOT_ROLE` says what Module B's forecast does to a part's verdict when the lot is COMPLETE (all four checkpoints measured).
It never applies to an in-progress lot, where Module B is the only screen and behaves exactly as before.

    current   B REJECT when the forecast exceeds the safety slope (the behaviour up to demo-v2)
    tiered    B REJECT only when the interval's lower bound also exceeds the slope; B REVIEW when only the point forecast does
    advisory  (default from demo-v2.1) B never changes a finished lot's verdict; its forecast is shown on the part as information
    off       Module A alone decides a finished lot's part verdict (same verdicts as advisory; no forecast note)

The value is read on every call (not at import), like MODULE_A_SCORING.
"""
from __future__ import annotations

import os

MODULE_B_ROLES = ("current", "tiered", "advisory", "off")
DEFAULT_MODULE_B_ROLE = "advisory"


def module_b_finished_lot_role() -> str:
    value = os.environ.get("MODULE_B_FINISHED_LOT_ROLE", "").strip().lower()
    if not value:
        return DEFAULT_MODULE_B_ROLE
    if value not in MODULE_B_ROLES:
        raise ValueError(f"MODULE_B_FINISHED_LOT_ROLE must be one of {MODULE_B_ROLES}, got {value!r}")
    return value
