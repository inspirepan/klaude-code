from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from klaude_code.app.session_index import SessionIndex
from klaude_code.session.session import Session


@pytest.mark.parametrize(
    ("timestamps", "expected_created_at", "expected_updated_at"),
    [
        pytest.param({}, 100.0, 100.0, id="missing"),
        pytest.param({"created_at": 12, "updated_at": 34.5}, 12.0, 34.5, id="numbers"),
        pytest.param({"created_at": "12.5", "updated_at": "34"}, 12.5, 34.0, id="numeric-strings"),
        pytest.param({"created_at": True, "updated_at": False}, 1.0, 0.0, id="booleans"),
        pytest.param({"created_at": 12.5}, 12.5, 12.5, id="missing-updated"),
        pytest.param({"created_at": "invalid", "updated_at": "invalid"}, 100.0, 100.0, id="invalid-strings"),
        pytest.param({"created_at": None, "updated_at": None}, 100.0, 100.0, id="nulls"),
        pytest.param({"created_at": [], "updated_at": {}}, 100.0, 100.0, id="containers"),
        pytest.param({"created_at": "invalid", "updated_at": 34.5}, 100.0, 34.5, id="invalid-created"),
        pytest.param({"created_at": 12.5, "updated_at": "invalid"}, 12.5, 12.5, id="invalid-updated"),
        pytest.param({"created_at": 12.5, "updated_at": None}, 12.5, 12.5, id="null-updated"),
        pytest.param({"created_at": 12.5, "updated_at": []}, 12.5, 12.5, id="container-updated"),
    ],
)
def test_index_and_restored_session_share_timestamp_fallbacks(
    isolated_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    timestamps: dict[str, Any],
    expected_created_at: float,
    expected_updated_at: float,
) -> None:
    monkeypatch.setattr("time.time", lambda: 100.0)
    session_id = "timestamp-fallbacks"
    meta_path = Session.paths(tmp_path).meta_file(session_id)
    meta_path.parent.mkdir(parents=True)
    meta_path.write_text(json.dumps({"work_dir": str(tmp_path), **timestamps}), encoding="utf-8")

    summary = SessionIndex(home=isolated_home).get(session_id)
    restored = Session.load(session_id, work_dir=tmp_path)

    assert summary is not None
    assert summary.created_at == restored.created_at == expected_created_at
    assert summary.updated_at == restored.updated_at == expected_updated_at
