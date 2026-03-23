import { describe, it, expect } from "vitest";
import { parseBashCommand, shortDisplayPath } from "./parse-bash-command";
import type { ParsedBashCommand } from "./parse-bash-command";

// Helper to make assertions more readable
function expectParsed(command: string, expected: ParsedBashCommand[]) {
  expect(parseBashCommand(command)).toEqual(expected);
}

describe("parseBashCommand", () => {
  // --- Read commands ---

  describe("read classification", () => {
    it("classifies cat as read", () => {
      expectParsed("cat README.md", [{ type: "read", name: "README.md" }]);
    });

    it("classifies cat with path as read with basename", () => {
      expectParsed("cat webview/src/main.rs", [{ type: "read", name: "main.rs" }]);
    });

    it("classifies bat with flags as read", () => {
      expectParsed("bat --theme TwoDark README.md", [{ type: "read", name: "README.md" }]);
    });

    it("classifies batcat as read", () => {
      expectParsed("batcat README.md", [{ type: "read", name: "README.md" }]);
    });

    it("classifies less as read", () => {
      expectParsed("less -p TODO README.md", [{ type: "read", name: "README.md" }]);
    });

    it("classifies more as read", () => {
      expectParsed("more README.md", [{ type: "read", name: "README.md" }]);
    });

    it("classifies head -n with file as read", () => {
      expectParsed("head -n 50 Cargo.toml", [{ type: "read", name: "Cargo.toml" }]);
    });

    it("classifies head -n50 (no space) with file as read", () => {
      expectParsed("head -n50 Cargo.toml", [{ type: "read", name: "Cargo.toml" }]);
    });

    it("classifies head with file only as read", () => {
      expectParsed("head Cargo.toml", [{ type: "read", name: "Cargo.toml" }]);
    });

    it("classifies tail -n with file as read", () => {
      expectParsed("tail -n +522 README.md", [{ type: "read", name: "README.md" }]);
    });

    it("classifies tail with file only as read", () => {
      expectParsed("tail README.md", [{ type: "read", name: "README.md" }]);
    });

    it("classifies sed -n range file as read", () => {
      expectParsed("sed -n '2000,2200p' tui/src/history_cell.rs", [
        { type: "read", name: "history_cell.rs" },
      ]);
    });

    it("classifies awk with file as read", () => {
      expectParsed("awk '{print $1}' Cargo.toml", [{ type: "read", name: "Cargo.toml" }]);
    });

    it("classifies nl with file as read", () => {
      expectParsed("nl -ba core/src/parse_command.rs", [
        { type: "read", name: "parse_command.rs" },
      ]);
    });
  });

  // --- ListFiles commands ---

  describe("list classification", () => {
    it("classifies ls as list", () => {
      expectParsed("ls -la", [{ type: "list", path: null }]);
    });

    it("classifies ls with path as list", () => {
      expectParsed("ls -la src/", [{ type: "list", path: "src" }]);
    });

    it("classifies tree as list", () => {
      expectParsed("tree -L 2 src", [{ type: "list", path: "src" }]);
    });

    it("classifies eza as list", () => {
      expectParsed("eza --color=always src", [{ type: "list", path: "src" }]);
    });

    it("classifies du as list", () => {
      expectParsed("du -d 2 .", [{ type: "list", path: "." }]);
    });

    it("classifies rg --files as list", () => {
      expectParsed("rg --files", [{ type: "list", path: null }]);
    });

    it("classifies rg --files with path as list", () => {
      expectParsed("rg --files webview/src", [{ type: "list", path: "webview" }]);
    });

    it("classifies git ls-files as list", () => {
      expectParsed("git ls-files", [{ type: "list", path: null }]);
    });

    it("classifies git ls-files with path as list", () => {
      expectParsed("git ls-files src", [{ type: "list", path: "src" }]);
    });

    it("classifies fd -t f as list", () => {
      expectParsed("fd -t f src/", [{ type: "list", path: "src" }]);
    });

    it("classifies find with type only as list", () => {
      expectParsed("find src -type f", [{ type: "list", path: "src" }]);
    });

    it("classifies python file walk as list", () => {
      expectParsed("python -c \"import os; os.listdir('.')\"", [{ type: "list", path: null }]);
    });

    it("classifies python3 glob as list", () => {
      expectParsed("python3 -c \"import glob; print(glob.glob('*.rs'))\"", [
        { type: "list", path: null },
      ]);
    });
  });

  // --- Search commands ---

  describe("search classification", () => {
    it("classifies rg with query as search", () => {
      expectParsed("rg TODO src", [{ type: "search", query: "TODO", path: "src" }]);
    });

    it("classifies rg with quoted query as search", () => {
      expectParsed('rg -n "BUG|FIXME|TODO" -S', [
        { type: "search", query: "BUG|FIXME|TODO", path: null },
      ]);
    });

    it("classifies grep -R as search", () => {
      expectParsed("grep -R TODO -n .", [{ type: "search", query: "TODO", path: "." }]);
    });

    it("classifies grep with specific file as search", () => {
      expectParsed("grep -R CODEX_SANDBOX_ENV_VAR -n core/src/spawn.rs", [
        { type: "search", query: "CODEX_SANDBOX_ENV_VAR", path: "spawn.rs" },
      ]);
    });

    it("classifies egrep and fgrep as search", () => {
      expectParsed("egrep -R TODO src", [{ type: "search", query: "TODO", path: "src" }]);
      expectParsed("fgrep -l TODO src", [{ type: "search", query: "TODO", path: "src" }]);
    });

    it("classifies ag as search", () => {
      expectParsed("ag TODO src", [{ type: "search", query: "TODO", path: "src" }]);
    });

    it("classifies ack as search", () => {
      expectParsed("ack TODO src", [{ type: "search", query: "TODO", path: "src" }]);
    });

    it("classifies pt as search", () => {
      expectParsed("pt TODO src", [{ type: "search", query: "TODO", path: "src" }]);
    });

    it("classifies rga as search", () => {
      expectParsed("rga TODO src", [{ type: "search", query: "TODO", path: "src" }]);
    });

    it("classifies git grep as search", () => {
      expectParsed("git grep TODO src", [{ type: "search", query: "TODO", path: "src" }]);
    });

    it("classifies fd with query as search", () => {
      expectParsed("fd main src", [{ type: "search", query: "main", path: "src" }]);
    });

    it("classifies find with -name as search", () => {
      expectParsed("find . -name '*.rs'", [{ type: "search", query: "*.rs", path: "." }]);
    });
  });

  // --- Run (unknown) commands ---

  describe("run classification", () => {
    it("classifies git status as run", () => {
      expectParsed("git status", [{ type: "run", cmd: "git status" }]);
    });

    it("classifies git commit as run", () => {
      expectParsed("git commit -m 'msg'", [{ type: "run", cmd: "git commit" }]);
    });

    it("classifies npm run build as run", () => {
      expectParsed("npm run build", [{ type: "run", cmd: "npm run" }]);
    });

    it("classifies make as run with subcommand", () => {
      expectParsed("make test", [{ type: "run", cmd: "make test" }]);
    });

    it("classifies unknown commands as run", () => {
      expectParsed("mycommand --flag", [{ type: "run", cmd: "mycommand" }]);
    });

    it("classifies python without file walk as run", () => {
      expectParsed("python -c \"print('hello')\"", [{ type: "run", cmd: "python" }]);
    });
  });

  // --- Pipeline filtering ---

  describe("pipeline formatting command filtering", () => {
    it("filters head from rg --files pipeline", () => {
      expectParsed("rg --files | head -n 50", [{ type: "list", path: null }]);
    });

    it("filters tail from pipeline", () => {
      expectParsed("rg --files | tail -n 20", [{ type: "list", path: null }]);
    });

    it("filters wc from pipeline", () => {
      expectParsed("git status | wc -l", [{ type: "run", cmd: "git status" }]);
    });

    it("filters sort from pipeline", () => {
      expectParsed("rg --files | sort", [{ type: "list", path: null }]);
    });

    it("filters sed -n from cat pipeline", () => {
      expectParsed("cat tui/Cargo.toml | sed -n '1,200p'", [{ type: "read", name: "Cargo.toml" }]);
    });

    it("filters head from rg search pipeline", () => {
      expectParsed('rg -n "BUG|FIXME|TODO" -S | head -n 200', [
        { type: "search", query: "BUG|FIXME|TODO", path: null },
      ]);
    });

    it("keeps mutating xargs pipeline as run", () => {
      expectParsed(
        "rg -l QkBindingController src | xargs perl -pi -e 's/QkBindingController/QkController/g'",
        [
          {
            type: "run",
            cmd: "rg -l QkBindingController src | xargs perl -pi -e s/QkBindingController/QkController/g",
          },
        ],
      );
    });

    it("filters nl -ba from pipeline", () => {
      expectParsed("rg --files | nl -ba", [{ type: "list", path: null }]);
    });

    it("does not filter single-stage commands", () => {
      // sort as standalone should not be filtered
      expectParsed("sort file.txt", [{ type: "run", cmd: "sort" }]);
    });

    it("filters ls pipeline with sed", () => {
      expectParsed("ls -la | sed -n '1,120p'", [{ type: "list", path: null }]);
    });
  });

  // --- Compound commands ---

  describe("compound statements", () => {
    it("parses cd && cat as read (cd dropped)", () => {
      expectParsed("cd foo && cat foo.txt", [{ type: "read", name: "foo.txt" }]);
    });

    it("parses cd && rg as search (cd dropped)", () => {
      expectParsed('cd /Users/user/code && rg -n "codex_api" codex-rs -S | head -n 50', [
        { type: "search", query: "codex_api", path: "codex-rs" },
      ]);
    });

    it("parses cd && rg --files as list (cd dropped)", () => {
      expectParsed("cd codex-rs && rg --files", [{ type: "list", path: null }]);
    });

    it("parses multiple statements", () => {
      expectParsed("cat README.md && rg TODO src", [
        { type: "read", name: "README.md" },
        { type: "search", query: "TODO", path: "src" },
      ]);
    });

    it("drops true from statements", () => {
      expectParsed("true && rg --files", [{ type: "list", path: null }]);
      expectParsed("rg --files || true", [{ type: "list", path: null }]);
    });

    it("drops echo from statements", () => {
      expectParsed("echo 'starting...' && cat README.md", [{ type: "read", name: "README.md" }]);
    });
  });

  // --- Deduplication ---

  describe("deduplication", () => {
    it("deduplicates consecutive identical commands", () => {
      expectParsed("rg TODO src && rg TODO src", [{ type: "search", query: "TODO", path: "src" }]);
    });

    it("keeps different commands", () => {
      expectParsed("rg TODO src && rg FIXME src", [
        { type: "search", query: "TODO", path: "src" },
        { type: "search", query: "FIXME", path: "src" },
      ]);
    });
  });
});

describe("shortDisplayPath", () => {
  it("returns basename for simple paths", () => {
    expect(shortDisplayPath("foo/bar/main.rs")).toBe("main.rs");
  });

  it("skips src segment", () => {
    expect(shortDisplayPath("webview/src")).toBe("webview");
  });

  it("skips build/dist/node_modules", () => {
    expect(shortDisplayPath("packages/app/node_modules")).toBe("app");
    expect(shortDisplayPath("foo/build")).toBe("foo");
    expect(shortDisplayPath("bar/dist")).toBe("bar");
  });

  it("strips trailing slashes", () => {
    expect(shortDisplayPath("webview/src/")).toBe("webview");
  });

  it("handles single component", () => {
    expect(shortDisplayPath("README.md")).toBe("README.md");
  });

  it("handles dot paths", () => {
    expect(shortDisplayPath(".")).toBe(".");
  });
});
