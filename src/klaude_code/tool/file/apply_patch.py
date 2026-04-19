"""
https://github.com/openai/openai-cookbook/blob/main/examples/gpt-5/apply_patch.py
"""

import os
from collections.abc import Callable, Iterator
from enum import Enum

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    ADD = "add"
    DELETE = "delete"
    UPDATE = "update"

class FileChange(BaseModel):
    type: ActionType
    old_content: str | None = None
    new_content: str | None = None
    move_path: str | None = None

class Commit(BaseModel):
    changes: dict[str, FileChange] = Field(default_factory=dict)

def _new_str_list() -> list[str]:
    # Returns a new list[str] for pydantic Field default_factory
    return []

class Chunk(BaseModel):
    orig_index: int = -1  # line index of the first line in the original file
    del_lines: list[str] = Field(default_factory=_new_str_list)
    ins_lines: list[str] = Field(default_factory=_new_str_list)

def _new_chunk_list() -> list["Chunk"]:
    # Returns a new list[Chunk] for pydantic Field default_factory
    return []

class PatchAction(BaseModel):
    type: ActionType
    new_file: str | None = None
    chunks: list[Chunk] = Field(default_factory=_new_chunk_list)
    move_path: str | None = None

class Patch(BaseModel):
    actions: dict[str, PatchAction] = Field(default_factory=dict)

class PatchSection(BaseModel):
    type: ActionType
    path: str
    text: str

def _new_patch_section_list() -> list[PatchSection]:
    return []

class PatchGroup(BaseModel):
    path: str
    sections: list[PatchSection] = Field(default_factory=_new_patch_section_list)

def _new_commit_list() -> list[Commit]:
    return []

class PatchSuccess(BaseModel):
    path: str
    change: FileChange
    commits: list[Commit] = Field(default_factory=_new_commit_list)

class PatchFailure(BaseModel):
    path: str
    error: str

def _new_patch_success_list() -> list[PatchSuccess]:
    return []

def _new_patch_failure_list() -> list[PatchFailure]:
    return []

class PatchResult(BaseModel):
    successes: list[PatchSuccess] = Field(default_factory=_new_patch_success_list)
    failures: list[PatchFailure] = Field(default_factory=_new_patch_failure_list)

class Parser(BaseModel):
    current_files: dict[str, str] = Field(default_factory=dict)
    lines: list[str] = Field(default_factory=list)
    index: int = 0
    patch: Patch = Field(default_factory=Patch)
    fuzz: int = 0

    def is_done(self, prefixes: tuple[str, ...] | None = None) -> bool:
        if self.index >= len(self.lines):
            return True
        return bool(prefixes and self.lines[self.index].startswith(prefixes))

    def startswith(self, prefix: str | tuple[str, ...]) -> bool:
        assert self.index < len(self.lines), f"Index: {self.index} >= {len(self.lines)}"
        return self.lines[self.index].startswith(prefix)

    def read_str(self, prefix: str = "", return_everything: bool = False) -> str:
        assert self.index < len(self.lines), f"Index: {self.index} >= {len(self.lines)}"
        if self.lines[self.index].startswith(prefix):
            text = self.lines[self.index] if return_everything else self.lines[self.index][len(prefix) :]
            self.index += 1
            return text
        return ""

    def parse(self):
        while not self.is_done(("*** End Patch",)):
            path = self.read_str("*** Update File: ")
            if path:
                if path in self.patch.actions:
                    raise DiffError(f"Update File Error: Duplicate Path: {path}")
                move_to = self.read_str("*** Move to: ")
                if path not in self.current_files:
                    raise DiffError(f"Update File Error: Missing File: {path}")
                text = self.current_files[path]
                action = self.parse_update_file(text)
                # TODO: Check move_to is valid
                action.move_path = move_to
                self.patch.actions[path] = action
                continue
            path = self.read_str("*** Delete File: ")
            if path:
                if path in self.patch.actions:
                    raise DiffError(f"Delete File Error: Duplicate Path: {path}")
                if path not in self.current_files:
                    raise DiffError(f"Delete File Error: Missing File: {path}")
                self.patch.actions[path] = PatchAction(
                    type=ActionType.DELETE,
                )
                continue
            path = self.read_str("*** Add File: ")
            if path:
                if path in self.patch.actions:
                    raise DiffError(f"Add File Error: Duplicate Path: {path}")
                self.patch.actions[path] = self.parse_add_file()
                continue
            raise DiffError(f"Unknown Line: {self.lines[self.index]}")
        if not self.startswith("*** End Patch"):
            raise DiffError("Missing End Patch")
        self.index += 1

    def parse_update_file(self, text: str) -> PatchAction:
        # self.lines / self.index refers to the patch
        # lines / index refers to the file being modified
        # print("parse update file")
        action = PatchAction(
            type=ActionType.UPDATE,
        )
        lines = text.split("\n")
        index = 0
        while not self.is_done(
            (
                "*** End Patch",
                "*** Update File:",
                "*** Delete File:",
                "*** Add File:",
                "*** End of File",
            )
        ):
            def_str = self.read_str("@@ ")
            section_str = ""
            if not def_str and self.lines[self.index] == "@@":
                section_str = self.lines[self.index]
                self.index += 1
            if not (def_str or section_str or index == 0):
                raise DiffError(f"Invalid Line:\n{self.lines[self.index]}")
            if def_str.strip():
                found = False
                if not [s for s in lines[:index] if s == def_str]:
                    # def str is a skip ahead operator
                    for i, s in enumerate(lines[index:], index):
                        if s == def_str:
                            # print(f"Jump ahead @@: {index} -> {i}: {def_str}")
                            index = i + 1
                            found = True
                            break
                if not found and not [s for s in lines[:index] if s.strip() == def_str.strip()]:
                    # def str is a skip ahead operator
                    for i, s in enumerate(lines[index:], index):
                        if s.strip() == def_str.strip():
                            # print(f"Jump ahead @@: {index} -> {i}: {def_str}")
                            index = i + 1
                            self.fuzz += 1
                            found = True
                            break
            next_chunk_context, chunks, end_patch_index, eof = peek_next_section(self.lines, self.index)
            next_chunk_text = "\n".join(next_chunk_context)
            new_index, fuzz = find_context(lines, next_chunk_context, index, eof)
            if new_index == -1:
                if eof:
                    raise DiffError(f"Invalid EOF Context {index}:\n{next_chunk_text}")
                else:
                    raise DiffError(f"Invalid Context {index}:\n{next_chunk_text}")
            self.fuzz += fuzz
            # print(f"Jump ahead: {index} -> {new_index}")
            for ch in chunks:
                ch.orig_index += new_index
                action.chunks.append(ch)
            index = new_index + len(next_chunk_context)
            self.index = end_patch_index
            continue
        return action

    def parse_add_file(self) -> PatchAction:
        lines: list[str] = []
        while not self.is_done(("*** End Patch", "*** Update File:", "*** Delete File:", "*** Add File:")):
            s = self.read_str()
            if not s.startswith("+"):
                raise DiffError(f"Invalid Add File Line: {s}")
            s = s[1:]
            lines.append(s)
        return PatchAction(
            type=ActionType.ADD,
            new_file="\n".join(lines),
        )

def find_context_core(lines: list[str], context: list[str], start: int) -> tuple[int, int]:
    if not context:
        # print("context is empty")
        return start, 0

    # Prefer identical
    for i in range(start, len(lines)):
        if lines[i : i + len(context)] == context:
            return i, 0
    # RStrip is ok
    for i in range(start, len(lines)):
        if [s.rstrip() for s in lines[i : i + len(context)]] == [s.rstrip() for s in context]:
            return i, 1
    # Fine, Strip is ok too.
    for i in range(start, len(lines)):
        if [s.strip() for s in lines[i : i + len(context)]] == [s.strip() for s in context]:
            return i, 100
    return -1, 0

def find_context(lines: list[str], context: list[str], start: int, eof: bool) -> tuple[int, int]:
    if eof:
        new_index, fuzz = find_context_core(lines, context, len(lines) - len(context))
        if new_index != -1:
            return new_index, fuzz
        new_index, fuzz = find_context_core(lines, context, start)
        return new_index, fuzz + 10000
    return find_context_core(lines, context, start)

def peek_next_section(lines: list[str], index: int) -> tuple[list[str], list[Chunk], int, bool]:
    old: list[str] = []
    del_lines: list[str] = []
    ins_lines: list[str] = []
    chunks: list[Chunk] = []
    mode = "keep"
    orig_index = index
    while index < len(lines):
        s = lines[index]
        if s.startswith(
            (
                "@@",
                "*** End Patch",
                "*** Update File:",
                "*** Delete File:",
                "*** Add File:",
                "*** End of File",
            )
        ):
            break
        if s == "***":
            break
        elif s.startswith("***"):
            raise DiffError(f"Invalid Line: {s}")
        index += 1
        last_mode = mode
        if s == "":
            s = " "
        if s[0] == "+":
            mode = "add"
        elif s[0] == "-":
            mode = "delete"
        elif s[0] == " ":
            mode = "keep"
        else:
            raise DiffError(f"Invalid Line: {s}")
        s = s[1:]
        if mode == "keep" and last_mode != mode:
            if ins_lines or del_lines:
                chunks.append(
                    Chunk(
                        orig_index=len(old) - len(del_lines),
                        del_lines=del_lines,
                        ins_lines=ins_lines,
                    )
                )
            del_lines = []
            ins_lines = []
        if mode == "delete":
            del_lines.append(s)
            old.append(s)
        elif mode == "add":
            ins_lines.append(s)
        elif mode == "keep":
            old.append(s)
    if ins_lines or del_lines:
        chunks.append(
            Chunk(
                orig_index=len(old) - len(del_lines),
                del_lines=del_lines,
                ins_lines=ins_lines,
            )
        )
        del_lines = []
        ins_lines = []
    if index < len(lines) and lines[index] == "*** End of File":
        index += 1
        return old, chunks, index, True
    if index == orig_index:
        raise DiffError(f"Nothing in this section - {index=} {lines[index]}")
    return old, chunks, index, False

_PATCH_ACTION_PREFIXES = ("*** Update File: ", "*** Delete File: ", "*** Add File: ")

def _duplicate_path_error(action_type: ActionType, path: str) -> "DiffError":
    prefix = {
        ActionType.UPDATE: "Update File Error",
        ActionType.DELETE: "Delete File Error",
        ActionType.ADD: "Add File Error",
    }[action_type]
    return DiffError(f"{prefix}: Duplicate Path: {path}")

def _parse_section_header(line: str) -> tuple[ActionType, str]:
    for prefix, action_type in (
        ("*** Update File: ", ActionType.UPDATE),
        ("*** Delete File: ", ActionType.DELETE),
        ("*** Add File: ", ActionType.ADD),
    ):
        if line.startswith(prefix):
            return action_type, line[len(prefix) :]
    raise DiffError(f"Unknown Line: {line}")

def _patch_lines(text: str) -> list[str]:
    lines = text.strip().split("\n")
    if len(lines) < 2 or not lines[0].startswith("*** Begin Patch") or lines[-1] != "*** End Patch":
        raise DiffError('Invalid patch text, expected "*** Begin Patch" and "*** End Patch"')
    return lines

def split_patch_sections(text: str) -> list[PatchSection]:
    lines = _patch_lines(text)
    sections: list[PatchSection] = []
    index = 1

    while index < len(lines) - 1:
        line = lines[index]
        action_type, path = _parse_section_header(line)

        start = index
        index += 1
        while index < len(lines) - 1 and not lines[index].startswith(_PATCH_ACTION_PREFIXES):
            if (
                lines[index].startswith("***")
                and lines[index] != "*** End of File"
                and not lines[index].startswith("*** Move to: ")
            ):
                raise DiffError(f"Invalid Line: {lines[index]}")
            index += 1

        section_lines = ["*** Begin Patch", *lines[start:index], "*** End Patch"]
        sections.append(PatchSection(type=action_type, path=path, text="\n".join(section_lines)))

    return sections

def group_patch_sections(text: str) -> list[PatchGroup]:
    groups_by_path: dict[str, PatchGroup] = {}
    for section in split_patch_sections(text):
        group = groups_by_path.get(section.path)
        if group is None:
            group = PatchGroup(path=section.path)
            groups_by_path[section.path] = group
        elif section.type != ActionType.UPDATE:
            raise _duplicate_path_error(section.type, section.path)
        group.sections.append(section)
    return list(groups_by_path.values())

def text_to_patch(text: str, orig: dict[str, str]) -> tuple[Patch, int]:
    lines = _patch_lines(text)

    parser = Parser(
        current_files=orig,
        lines=lines,
        index=1,
    )
    parser.parse()
    return parser.patch, parser.fuzz

def identify_files_needed(text: str) -> list[str]:
    lines = text.strip().split("\n")
    result: set[str] = set()
    for line in lines:
        if line.startswith("*** Update File: "):
            result.add(line[len("*** Update File: ") :])
        if line.startswith("*** Delete File: "):
            result.add(line[len("*** Delete File: ") :])
    return list(result)

def _get_updated_file(text: str, action: PatchAction, path: str) -> str:
    assert action.type == ActionType.UPDATE
    orig_lines = text.split("\n")
    dest_lines: list[str] = []
    orig_index = 0
    dest_index = 0
    for chunk in action.chunks:
        # Process the unchanged lines before the chunk
        if chunk.orig_index > len(orig_lines):
            # print(f"_get_updated_file: {path}: chunk.orig_index {chunk.orig_index} > len(lines) {len(orig_lines)}")
            raise DiffError(
                f"_get_updated_file: {path}: chunk.orig_index {chunk.orig_index} > len(lines) {len(orig_lines)}"
            )
        if orig_index > chunk.orig_index:
            raise DiffError(f"_get_updated_file: {path}: orig_index {orig_index} > chunk.orig_index {chunk.orig_index}")
        assert orig_index <= chunk.orig_index
        dest_lines.extend(orig_lines[orig_index : chunk.orig_index])
        delta = chunk.orig_index - orig_index
        orig_index += delta
        dest_index += delta
        # Process the inserted lines
        if chunk.ins_lines:
            for i in range(len(chunk.ins_lines)):
                dest_lines.append(chunk.ins_lines[i])
            dest_index += len(chunk.ins_lines)
        orig_index += len(chunk.del_lines)
    # Final part
    dest_lines.extend(orig_lines[orig_index:])
    delta = len(orig_lines) - orig_index
    orig_index += delta
    dest_index += delta
    assert orig_index == len(orig_lines)
    assert dest_index == len(dest_lines)
    return "\n".join(dest_lines)

def patch_to_commit(patch: Patch, orig: dict[str, str]) -> Commit:
    commit = Commit()
    for path, action in patch.actions.items():
        if action.type == ActionType.DELETE:
            commit.changes[path] = FileChange(type=ActionType.DELETE, old_content=orig[path])
        elif action.type == ActionType.ADD:
            commit.changes[path] = FileChange(type=ActionType.ADD, new_content=action.new_file)
        elif action.type == ActionType.UPDATE:
            new_content = _get_updated_file(text=orig[path], action=action, path=path)
            commit.changes[path] = FileChange(
                type=ActionType.UPDATE,
                old_content=orig[path],
                new_content=new_content,
                move_path=action.move_path,
            )
    return commit

class DiffError(ValueError):
    pass

def _apply_commit_to_contents(commit: Commit, files: dict[str, str]) -> None:
    def write_fn(path: str, content: str) -> None:
        files[path] = content

    def remove_fn(path: str) -> None:
        if path not in files:
            raise DiffError(f"Missing File: {path}")
        del files[path]

    apply_commit(commit, write_fn, remove_fn)

def _flatten_commits(path: str, commits: list[Commit]) -> FileChange:
    if not commits:
        raise DiffError(f"Missing commit for path: {path}")

    first = commits[0].changes[path]
    last = commits[-1].changes[path]
    if len(commits) == 1:
        return last.model_copy(deep=True)

    return FileChange(
        type=ActionType.UPDATE,
        old_content=first.old_content,
        new_content=last.new_content,
        move_path=last.move_path,
    )

def iter_successful_changes(result: PatchResult):
    for success in result.successes:
        yield success.path, success.change

def describe_change(path: str, change: FileChange) -> str:
    if change.type == ActionType.DELETE:
        return f"deleted {path}"
    if change.type == ActionType.UPDATE and change.move_path and change.move_path != path:
        return f"{path} -> {change.move_path}"
    return path

def build_patch_result(text: str, open_fn: Callable[[str], str]) -> PatchResult:
    result = PatchResult()
    workspace_files: dict[str, str] = {}
    missing_files: set[str] = set()

    def load_current_file(path: str) -> str:
        if path in workspace_files:
            return workspace_files[path]
        if path in missing_files:
            raise DiffError(f"Missing File: {path}")
        content = open_fn(path)
        workspace_files[path] = content
        return content

    def write_workspace(path: str, content: str) -> None:
        workspace_files[path] = content
        missing_files.discard(path)

    def remove_workspace(path: str) -> None:
        workspace_files.pop(path, None)
        missing_files.add(path)

    for group in group_patch_sections(text):
        group_files: dict[str, str] = {}
        group_commits: list[Commit] = []
        try:
            for section in group.sections:
                if section.type != ActionType.ADD and section.path not in group_files:
                    group_files[section.path] = load_current_file(section.path)
                patch, _ = text_to_patch(section.text, group_files)
                commit = patch_to_commit(patch, group_files)
                _apply_commit_to_contents(commit, group_files)
                group_commits.append(commit)
        except DiffError as error:
            result.failures.append(PatchFailure(path=group.path, error=str(error)))
            continue

        for commit in group_commits:
            apply_commit(commit, write_workspace, remove_workspace)
        result.successes.append(
            PatchSuccess(path=group.path, change=_flatten_commits(group.path, group_commits), commits=group_commits)
        )

    return result

def iter_commits(result: PatchResult) -> Iterator[Commit]:
    for success in result.successes:
        yield from success.commits

def format_patch_result(result: PatchResult) -> str:
    if not result.failures:
        return "Done!"

    lines: list[str] = []
    if result.successes:
        lines.append("Applied changes:")
        for path, change in iter_successful_changes(result):
            lines.append(f"- {describe_change(path, change)}")
    lines.append("Failed changes:")
    for failure in result.failures:
        lines.append(f"- {failure.path}: {failure.error}")
    return "\n".join(lines)

def apply_commit(
    commit: Commit,
    write_fn: Callable[[str, str], None],
    remove_fn: Callable[[str], None],
) -> None:
    for path, change in commit.changes.items():
        if change.type == ActionType.DELETE:
            remove_fn(path)
        elif change.type == ActionType.ADD:
            if change.new_content is None:
                raise DiffError(f"Missing new_content for ADD: {path}")
            write_fn(path, change.new_content)
        elif change.type == ActionType.UPDATE:
            if change.move_path:
                if change.new_content is None:
                    raise DiffError(f"Missing new_content for UPDATE: {path}")
                write_fn(change.move_path, change.new_content)
                remove_fn(path)
            else:
                if change.new_content is None:
                    raise DiffError(f"Missing new_content for UPDATE: {path}")
                write_fn(path, change.new_content)

def process_patch(
    text: str,
    open_fn: Callable[[str], str],
    write_fn: Callable[[str, str], None],
    remove_fn: Callable[[str], None],
) -> str:
    assert text.startswith("*** Begin Patch")
    result = build_patch_result(text, open_fn)
    if not result.successes:
        raise DiffError(format_patch_result(result))
    for commit in iter_commits(result):
        apply_commit(commit, write_fn, remove_fn)
    return format_patch_result(result)

def open_file(path: str) -> str:
    with open(path) as f:
        return f.read()

def write_file(path: str, content: str) -> None:
    if "/" in path:
        parent = "/".join(path.split("/")[:-1])
        os.makedirs(parent, exist_ok=True)
    with open(path, "w") as f:
        f.write(content)

def remove_file(path: str) -> None:
    os.remove(path)

def main():
    import sys

    patch_text = sys.stdin.read()
    if not patch_text:
        print("Please pass patch text through stdin")
        return
    try:
        result = process_patch(patch_text, open_file, write_file, remove_file)
    except DiffError as e:
        print(str(e))
        return
    print(result)

if __name__ == "__main__":
    main()
