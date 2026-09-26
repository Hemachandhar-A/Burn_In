"""module_a — Module A: Outlier Detection Ensemble (P3, E2).

Public surface: a single function, detect(), consumed in-process by fusion/ (P5).
No router — this module is never called over HTTP.

Session history:
  P3.0  detect.py — STUB returning correctly-shaped fixed fake data (this session)
  P3.1  detect.py — real z-score, MCD, Isolation Forest (E2 steps 1-3)
  P3.2  detect.py — ECOD + direction-awareness cap (E2 steps 4-6)
  P3.3  detect.py — explainable tags + harness thresholds (E2 steps 7-8)
"""
