"""scripts/make_demo_csvs.py: deterministic (byte-identical on every run), right checkpoints in each file, and the
files ingest through the real parser."""
from scripts import make_demo_csvs as m


def test_two_runs_are_byte_identical(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    m.write_all(a)
    m.write_all(b)
    for name in m.FILES:
        assert (a / name).read_bytes() == (b / name).read_bytes()


def test_each_file_has_only_its_checkpoints_and_full_is_the_union(tmp_path):
    m.write_all(tmp_path)
    hours = {}
    for name in m.FILES:
        rows = (tmp_path / name).read_text().splitlines()
        assert rows[0] == "component_id,parameter,checkpoint_hour,value,unit"
        hours[name] = {int(r.split(",")[2]) for r in rows[1:]}
        assert hours[name] == set(m.FILES[name])
    body = lambda n: set((tmp_path / n).read_text().splitlines()[1:])
    assert body("full_lot.csv") == body("live_0h_24h.csv") | body("live_96h.csv") | body("live_168h.csv")


def test_committed_files_match_the_generator():
    committed = m.OUT_DIR
    for name, hours in m.FILES.items():
        assert (committed / name).read_bytes() == m.csv_text(m.live_readings(), hours).encode()


def test_files_parse_through_the_real_ingestion_parser(tmp_path):
    from ingestion.parsing import parse_lot_csv

    m.write_all(tmp_path)
    readings = parse_lot_csv((tmp_path / "full_lot.csv").read_bytes(), lot_id="X", **m.LIVE_META)
    assert len(readings) == 924
