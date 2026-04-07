import asyncio
from pathlib import Path
from typing import ClassVar

import pytest

import klaude_code.agent.attachments as attachments
from klaude_code.agent.attachments import get_skills_from_user_input
from klaude_code.protocol import message, model
from klaude_code.session.session import Session
from klaude_code.skill.loader import Skill, get_candidate_skill_dirs_for_anchor
from klaude_code.tool.file._utils import hash_text_sha256


def _arun(coro):  # type: ignore
    return asyncio.run(coro)  # type: ignore


def _build_session_with_user_text(text: str) -> Session:
    session = Session(work_dir=Path.cwd())
    session.conversation_history.append(message.UserMessage(parts=message.text_parts_from_str(text)))
    return session


def _make_skill(name: str, *, root: Path, location: str = "system", description: str | None = None) -> Skill:
    skill_dir = root / name
    return Skill(
        name=name,
        description=description or f"{name} skill",
        location=location,
        skill_path=skill_dir / "SKILL.md",
        base_dir=skill_dir,
    )


def test_get_skill_from_slash_token() -> None:
    session = _build_session_with_user_text("please /skill:commit now")
    assert get_skills_from_user_input(session) == ["commit"]


def test_get_skill_from_double_slash_token() -> None:
    session = _build_session_with_user_text("please //skill:commit now")
    assert get_skills_from_user_input(session) == ["commit"]


def test_get_skill_ignores_path_like_slash_token() -> None:
    session = _build_session_with_user_text("/Users/root/code/project")
    assert get_skills_from_user_input(session) == []


def test_get_skill_ignores_command_name_for_slash_token() -> None:
    session = _build_session_with_user_text("/model")
    assert get_skills_from_user_input(session) == []


def test_get_skill_with_prefix_can_match_command_name() -> None:
    session = _build_session_with_user_text("/skill:model")
    assert get_skills_from_user_input(session) == ["model"]


def test_get_skill_ignores_legacy_dollar_token() -> None:
    session = _build_session_with_user_text("please $commit now")
    assert get_skills_from_user_input(session) == []


def test_get_multiple_skills_from_user_input() -> None:
    session = _build_session_with_user_text("//skill:commit  //skill:submit-pr")
    assert get_skills_from_user_input(session) == ["commit", "submit-pr"]


def test_get_skills_deduplicates() -> None:
    session = _build_session_with_user_text("/skill:commit /skill:commit")
    assert get_skills_from_user_input(session) == ["commit"]


def test_skill_attachment_tracks_skill_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skill_dir = tmp_path / "demo-skill"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_content = "# Demo Skill\n\nDo something useful.\n"
    skill_path.write_text(skill_content, encoding="utf-8")

    skill = Skill(
        name="demo",
        description="demo skill",
        location="project",
        skill_path=skill_path,
        base_dir=skill_dir,
    )

    def _mock_get_skill(_: str) -> Skill | None:
        return skill

    monkeypatch.setattr(attachments, "get_skill", _mock_get_skill)

    session = _build_session_with_user_text("/skill:demo")
    attachment = _arun(attachments.skill_attachment(session))

    assert attachment is not None
    tracked = session.file_tracker[str(skill_path)]
    assert tracked.content_sha256 == hash_text_sha256(skill_content)
    assert tracked.is_memory is False


def test_skill_attachment_loads_multiple_skills(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skills: dict[str, Skill] = {}
    for name in ("alpha", "beta"):
        skill_dir = tmp_path / name
        skill_dir.mkdir(parents=True)
        skill_path = skill_dir / "SKILL.md"
        skill_path.write_text(f"# {name} skill\n", encoding="utf-8")
        skills[name] = Skill(
            name=name,
            description=f"{name} skill",
            location="project",
            skill_path=skill_path,
            base_dir=skill_dir,
        )

    def _mock_get_skill(name: str) -> Skill | None:
        return skills.get(name)

    monkeypatch.setattr(attachments, "get_skill", _mock_get_skill)

    session = _build_session_with_user_text("//skill:alpha //skill:beta")
    attachment = _arun(attachments.skill_attachment(session))

    assert attachment is not None
    assert attachment.ui_extra is not None
    activated = [item for item in attachment.ui_extra.items if isinstance(item, model.SkillActivatedUIItem)]
    assert [item.name for item in activated] == ["alpha", "beta"]

    text = message.join_text_parts(attachment.parts)
    assert "alpha" in text
    assert "beta" in text

    assert str(skills["alpha"].skill_path) in session.file_tracker
    assert str(skills["beta"].skill_path) in session.file_tracker


def test_available_skills_attachment_injects_listing_once_per_compaction_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from klaude_code.agent.task import _reset_attachment_loaded_flags  # pyright: ignore[reportPrivateUsage]

    skills = [
        _make_skill("commit", root=tmp_path, location="system"),
        _make_skill("submit-pr", root=tmp_path, location="user"),
    ]
    monkeypatch.setattr(attachments, "_get_available_skills_for_session", lambda _session: skills)  # pyright: ignore[reportUnknownArgumentType,reportUnknownLambdaType]

    session = Session(work_dir=tmp_path)
    session.conversation_history.append(message.UserMessage(parts=message.text_parts_from_str("help")))

    first_attachment = _arun(attachments.available_skills_attachment(session))
    assert first_attachment is not None
    assert first_attachment.attachment_position == "prepend"
    assert first_attachment.ui_extra is not None

    listing = [item for item in first_attachment.ui_extra.items if isinstance(item, model.SkillListingUIItem)]
    assert listing == [model.SkillListingUIItem(names=["submit-pr", "commit"])]

    first_text = message.join_text_parts(first_attachment.parts)
    assert "# Skills" in first_text
    assert "<available_skills>" in first_text
    assert "<name>submit-pr</name>" in first_text
    assert "<name>commit</name>" in first_text
    assert any(status.is_skill_listing for status in session.file_tracker.values())

    assert _arun(attachments.available_skills_attachment(session)) is None

    _reset_attachment_loaded_flags(session.file_tracker)

    second_attachment = _arun(attachments.available_skills_attachment(session))
    assert second_attachment is not None
    assert "<available_skills>" in message.join_text_parts(second_attachment.parts)


def test_last_path_skill_attachment_discovers_nested_project_skill(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    target_file = work_dir / "src" / "feature" / "app.py"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("print('hello')\n", encoding="utf-8")

    skill_dir = work_dir / "src" / ".claude" / "skills" / "local-skill"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text("---\nname: local-skill\ndescription: nested skill\n---\n# Local skill\n", encoding="utf-8")

    session = Session(work_dir=work_dir)
    session.file_tracker[str(target_file.resolve())] = model.FileStatus(
        mtime=target_file.stat().st_mtime,
        content_sha256=hash_text_sha256(target_file.read_text(encoding="utf-8")),
    )

    attachment = _arun(attachments.last_path_skill_attachment(session))

    assert attachment is not None
    assert attachment.ui_extra is not None
    discovered = [item for item in attachment.ui_extra.items if isinstance(item, model.SkillDiscoveredUIItem)]
    assert [item.name for item in discovered] == ["local-skill"]

    text = message.join_text_parts(attachment.parts)
    assert "<available_skills>" in text
    assert "<name>local-skill</name>" in text
    assert "<description>nested skill</description>" in text
    assert "# Local skill" not in text

    tracked = session.file_tracker[str(skill_path.resolve())]
    assert tracked.is_skill is True
    assert tracked.content_sha256 == hash_text_sha256(skill_path.read_text(encoding="utf-8"))


def test_last_path_skill_attachment_same_directory_second_file_does_not_repeat(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    target_dir = work_dir / "a" / "b" / "c"
    target_dir.mkdir(parents=True)
    file1 = target_dir / "file1.py"
    file2 = target_dir / "file2.py"
    file1.write_text("print('file1')\n", encoding="utf-8")
    file2.write_text("print('file2')\n", encoding="utf-8")

    skill_dir = target_dir / ".agents" / "skills" / "build"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text("---\nname: build\ndescription: build skill\n---\n# Build\n", encoding="utf-8")

    session = Session(work_dir=work_dir)
    session.file_tracker[str(file1.resolve())] = model.FileStatus(
        mtime=file1.stat().st_mtime,
        content_sha256=hash_text_sha256(file1.read_text(encoding="utf-8")),
    )

    first_attachment = _arun(attachments.last_path_skill_attachment(session))
    assert first_attachment is not None
    first_text = message.join_text_parts(first_attachment.parts)
    assert "<name>build</name>" in first_text

    session.file_tracker[str(file2.resolve())] = model.FileStatus(
        mtime=file2.stat().st_mtime,
        content_sha256=hash_text_sha256(file2.read_text(encoding="utf-8")),
    )

    assert _arun(attachments.last_path_skill_attachment(session)) is None
    assert str(skill_path.resolve()) in session.file_tracker
    tracked = session.file_tracker[str(skill_path.resolve())]
    assert tracked.is_skill is True
    assert tracked.skill_attachment_source == "dynamic"


def test_last_path_skill_attachment_prefers_deeper_skill_with_same_name(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    target_file = work_dir / "apps" / "service" / "handlers" / "main.py"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("print('hello')\n", encoding="utf-8")

    shallow_skill = work_dir / "apps" / ".claude" / "skills" / "shared-skill" / "SKILL.md"
    shallow_skill.parent.mkdir(parents=True)
    shallow_skill.write_text(
        "---\nname: shared-skill\ndescription: shallow\n---\n# Shallow\n",
        encoding="utf-8",
    )

    deep_skill = work_dir / "apps" / "service" / ".claude" / "skills" / "shared-skill" / "SKILL.md"
    deep_skill.parent.mkdir(parents=True)
    deep_skill.write_text(
        "---\nname: shared-skill\ndescription: deep\n---\n# Deep\n",
        encoding="utf-8",
    )

    session = Session(work_dir=work_dir)
    session.file_tracker[str(target_file.resolve())] = model.FileStatus(
        mtime=target_file.stat().st_mtime,
        content_sha256=hash_text_sha256(target_file.read_text(encoding="utf-8")),
    )

    attachment = _arun(attachments.last_path_skill_attachment(session))

    assert attachment is not None
    text = message.join_text_parts(attachment.parts)
    assert "<description>deep</description>" in text
    assert "<description>shallow</description>" not in text
    assert "# Deep" not in text


def test_last_path_skill_attachment_reloads_when_skill_changes(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    target_file = work_dir / "pkg" / "module" / "code.py"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("print('hello')\n", encoding="utf-8")

    skill_dir = work_dir / "pkg" / ".agents" / "skills" / "refresh-skill"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text("---\nname: refresh-skill\ndescription: v1\n---\nversion one\n", encoding="utf-8")

    session = Session(work_dir=work_dir)
    session.file_tracker[str(target_file.resolve())] = model.FileStatus(
        mtime=target_file.stat().st_mtime,
        content_sha256=hash_text_sha256(target_file.read_text(encoding="utf-8")),
    )

    first_attachment = _arun(attachments.last_path_skill_attachment(session))
    assert first_attachment is not None
    first_text = message.join_text_parts(first_attachment.parts)
    assert "<description>v1</description>" in first_text
    assert "version one" not in first_text

    assert _arun(attachments.last_path_skill_attachment(session)) is None

    skill_path.write_text("---\nname: refresh-skill\ndescription: v2\n---\nversion two\n", encoding="utf-8")

    second_attachment = _arun(attachments.last_path_skill_attachment(session))
    assert second_attachment is not None
    second_text = message.join_text_parts(second_attachment.parts)
    assert "<description>v2</description>" in second_text
    assert "version two" not in second_text


def test_last_path_skill_attachment_supersedes_prior_same_name_skill(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"

    first_file = work_dir / "pkg_a" / "main.py"
    first_file.parent.mkdir(parents=True)
    first_file.write_text("print('a')\n", encoding="utf-8")
    first_skill = work_dir / "pkg_a" / ".claude" / "skills" / "shared" / "SKILL.md"
    first_skill.parent.mkdir(parents=True)
    first_skill.write_text("---\nname: shared\ndescription: first\n---\n# First\n", encoding="utf-8")

    second_file = work_dir / "pkg_b" / "main.py"
    second_file.parent.mkdir(parents=True)
    second_file.write_text("print('b')\n", encoding="utf-8")
    second_skill = work_dir / "pkg_b" / ".claude" / "skills" / "shared" / "SKILL.md"
    second_skill.parent.mkdir(parents=True)
    second_skill.write_text("---\nname: shared\ndescription: second\n---\n# Second\n", encoding="utf-8")

    session = Session(work_dir=work_dir)
    session.file_tracker[str(first_file.resolve())] = model.FileStatus(
        mtime=first_file.stat().st_mtime,
        content_sha256=hash_text_sha256(first_file.read_text(encoding="utf-8")),
    )

    first_attachment = _arun(attachments.last_path_skill_attachment(session))
    assert first_attachment is not None
    assert "<description>first</description>" in message.join_text_parts(first_attachment.parts)

    session.file_tracker[str(second_file.resolve())] = model.FileStatus(
        mtime=second_file.stat().st_mtime,
        content_sha256=hash_text_sha256(second_file.read_text(encoding="utf-8")),
    )

    second_attachment = _arun(attachments.last_path_skill_attachment(session))
    assert second_attachment is not None
    second_text = message.join_text_parts(second_attachment.parts)
    assert "<description>second</description>" in second_text
    assert str(second_skill.resolve()) in session.file_tracker


def test_at_dir_skill_anchor_survives_attachment_reset(tmp_path: Path) -> None:
    from klaude_code.agent.task import _reset_attachment_loaded_flags  # pyright: ignore[reportPrivateUsage]

    work_dir = tmp_path / "repo"
    target_dir = work_dir / "nested"
    target_dir.mkdir(parents=True)
    (target_dir / "file.txt").write_text("hello\n", encoding="utf-8")

    skill_dir = target_dir / ".claude" / "skills" / "local-dir-skill"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        "---\nname: local-dir-skill\ndescription: dir skill\n---\n# Dir skill\n",
        encoding="utf-8",
    )

    session = Session(work_dir=work_dir)
    session.conversation_history.append(
        message.UserMessage(parts=message.text_parts_from_str(f"@{target_dir.resolve()}"))
    )

    first_attachment = _arun(attachments.at_file_reader_attachment(session))
    assert first_attachment is not None
    first_text = message.join_text_parts(first_attachment.parts)
    assert "<available_skills>" in first_text
    assert "<name>local-dir-skill</name>" in first_text
    assert "# Dir skill" not in first_text
    assert str(target_dir.resolve()) in session.file_tracker
    assert session.file_tracker[str(target_dir.resolve())].is_directory is True

    _reset_attachment_loaded_flags(session.file_tracker)

    second_attachment = _arun(attachments.last_path_skill_attachment(session))
    assert second_attachment is not None
    assert "<name>local-dir-skill</name>" in message.join_text_parts(second_attachment.parts)


def test_skill_attachment_prefers_dynamic_skill_over_static_with_same_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work_dir = tmp_path / "repo"
    target_file = work_dir / "feature" / "app.py"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("print('hello')\n", encoding="utf-8")

    dynamic_skill_dir = work_dir / "feature" / ".claude" / "skills" / "commit"
    dynamic_skill_dir.mkdir(parents=True)
    dynamic_skill_path = dynamic_skill_dir / "SKILL.md"
    dynamic_skill_path.write_text(
        "---\nname: commit\ndescription: dynamic commit\n---\n# Dynamic commit\n",
        encoding="utf-8",
    )

    static_skill_dir = tmp_path / "static-commit"
    static_skill_dir.mkdir(parents=True)
    static_skill_path = static_skill_dir / "SKILL.md"
    static_skill_path.write_text("# Static commit\n", encoding="utf-8")
    static_skill = Skill(
        name="commit",
        description="static commit",
        location="system",
        skill_path=static_skill_path,
        base_dir=static_skill_dir,
    )

    monkeypatch.setattr(attachments, "get_skill", lambda _name="": static_skill)

    session = Session(work_dir=work_dir)
    session.file_tracker[str(target_file.resolve())] = model.FileStatus(
        mtime=target_file.stat().st_mtime,
        content_sha256=hash_text_sha256(target_file.read_text(encoding="utf-8")),
    )
    session.conversation_history.append(message.UserMessage(parts=message.text_parts_from_str("/skill:commit")))

    attachment = _arun(attachments.skill_attachment(session))

    assert attachment is not None
    text = message.join_text_parts(attachment.parts)
    assert "# Dynamic commit" in text
    assert "# Static commit" not in text


def test_skill_attachment_preserves_exact_namespaced_static_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work_dir = tmp_path / "repo"
    target_file = work_dir / "feature" / "app.py"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("print('hello')\n", encoding="utf-8")

    dynamic_skill_dir = work_dir / "feature" / ".claude" / "skills" / "commit"
    dynamic_skill_dir.mkdir(parents=True)
    dynamic_skill_path = dynamic_skill_dir / "SKILL.md"
    dynamic_skill_path.write_text(
        "---\nname: commit\ndescription: dynamic commit\n---\n# Dynamic commit\n",
        encoding="utf-8",
    )

    static_skill_dir = tmp_path / "static-namespaced"
    static_skill_dir.mkdir(parents=True)
    static_skill_path = static_skill_dir / "SKILL.md"
    static_skill_path.write_text("# Static namespaced commit\n", encoding="utf-8")
    static_skill = Skill(
        name="team:commit",
        description="namespaced commit",
        location="system",
        skill_path=static_skill_path,
        base_dir=static_skill_dir,
    )

    class _Loader:
        loaded_skills: ClassVar[dict[str, object]] = {"team:commit": static_skill}

    monkeypatch.setattr(attachments, "get_skill_loader", lambda: _Loader())
    monkeypatch.setattr(attachments, "get_skill", lambda _name="": None)

    session = Session(work_dir=work_dir)
    session.file_tracker[str(target_file.resolve())] = model.FileStatus(
        mtime=target_file.stat().st_mtime,
        content_sha256=hash_text_sha256(target_file.read_text(encoding="utf-8")),
    )
    session.conversation_history.append(message.UserMessage(parts=message.text_parts_from_str("/skill:team:commit")))

    attachment = _arun(attachments.skill_attachment(session))

    assert attachment is not None
    text = message.join_text_parts(attachment.parts)
    assert "# Static namespaced commit" in text
    assert "# Dynamic commit" not in text


def test_last_path_skill_attachment_does_not_override_explicit_skill(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    target_file = work_dir / "pkg" / "main.py"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("print('hello')\n", encoding="utf-8")

    dynamic_skill_dir = work_dir / "pkg" / ".claude" / "skills" / "shared"
    dynamic_skill_dir.mkdir(parents=True)
    dynamic_skill_path = dynamic_skill_dir / "SKILL.md"
    dynamic_skill_path.write_text(
        "---\nname: shared\ndescription: dynamic\n---\n# Dynamic shared\n",
        encoding="utf-8",
    )

    explicit_skill_dir = tmp_path / "explicit-shared"
    explicit_skill_dir.mkdir(parents=True)
    explicit_skill_path = explicit_skill_dir / "SKILL.md"
    explicit_skill_path.write_text(
        "---\nname: shared\ndescription: explicit\n---\n# Explicit shared\n",
        encoding="utf-8",
    )

    session = Session(work_dir=work_dir)
    session.file_tracker[str(target_file.resolve())] = model.FileStatus(
        mtime=target_file.stat().st_mtime,
        content_sha256=hash_text_sha256(target_file.read_text(encoding="utf-8")),
    )
    session.file_tracker[str(explicit_skill_path.resolve())] = model.FileStatus(
        mtime=explicit_skill_path.stat().st_mtime,
        content_sha256=hash_text_sha256(explicit_skill_path.read_text(encoding="utf-8")),
        is_skill=True,
        skill_attachment_source="explicit",
    )

    assert _arun(attachments.last_path_skill_attachment(session)) is None


def test_last_path_skill_attachment_discovers_external_repo_root_skill(tmp_path: Path) -> None:
    work_dir = tmp_path / "repo"
    work_dir.mkdir()

    external_repo = tmp_path / "content-workspace"
    (external_repo / ".git").mkdir(parents=True)

    target_file = external_repo / "posts" / "draft.md"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("# Draft\n", encoding="utf-8")

    skill_dir = external_repo / ".agents" / "skills" / "writer"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text("---\nname: writer\ndescription: external writer skill\n---\n# Writer\n", encoding="utf-8")

    session = Session(work_dir=work_dir)
    session.file_tracker[str(target_file.resolve())] = model.FileStatus(
        mtime=target_file.stat().st_mtime,
        content_sha256=hash_text_sha256(target_file.read_text(encoding="utf-8")),
    )

    attachment = _arun(attachments.last_path_skill_attachment(session))

    assert attachment is not None
    text = message.join_text_parts(attachment.parts)
    assert "<name>writer</name>" in text
    assert "<description>external writer skill</description>" in text
    assert "# Writer" not in text


def test_candidate_skill_dir_discovery_uses_cache(tmp_path: Path) -> None:
    get_candidate_skill_dirs_for_anchor.cache_clear()

    boundary_dir = tmp_path / "external" / "project"
    anchor_dir = boundary_dir / "pkg"

    get_candidate_skill_dirs_for_anchor(anchor_dir, boundary_dir, True)
    first = get_candidate_skill_dirs_for_anchor.cache_info()

    get_candidate_skill_dirs_for_anchor(anchor_dir, boundary_dir, True)
    second = get_candidate_skill_dirs_for_anchor.cache_info()

    assert second.hits == first.hits + 1
