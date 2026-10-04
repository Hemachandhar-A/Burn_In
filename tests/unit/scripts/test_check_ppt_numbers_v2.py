"""scripts/check_ppt_numbers.py prints the demo-v2 numbers (absolute scoring) straight from the committed tables."""
from scripts import check_ppt_numbers as c


def test_v2_section_prints_the_numbers_used_in_ppt_numbers(capsys):
    c.print_v2()
    out = capsys.readouterr().out
    for needle in ("V1F REVIEW", "dynamic_pat cost-tuned", "fixed_delta cost-tuned", "S-new (WATCH+REJECT)",
                   "S-old (WATCH+REJECT)", "G_flip", "T1", "T2", "clean-lot flag rate by lot size", "sweep"):
        assert needle in out, needle
    assert "0.082" in out and "0.239" in out          # Module A alone: V1F cost 0.082 against the previous scoring 0.239
