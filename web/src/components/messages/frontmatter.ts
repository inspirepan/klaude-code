import { useMemo } from "react";

interface FrontmatterEntry {
  key: string;
  value: string;
}

export interface ParsedFrontmatter {
  entries: FrontmatterEntry[] | null;
  body: string;
}

/** Parse YAML frontmatter delimited by `---` at the start of markdown content. */
export function parseFrontmatter(content: string): ParsedFrontmatter {
  const trimmed = content.trimStart();
  if (!trimmed.startsWith("---")) return { entries: null, body: content };

  const afterFirst = trimmed.indexOf("\n");
  if (afterFirst === -1) return { entries: null, body: content };

  const closingIdx = trimmed.indexOf("\n---", afterFirst);
  if (closingIdx === -1) return { entries: null, body: content };

  const yamlBlock = trimmed.slice(afterFirst + 1, closingIdx);
  const rest = trimmed.slice(closingIdx + 4);
  const body = rest.replace(/^\r?\n/, "");

  const entries: FrontmatterEntry[] = [];
  let currentKey = "";
  let currentValue = "";

  for (const line of yamlBlock.split("\n")) {
    const match = line.match(/^(\w[\w\s-]*):\s*(.*)/);
    if (match) {
      if (currentKey) entries.push({ key: currentKey, value: currentValue.trim() });
      currentKey = match[1].trim();
      currentValue = match[2];
    } else if (currentKey) {
      currentValue += " " + line.trim();
    }
  }
  if (currentKey) entries.push({ key: currentKey, value: currentValue.trim() });

  if (entries.length === 0) return { entries: null, body: content };
  return { entries, body };
}

export function useParsedFrontmatter(content: string): ParsedFrontmatter {
  return useMemo(() => parseFrontmatter(content), [content]);
}
