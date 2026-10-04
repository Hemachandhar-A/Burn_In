"""Weighted decision matrix for the detection-approach decision (see DECISION_RECORD_DETECTION_APPROACH.md).

Ratings are ORDINAL judgements on a 1-5 scale (5 = best), each justified in the decision record with an evidence tag.
Edit WEIGHTS or RATINGS and re-run:  python decision_matrix.py
"""
OPTIONS = {
    "O1 Fixed delta limit alone":                    None,
    "O2 Dynamic PAT alone":                          None,
    "O3 Previous Module A scoring + Module B":       None,
    "O4 V1F (Module A only)":                        None,
    "O5 System: V1F + Module B + gate (shipped)":    None,
    "O6 Layered: O5 + spec delta guard (unbuilt)":   None,
    "O7 By phase: V1F verdict for finished lots, Module B for unfinished lots (unbuilt)": None,
}
CRITERIA = ["C1 miss protection", "C2 false-alarm burden", "C3 explainability to QA", "C4 drift forecast",
            "C5 robustness to unfamiliar data", "C6 method transparency", "C7 day-one deployability",
            "C8 peer/multivariate premise"]
WEIGHTS = {  # percent, sum 100; rationale in the record
    "base":                  [20, 10, 20, 10, 15, 10, 10, 5],
    "equal":                 [12.5] * 8,
    "detection-heavy":       [35, 20, 10, 5, 10, 5, 10, 5],
    "explainability-heavy":  [15, 5, 35, 10, 10, 10, 10, 5],
    "real-world-heavy":      [15, 5, 15, 5, 30, 10, 15, 5],
    "synthetic score only":  [60, 40, 0, 0, 0, 0, 0, 0],
    "mission (C1>=15, C3>=15) example": [15, 10, 15, 10, 20, 10, 10, 10],
}
RATINGS = {  # order of CRITERIA; rubric and reasons in the decision record. Revised after Session I2b (see record, section 14)
    "O1 Fixed delta limit alone":                  [5, 4, 4, 1, 3, 5, 3, 2],
    "O2 Dynamic PAT alone":                        [2, 5, 4, 1, 4, 5, 5, 3],
    "O3 Previous Module A scoring + Module B":     [4, 1, 3, 3, 3, 2, 2, 5],
    "O4 V1F (Module A only)":                      [4, 3, 4, 1, 3, 3, 3, 4],
    "O5 System: V1F + Module B + gate (shipped)":  [4, 1, 5, 3, 4, 2, 2, 5],
    "O6 Layered: O5 + spec delta guard (unbuilt)": [5, 1, 5, 3, 3, 2, 2, 5],
    "O7 By phase: V1F verdict for finished lots, Module B for unfinished lots (unbuilt)": [4, 3, 5, 3, 4, 2, 2, 5],
}
def total(r, w): return sum(a * b for a, b in zip(r, w)) / 100.0
if __name__ == "__main__":
    for name, w in WEIGHTS.items():
        assert abs(sum(w) - 100) < 1e-9, name
        rows = sorted(((total(r, w), o) for o, r in RATINGS.items()), reverse=True)
        print(f"\n{name}  (weights {w})")
        for s, o in rows: print(f"  {s:5.2f}  {o}")
