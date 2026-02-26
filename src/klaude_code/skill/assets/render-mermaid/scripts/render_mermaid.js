#!/usr/bin/env bun

import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const MERMAID_PACKAGE = "beautiful-mermaid";

function fail(message) {
  console.error(`RENDER_FAILED: ${message}`);
  process.exit(1);
}

function parseArgs(argv) {
  const args = { mermaid: "", output: "", help: false };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--help" || arg === "-h") {
      args.help = true;
      continue;
    }
    if (arg === "--mermaid") {
      args.mermaid = argv[i + 1] ?? "";
      i += 1;
      continue;
    }
    if (arg === "--output") {
      args.output = argv[i + 1] ?? "";
      i += 1;
    }
  }

  return args;
}

const { mermaid, output, help } = parseArgs(process.argv.slice(2));

if (help) {
  console.log(`Usage:
  bun scripts/render_mermaid.js --output <OUTPUT_PATH>.svg <<'MERMAID'
  flowchart TD
    A[Start] --> B[End]
  MERMAID

Options:
  --output <path.svg>  Required. Output SVG path.
  --mermaid <text>     Optional. Mermaid text (stdin is preferred).
  --help, -h           Show this help message.
`);
  process.exit(0);
}

async function readMermaidFromStdin() {
  if (process.stdin.isTTY) {
    return "";
  }

  return await readFile(0, "utf8");
}

const mermaidInput = mermaid || (await readMermaidFromStdin());

if (!mermaidInput.trim()) {
  fail("missing Mermaid input: pass --mermaid or provide content via stdin");
}

if (!output) {
  fail("missing required argument --output");
}

const outputPath = path.resolve(output);
if (path.extname(outputPath).toLowerCase() !== ".svg") {
  fail("output must end with .svg");
}

let renderMermaidSVG;
try {
  ({ renderMermaidSVG } = await import(MERMAID_PACKAGE));
} catch (error) {
  fail(`failed to load ${MERMAID_PACKAGE}: ${error instanceof Error ? error.message : String(error)}`);
}

if (typeof renderMermaidSVG !== "function") {
  fail("renderMermaidSVG is not available in library");
}

try {
  const svg = renderMermaidSVG(mermaidInput);
  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, svg, "utf8");
  console.log(`RENDER_SUCCESS: ${outputPath}`);
} catch (error) {
  fail(`render failed: ${error instanceof Error ? error.message : String(error)}`);
}
