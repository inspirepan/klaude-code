/**
 * Semantic bash command parser.
 *
 * Classifies shell commands into Read / ListFiles / Search / Run categories
 * so the collapse-group summary can show richer labels than a raw command name.
 *
 * Ported from openai-codex codex-rs/shell-command/src/parse_command.rs
 */

import { parse as shellParse } from "shell-quote";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ParsedBashCommand =
  | { type: "read"; name: string }
  | { type: "list"; path: string | null }
  | { type: "search"; query: string | null; path: string | null }
  | { type: "run"; cmd: string };

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STATEMENT_SEPARATORS = new Set(["&&", "||", ";", "\n"]);

/** Commands that are always formatting helpers in pipelines. */
const ALWAYS_FORMATTING = new Set([
  "wc",
  "tr",
  "cut",
  "sort",
  "uniq",
  "tee",
  "column",
  "printf",
  "yes",
]);

/** Leading commands to drop from statements (noise, not actionable). */
const IGNORED_STATEMENTS = new Set(["cd", "true", "echo"]);

/** Commands that take a meaningful subcommand as second token (for "run" display). */
const SUBCOMMAND_COMMANDS = new Set([
  // Version control
  "git",
  "jj",
  "hg",
  "svn",
  // Containers & orchestration
  "docker",
  "docker-compose",
  "podman",
  "kubectl",
  "helm",
  "minikube",
  // JS package managers
  "npm",
  "yarn",
  "pnpm",
  "bun",
  "deno",
  // Rust
  "cargo",
  "rustup",
  // Python
  "uv",
  "pip",
  "pipx",
  "poetry",
  "conda",
  "python",
  // Ruby
  "ruby",
  "gem",
  "bundle",
  // Other languages
  "go",
  "dotnet",
  "swift",
  "mix",
  "gradle",
  // System package managers
  "brew",
  "apt",
  "apt-get",
  "dnf",
  "yum",
  "pacman",
  // Cloud & infra
  "aws",
  "gcloud",
  "az",
  "terraform",
  "pulumi",
  "fly",
  "vercel",
  "netlify",
  "heroku",
  "wrangler",
  // Build tools
  "make",
  "just",
  "nx",
  "turbo",
  "bazel",
  // CLI tools
  "gh",
  // Service managers
  "systemctl",
  "launchctl",
  "supervisorctl",
]);

// ---------------------------------------------------------------------------
// Path utilities
// ---------------------------------------------------------------------------

/**
 * Shorten a path to its last meaningful component,
 * stripping common non-informative directory segments.
 */
export function shortDisplayPath(path: string): string {
  const normalized = path.replace(/\\/g, "/").replace(/\/+$/, "");
  const skip = new Set(["build", "dist", "node_modules", "src"]);
  const parts = normalized.split("/").filter(Boolean).reverse();
  for (const p of parts) {
    if (!skip.has(p)) return p;
  }
  return normalized;
}

// ---------------------------------------------------------------------------
// Flag / operand extraction
// ---------------------------------------------------------------------------

/**
 * Skip flag values and --flag=value, returning only non-consumed tokens.
 * Tokens after `--` are always kept.
 */
function skipFlagValues(args: string[], flagsWithVals: string[]): string[] {
  const out: string[] = [];
  let skipNext = false;
  for (let i = 0; i < args.length; i++) {
    if (skipNext) {
      skipNext = false;
      continue;
    }
    const a = args[i];
    if (a === "--") {
      out.push(...args.slice(i + 1));
      break;
    }
    if (a.startsWith("--") && a.includes("=")) continue;
    if (flagsWithVals.includes(a)) {
      if (i + 1 < args.length) skipNext = true;
      continue;
    }
    out.push(a);
  }
  return out;
}

/** Extract positional operands (non-flag, non-flag-value tokens). */
function positionalOperands(args: string[], flagsWithVals: string[]): string[] {
  const out: string[] = [];
  let afterDD = false;
  let skipNext = false;
  for (let i = 0; i < args.length; i++) {
    if (skipNext) {
      skipNext = false;
      continue;
    }
    if (afterDD) {
      out.push(args[i]);
      continue;
    }
    const a = args[i];
    if (a === "--") {
      afterDD = true;
      continue;
    }
    if (a.startsWith("--") && a.includes("=")) continue;
    if (flagsWithVals.includes(a)) {
      if (i + 1 < args.length) skipNext = true;
      continue;
    }
    if (a.startsWith("-")) continue;
    out.push(a);
  }
  return out;
}

function firstPositional(args: string[], flagsWithVals: string[]): string | null {
  return positionalOperands(args, flagsWithVals)[0] ?? null;
}

function singlePositional(args: string[], flagsWithVals: string[]): string | null {
  const ops = positionalOperands(args, flagsWithVals);
  return ops.length === 1 ? ops[0] : null;
}

// ---------------------------------------------------------------------------
// Formatting-command detection
// ---------------------------------------------------------------------------

/** Check if a sed argument is a valid range like `1,200p` or `10p`. */
function isValidSedRange(arg: string | undefined): boolean {
  if (!arg?.endsWith("p")) return false;
  const core = arg.slice(0, -1);
  const parts = core.split(",");
  if (parts.length === 1) return parts[0].length > 0 && /^\d+$/.test(parts[0]);
  if (parts.length === 2) return parts.every((p) => p.length > 0 && /^\d+$/.test(p));
  return false;
}

/** If `sed -n <range> <file>`, return the file path. */
function sedReadPath(args: string[]): string | null {
  if (!args.includes("-n")) return null;
  let hasRange = false;
  let i = 0;
  while (i < args.length) {
    if (args[i] === "-e" || args[i] === "--expression") {
      if (isValidSedRange(args[i + 1])) hasRange = true;
      i += 2;
      continue;
    }
    if (args[i] === "-f" || args[i] === "--file") {
      i += 2;
      continue;
    }
    i++;
  }
  if (!hasRange) hasRange = args.some((a) => !a.startsWith("-") && isValidSedRange(a));
  if (!hasRange) return null;
  const nonFlags = skipFlagValues(args, ["-e", "-f", "--expression", "--file"]).filter(
    (a) => !a.startsWith("-"),
  );
  if (nonFlags.length === 0) return null;
  if (isValidSedRange(nonFlags[0])) return nonFlags[1] ?? null;
  return nonFlags[0];
}

/** If awk has a data-file operand, return it. */
function awkFileOperand(args: string[]): string | null {
  if (args.length === 0) return null;
  const hasScriptFile = args.some((a) => a === "-f" || a === "--file");
  const nonFlags = skipFlagValues(args, [
    "-F",
    "-v",
    "-f",
    "--field-separator",
    "--assign",
    "--file",
  ]).filter((a) => !a.startsWith("-"));
  if (hasScriptFile) return nonFlags[0] ?? null;
  return nonFlags.length >= 2 ? nonFlags[1] : null;
}

function isMutatingXargs(tokens: string[]): boolean {
  let i = 1;
  while (i < tokens.length) {
    const t = tokens[i];
    if (t === "--") return checkMutatingSubcmd(tokens.slice(i + 1));
    if (!t.startsWith("-")) return checkMutatingSubcmd(tokens.slice(i));
    i += ["-E", "-e", "-I", "-L", "-n", "-P", "-s"].includes(t) && t.length === 2 ? 2 : 1;
  }
  return false;
}

function checkMutatingSubcmd(tokens: string[]): boolean {
  if (tokens.length === 0) return false;
  const [head, ...tail] = tokens;
  if (head === "perl" || head === "ruby")
    return tail.some((t) => t === "-i" || t.startsWith("-i") || t === "-pi" || t.startsWith("-pi"));
  if (head === "sed")
    return tail.some((t) => t === "-i" || t.startsWith("-i") || t === "--in-place");
  if (head === "rg") return tail.some((t) => t === "--replace");
  return false;
}

/**
 * Return true if this pipeline stage is a small formatting helper
 * (e.g. `head -n 40`, `wc -l`, `sort`).
 * Only called when there are multiple stages in a pipeline.
 */
function isFormattingCommand(tokens: string[]): boolean {
  if (tokens.length === 0) return false;
  const cmd = tokens[0];

  if (ALWAYS_FORMATTING.has(cmd)) return true;
  if (cmd === "xargs") return !isMutatingXargs(tokens);
  if (cmd === "awk") return awkFileOperand(tokens.slice(1)) === null;

  if (cmd === "head") {
    if (tokens.length <= 1) return true;
    if (tokens.length === 2) return tokens[1].startsWith("-");
    if (
      tokens.length === 3 &&
      (tokens[1] === "-n" || tokens[1] === "-c") &&
      /^\d+$/.test(tokens[2])
    )
      return true;
    return false;
  }

  if (cmd === "tail") {
    if (tokens.length <= 1) return true;
    if (tokens.length === 2) return tokens[1].startsWith("-");
    if (tokens.length === 3 && (tokens[1] === "-n" || tokens[1] === "-c")) {
      const v = tokens[2];
      const s = v.startsWith("+") ? v.slice(1) : v;
      return s.length > 0 && /^\d+$/.test(s);
    }
    return false;
  }

  if (cmd === "sed") return sedReadPath(tokens.slice(1)) === null;

  // nl without a file operand is formatting (e.g. `nl -ba` in a pipeline)
  if (cmd === "nl") {
    const file = skipFlagValues(tokens.slice(1), ["-s", "-w", "-v", "-i", "-b"]).find(
      (p) => !p.startsWith("-"),
    );
    return file === undefined;
  }

  return false;
}

// ---------------------------------------------------------------------------
// Command-specific parsers
// ---------------------------------------------------------------------------

function isPathish(s: string): boolean {
  return (
    s === "." ||
    s === ".." ||
    s.startsWith("./") ||
    s.startsWith("../") ||
    s.includes("/") ||
    s.includes("\\")
  );
}

/** Parse grep / egrep / fgrep / git-grep arguments. */
function parseGrepLike(args: string[]): ParsedBashCommand {
  let pattern: string | null = null;
  const operands: string[] = [];
  let afterDD = false;
  let i = 0;
  while (i < args.length) {
    const a = args[i];
    if (afterDD) {
      operands.push(a);
      i++;
      continue;
    }
    if (a === "--") {
      afterDD = true;
      i++;
      continue;
    }
    if ((a === "-e" || a === "--regexp") && args[i + 1] && !pattern) {
      pattern = args[i + 1];
      i += 2;
      continue;
    }
    if ((a === "-f" || a === "--file") && args[i + 1] && !pattern) {
      pattern = args[i + 1];
      i += 2;
      continue;
    }
    if (
      [
        "-m",
        "--max-count",
        "-C",
        "--context",
        "-A",
        "--after-context",
        "-B",
        "--before-context",
      ].includes(a)
    ) {
      i += 2;
      continue;
    }
    if (a.startsWith("-")) {
      i++;
      continue;
    }
    operands.push(a);
    i++;
  }
  const hasExplicitPattern = pattern !== null;
  const query = pattern ?? (operands[0] as string | undefined) ?? null;
  const pathIdx = hasExplicitPattern ? 0 : 1;
  const rawPath = operands[pathIdx] as string | undefined;
  const path = rawPath ? shortDisplayPath(rawPath) : null;
  return { type: "search", query, path };
}

function parseFd(tail: string[]): ParsedBashCommand {
  const nonFlags = skipFlagValues(tail, [
    "-t",
    "--type",
    "-e",
    "--extension",
    "-E",
    "--exclude",
    "--search-path",
  ]).filter((p) => !p.startsWith("-"));
  if (nonFlags.length === 0) return { type: "list", path: null };
  if (nonFlags.length === 1) {
    return isPathish(nonFlags[0])
      ? { type: "list", path: shortDisplayPath(nonFlags[0]) }
      : { type: "search", query: nonFlags[0], path: null };
  }
  return { type: "search", query: nonFlags[0], path: shortDisplayPath(nonFlags[1]) };
}

function parseFind(tail: string[]): ParsedBashCommand {
  let path: string | null = null;
  for (const a of tail) {
    if (!a.startsWith("-") && a !== "!" && a !== "(" && a !== ")") {
      path = shortDisplayPath(a);
      break;
    }
  }
  let query: string | null = null;
  for (let i = 0; i < tail.length; i++) {
    if (["-name", "-iname", "-path", "-regex"].includes(tail[i]) && tail[i + 1]) {
      query = tail[i + 1];
      break;
    }
  }
  return query ? { type: "search", query, path } : { type: "list", path };
}

function isPythonCmd(cmd: string): boolean {
  return /^python[23]?(\.\d+)?$/.test(cmd);
}

const PYTHON_FILE_WALK_PATTERNS =
  /os\.walk|os\.listdir|os\.scandir|glob\.glob|glob\.iglob|pathlib\.Path|\.rglob\(/;

// ---------------------------------------------------------------------------
// Main classifier
// ---------------------------------------------------------------------------

/** Classify a single command (one pipeline stage) into a ParsedBashCommand. */
function classifyCommand(tokens: string[]): ParsedBashCommand {
  if (tokens.length === 0) return { type: "run", cmd: "" };
  const [head, ...tail] = tokens;

  // --- Directory listing ---
  if (head === "ls" || head === "eza" || head === "exa") {
    const fwv: Record<string, string[]> = {
      ls: ["-I", "-w", "--block-size", "--format", "--time-style", "--color", "--quoting-style"],
      eza: ["-I", "--ignore-glob", "--color", "--sort", "--time-style", "--time"],
      exa: ["-I", "--ignore-glob", "--color", "--sort", "--time-style", "--time"],
    };
    const p = firstPositional(tail, fwv[head] ?? []);
    return { type: "list", path: p ? shortDisplayPath(p) : null };
  }
  if (head === "tree") {
    const p = firstPositional(tail, ["-L", "-P", "-I", "--charset", "--filelimit", "--sort"]);
    return { type: "list", path: p ? shortDisplayPath(p) : null };
  }
  if (head === "du") {
    const p = firstPositional(tail, [
      "-d",
      "--max-depth",
      "-B",
      "--block-size",
      "--exclude",
      "--time-style",
    ]);
    return { type: "list", path: p ? shortDisplayPath(p) : null };
  }

  // --- ripgrep ---
  if (head === "rg" || head === "rga" || head === "ripgrep-all") {
    const hasFiles = tail.includes("--files");
    const nonFlags = skipFlagValues(tail, [
      "-g",
      "--glob",
      "--iglob",
      "-t",
      "--type",
      "--type-add",
      "--type-not",
      "-m",
      "--max-count",
      "-A",
      "-B",
      "-C",
      "--context",
      "--max-depth",
    ]).filter((p) => !p.startsWith("-"));
    if (hasFiles) return { type: "list", path: nonFlags[0] ? shortDisplayPath(nonFlags[0]) : null };
    return {
      type: "search",
      query: nonFlags[0] ?? null,
      path: nonFlags[1] ? shortDisplayPath(nonFlags[1]) : null,
    };
  }

  // --- git subcommands ---
  if (head === "git") {
    if (tail[0] === "grep") return parseGrepLike(tail.slice(1));
    if (tail[0] === "ls-files") {
      const p = firstPositional(tail.slice(1), [
        "--exclude",
        "--exclude-from",
        "--pathspec-from-file",
      ]);
      return { type: "list", path: p ? shortDisplayPath(p) : null };
    }
    const sub = tail.find((w) => !w.startsWith("-"));
    return { type: "run", cmd: sub ? `git ${sub}` : "git" };
  }

  // --- fd / find ---
  if (head === "fd") return parseFd(tail);
  if (head === "find") return parseFind(tail);

  // --- grep family ---
  if (head === "grep" || head === "egrep" || head === "fgrep") return parseGrepLike(tail);

  // --- ag / ack / pt ---
  if (head === "ag" || head === "ack" || head === "pt") {
    const nonFlags = skipFlagValues(tail, [
      "-G",
      "-g",
      "--file-search-regex",
      "--ignore-dir",
      "--ignore-file",
      "--path-to-ignore",
    ]).filter((p) => !p.startsWith("-"));
    return {
      type: "search",
      query: nonFlags[0] ?? null,
      path: nonFlags[1] ? shortDisplayPath(nonFlags[1]) : null,
    };
  }

  // --- File readers ---
  if (head === "cat") {
    const p = singlePositional(tail, []);
    return p ? { type: "read", name: shortDisplayPath(p) } : { type: "run", cmd: "cat" };
  }
  if (head === "bat" || head === "batcat") {
    const p = singlePositional(tail, [
      "--theme",
      "--language",
      "--style",
      "--terminal-width",
      "--tabs",
      "--line-range",
      "--map-syntax",
    ]);
    return p ? { type: "read", name: shortDisplayPath(p) } : { type: "run", cmd: head };
  }
  if (head === "less") {
    const p = singlePositional(tail, [
      "-p",
      "-P",
      "-x",
      "-y",
      "-z",
      "-j",
      "--pattern",
      "--prompt",
      "--tabs",
      "--shift",
      "--jump-target",
    ]);
    return p ? { type: "read", name: shortDisplayPath(p) } : { type: "run", cmd: "less" };
  }
  if (head === "more") {
    const p = singlePositional(tail, []);
    return p ? { type: "read", name: shortDisplayPath(p) } : { type: "run", cmd: "more" };
  }

  // --- head with file ---
  if (head === "head") {
    const hasN =
      (tail[0] === "-n" && tail.length > 1 && /^\d+$/.test(tail[1])) ||
      (tail[0]?.startsWith("-n") && /^\d+$/.test(tail[0].slice(2)));
    if (hasN) {
      const skip = tail[0] === "-n" ? 2 : 1;
      const file = tail.slice(skip).find((p) => !p.startsWith("-"));
      if (file) return { type: "read", name: shortDisplayPath(file) };
    }
    if (tail.length === 1 && !tail[0].startsWith("-"))
      return { type: "read", name: shortDisplayPath(tail[0]) };
    return { type: "run", cmd: "head" };
  }

  // --- tail with file ---
  if (head === "tail") {
    const hasN = (() => {
      if (tail[0] === "-n" && tail.length > 1) {
        const s = tail[1].startsWith("+") ? tail[1].slice(1) : tail[1];
        return s.length > 0 && /^\d+$/.test(s);
      }
      if (tail[0]?.startsWith("-n")) {
        const v = tail[0].slice(2);
        const s = v.startsWith("+") ? v.slice(1) : v;
        return s.length > 0 && /^\d+$/.test(s);
      }
      return false;
    })();
    if (hasN) {
      const skip = tail[0] === "-n" ? 2 : 1;
      const file = tail.slice(skip).find((p) => !p.startsWith("-"));
      if (file) return { type: "read", name: shortDisplayPath(file) };
    }
    if (tail.length === 1 && !tail[0].startsWith("-"))
      return { type: "read", name: shortDisplayPath(tail[0]) };
    return { type: "run", cmd: "tail" };
  }

  // --- awk with file ---
  if (head === "awk") {
    const p = awkFileOperand(tail);
    return p ? { type: "read", name: shortDisplayPath(p) } : { type: "run", cmd: "awk" };
  }

  // --- nl with file ---
  if (head === "nl") {
    const file = skipFlagValues(tail, ["-s", "-w", "-v", "-i", "-b"]).find(
      (p) => !p.startsWith("-"),
    );
    return file ? { type: "read", name: shortDisplayPath(file) } : { type: "run", cmd: "nl" };
  }

  // --- sed -n range file ---
  if (head === "sed") {
    const p = sedReadPath(tail);
    return p ? { type: "read", name: shortDisplayPath(p) } : { type: "run", cmd: "sed" };
  }

  // --- python file-walk detection ---
  if (isPythonCmd(head)) {
    for (let idx = 0; idx < tail.length; idx++) {
      if (tail[idx] === "-c" && tail[idx + 1] && PYTHON_FILE_WALK_PATTERNS.test(tail[idx + 1]))
        return { type: "list", path: null };
    }
    return { type: "run", cmd: head };
  }

  // --- Fallback: use subcommand pattern for known CLIs ---
  if (SUBCOMMAND_COMMANDS.has(head)) {
    const sub = tail.find((w) => !w.startsWith("-"));
    return { type: "run", cmd: sub ? `${head} ${sub}` : head };
  }

  return { type: "run", cmd: head };
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

/** Parse a bash command string into a list of semantic ParsedBashCommands. */
export function parseBashCommand(command: string): ParsedBashCommand[] {
  const tokens = shellParse(command);

  // Split into statements on control operators (&&, ||, ;)
  const statements: Array<Array<string | { op: string }>> = [];
  let current: Array<string | { op: string }> = [];
  for (const tok of tokens) {
    if (typeof tok === "object" && "op" in tok && STATEMENT_SEPARATORS.has(tok.op)) {
      if (current.length > 0) {
        statements.push(current);
        current = [];
      }
      continue;
    }
    current.push(tok);
  }
  if (current.length > 0) statements.push(current);

  const results: ParsedBashCommand[] = [];

  for (const stmt of statements) {
    // Split into pipeline stages on |
    const stages: string[][] = [];
    let stageTokens: string[] = [];
    for (const tok of stmt) {
      if (typeof tok === "object" && "op" in tok) {
        if (tok.op === "|" && stageTokens.length > 0) {
          stages.push(stageTokens);
          stageTokens = [];
        }
        // Skip other operators (redirections etc.)
        continue;
      }
      if (typeof tok === "string") stageTokens.push(tok);
    }
    if (stageTokens.length > 0) stages.push(stageTokens);
    if (stages.length === 0) continue;

    // Filter formatting commands only from multi-stage pipelines
    const filtered = stages.length > 1 ? stages.filter((s) => !isFormattingCommand(s)) : stages;

    if (filtered.length === 0) {
      // All stages were formatting; classify first stage as fallback
      results.push(classifyCommand(stages[0]));
      continue;
    }

    // Drop ignored statements (cd, true, echo)
    const meaningful = filtered.filter((s) => s.length > 0 && !IGNORED_STATEMENTS.has(s[0]));
    if (meaningful.length === 0) continue;

    // Classify each remaining stage
    const classified = meaningful.map(classifyCommand);

    // If any stage is "run" in a multi-stage pipeline, collapse to single run
    if (classified.length > 1 && classified.some((c) => c.type === "run")) {
      const fullCmd = meaningful.map((s) => s.join(" ")).join(" | ");
      results.push({ type: "run", cmd: fullCmd });
    } else {
      results.push(...classified);
    }
  }

  // Dedup consecutive identical commands
  const deduped: ParsedBashCommand[] = [];
  for (const cmd of results) {
    const last = deduped.at(-1);
    if (last && last.type === cmd.type) {
      if (
        (cmd.type === "read" && last.type === "read" && cmd.name === last.name) ||
        (cmd.type === "list" && last.type === "list" && cmd.path === last.path) ||
        (cmd.type === "run" && last.type === "run" && cmd.cmd === last.cmd) ||
        (cmd.type === "search" &&
          last.type === "search" &&
          cmd.query === last.query &&
          cmd.path === last.path)
      )
        continue;
    }
    deduped.push(cmd);
  }

  return deduped;
}
