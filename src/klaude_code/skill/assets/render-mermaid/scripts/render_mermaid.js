#!/usr/bin/env bun

import { access, mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const MERMAID_PACKAGE = "beautiful-mermaid";
const PUPPETEER_PACKAGE = "puppeteer-core";
const SKILL_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DEPENDENCIES = [MERMAID_PACKAGE, PUPPETEER_PACKAGE];

const DEFAULT_CHROME_PATHS = [
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium-browser",
  "/usr/bin/chromium",
];

function fail(message) {
  console.error(`RENDER_FAILED: ${message}`);
  process.exit(1);
}

function isMissingPackageError(error) {
  const message = error instanceof Error ? error.message : String(error);
  return message.includes("Cannot find package") || message.includes("Cannot find module");
}

function installHint(packageName) {
  return `missing dependency \"${packageName}\": run \"cd ${SKILL_DIR} && bun install\" and retry`;
}

function installAllHint() {
  return `run \"cd ${SKILL_DIR} && bun install\" and retry`;
}

async function assertDependenciesInstalled() {
  const missing = [];
  for (const dep of DEPENDENCIES) {
    const packageJsonPath = path.join(SKILL_DIR, "node_modules", dep, "package.json");
    try {
      await access(packageJsonPath);
    } catch {
      missing.push(dep);
    }
  }

  if (missing.length > 0) {
    fail(`dependencies not installed (${missing.join(", ")}): ${installAllHint()}`);
  }
}

function formatLoadFailure(packageName, error) {
  const message = error instanceof Error ? error.message : String(error);
  return `failed to load ${packageName}: ${message}. If this is first use (or dependencies changed), ${installAllHint()}`;
}

function parseArgs(argv) {
  const args = { mermaid: "", output: "", chromePath: "", help: false };

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
      continue;
    }
    if (arg === "--chrome-path") {
      args.chromePath = argv[i + 1] ?? "";
      i += 1;
    }
  }

  return args;
}

const { mermaid, output, chromePath, help } = parseArgs(process.argv.slice(2));

if (help) {
  console.log(`Usage:
  bun scripts/render_mermaid.js --output <OUTPUT_PATH>.png <<'MERMAID'
  flowchart TD
    A[Start] --> B[End]
  MERMAID

  node scripts/render_mermaid.js --output <OUTPUT_PATH>.png <<'MERMAID'
  flowchart TD
    A[Start] --> B[End]
  MERMAID

Options:
  --output <path.png>  Required. Output PNG path.
  --mermaid <text>     Optional. Mermaid text (stdin is preferred).
  --chrome-path <path> Optional. Chrome/Chromium executable path.
  --help, -h           Show this help message.
`);
  process.exit(0);
}

async function resolveChromePath(explicitPath) {
  const candidates = [
    explicitPath,
    process.env.PUPPETEER_EXECUTABLE_PATH,
    process.env.CHROME_PATH,
    ...DEFAULT_CHROME_PATHS,
  ].filter(Boolean);

  for (const candidate of candidates) {
    try {
      await access(candidate);
      return candidate;
    } catch {
      // Ignore missing paths and continue searching.
    }
  }

  return "";
}

async function readMermaidFromStdin() {
  if (process.stdin.isTTY) {
    return "";
  }

  process.stdin.setEncoding("utf8");
  let content = "";
  for await (const chunk of process.stdin) {
    content += chunk;
  }
  return content;
}

const mermaidInput = mermaid || (await readMermaidFromStdin());

if (!mermaidInput.trim()) {
  fail("missing Mermaid input: pass --mermaid or provide content via stdin");
}

if (!output) {
  fail("missing required argument --output");
}

const outputPath = path.resolve(output);
if (path.extname(outputPath).toLowerCase() !== ".png") {
  fail("output must end with .png");
}

await assertDependenciesInstalled();

let renderMermaidSVG;
try {
  ({ renderMermaidSVG } = await import(MERMAID_PACKAGE));
} catch (error) {
  if (isMissingPackageError(error)) {
    fail(installHint(MERMAID_PACKAGE));
  }
  fail(formatLoadFailure(MERMAID_PACKAGE, error));
}

if (typeof renderMermaidSVG !== "function") {
  fail("renderMermaidSVG is not available in library");
}

let puppeteer;
try {
  ({ default: puppeteer } = await import(PUPPETEER_PACKAGE));
} catch (error) {
  if (isMissingPackageError(error)) {
    fail(installHint(PUPPETEER_PACKAGE));
  }
  fail(formatLoadFailure(PUPPETEER_PACKAGE, error));
}

const chromeExecutablePath = await resolveChromePath(chromePath);
if (!chromeExecutablePath) {
  fail("missing Chrome/Chromium executable: pass --chrome-path or set CHROME_PATH");
}

try {
  const svg = renderMermaidSVG(mermaidInput);
  await mkdir(path.dirname(outputPath), { recursive: true });

  const browser = await puppeteer.launch({
    headless: true,
    executablePath: chromeExecutablePath,
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 2048, height: 2048, deviceScaleFactor: 2 });
    await page.setContent(
      `<!doctype html><html><head><meta charset="utf-8"></head><body style="margin:0;background:#FFFFFF">${svg}</body></html>`,
      { waitUntil: "networkidle0" },
    );
    await page.evaluate(() => document.fonts?.ready ?? Promise.resolve());

    const svgElement = await page.$("svg");
    if (!svgElement) {
      throw new Error("rendered SVG is missing in page");
    }
    await svgElement.screenshot({ path: outputPath, type: "png", omitBackground: false });
  } finally {
    await browser.close();
  }

  console.log(`RENDER_SUCCESS: ${outputPath}`);
} catch (error) {
  fail(`render failed: ${error instanceof Error ? error.message : String(error)}`);
}
