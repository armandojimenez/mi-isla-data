import datetime as dt
import json

import pytest

from snapshot import build
from snapshot.build import SnapshotError, _check_run_age, publish
from snapshot.openmeteo import Run

NOW = dt.datetime(2026, 10, 4, 3, 41, tzinfo=dt.timezone.utc)


def _run(hours_old: float) -> Run:
    return Run(
        model="cams_global",
        path="openmeteo/data_run/cams_global/x",
        reference=NOW - dt.timedelta(hours=hours_old),
    )


def test_a_current_run_passes_and_a_stalled_one_is_refused():
    _check_run_age(_run(14), NOW, 30)
    with pytest.raises(SnapshotError, match="31 h old"):
        _check_run_age(_run(31), NOW, 30)


def _doc(kind: str) -> dict:
    return {"v": build.SCHEMA_VERSION, "kind": kind, "run": "2026-10-03T12:00Z"}


def _ok(kind):
    return (kind, lambda fs, now: _doc(kind), lambda doc, now: None)


def _broken(kind):
    def fail(fs, now):
        raise SnapshotError(f"{kind} model is down")

    return (kind, fail, lambda doc, now: None)


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("no network in tests")

    monkeypatch.setattr(build.urllib.request, "urlopen", refuse)


def test_every_domain_built_means_nothing_missing(tmp_path, no_network):
    status, missing = publish(None, tmp_path, NOW, [_ok("air"), _ok("marine")])
    assert missing == []
    assert status["domains"]["air"] == {"ok": True, "run": "2026-10-03T12:00Z"}
    assert json.loads((tmp_path / "v1" / "marine.json").read_text())["kind"] == "marine"


def test_a_failed_domain_keeps_the_published_file(tmp_path, no_network):
    previous = tmp_path / "previous"
    (previous / "v1").mkdir(parents=True)
    old = json.dumps({**_doc("marine"), "generatedAt": "2026-10-04T00:41:00Z"})
    (previous / "v1" / "marine.json").write_text(old)

    out = tmp_path / "site"
    status, missing = publish(None, out, NOW, [_ok("air"), _broken("marine")], previous=previous)
    assert missing == []
    assert status["domains"]["marine"]["ok"] is False
    assert status["domains"]["marine"]["kept"] is True
    assert (out / "v1" / "marine.json").read_text() == old


def test_a_failed_domain_with_nothing_to_keep_blocks_publishing(tmp_path, no_network):
    # Publishing would take marine.json down for every reader: main() fails
    # on `missing` instead, and the live site stays as it is.
    status, missing = publish(None, tmp_path, NOW, [_ok("air"), _broken("marine")])
    assert missing == ["marine"]
    assert status["domains"]["marine"]["kept"] is False


def test_a_kept_file_must_be_the_same_kind_and_schema(tmp_path, no_network):
    previous = tmp_path / "previous"
    (previous / "v1").mkdir(parents=True)
    (previous / "v1" / "air.json").write_text(json.dumps({"v": 99, "kind": "air"}))
    _, missing = publish(None, tmp_path / "site", NOW, [_broken("air")], previous=previous)
    assert missing == ["air"]


def test_rebuilding_one_domain_carries_the_other_over(tmp_path, no_network):
    previous = tmp_path / "previous"
    (previous / "v1").mkdir(parents=True)
    (previous / "v1" / "marine.json").write_text(json.dumps(_doc("marine")))
    out = tmp_path / "site"
    _, missing = publish(
        None, out, NOW, [_ok("air"), _ok("marine")], previous=previous, only="air"
    )
    assert missing == []
    assert (out / "v1" / "marine.json").is_file()
