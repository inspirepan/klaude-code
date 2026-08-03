from __future__ import annotations

from pathlib import Path

from klaude_code.session.session import Session


def test_headless_meta_round_trip(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home
    session = Session.create(work_dir=tmp_path)
    session.name = "fix-tests"
    session.group = "review"
    session.agent_type = "finder"
    session.spawn_kind = "headless"
    session.approval_policy = "deny"
    session.ensure_meta_exists()

    loaded = Session.load_meta(session.id, work_dir=tmp_path)
    assert loaded.name == "fix-tests"
    assert loaded.group == "review"
    assert loaded.agent_type == "finder"
    assert loaded.spawn_kind == "headless"
    assert loaded.approval_policy == "deny"


def test_interactive_meta_has_no_headless_fields(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home
    session = Session.create(work_dir=tmp_path)
    session.ensure_meta_exists()

    raw = session._store.load_meta(session.id)  # pyright: ignore[reportPrivateUsage]
    assert raw is not None
    for key in ("name", "group", "agent_type", "spawn_kind", "approval_policy"):
        assert key not in raw

    loaded = Session.load_meta(session.id, work_dir=tmp_path)
    assert loaded.spawn_kind is None
    assert loaded.name is None
