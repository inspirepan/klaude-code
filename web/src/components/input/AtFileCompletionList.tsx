import { useEffect, useRef } from "react";
import type { LucideIcon } from "lucide-react";
import {
  File,
  FileCode,
  FileCog,
  FileImage,
  FileJson,
  FileTerminal,
  FileText,
  FileType,
  Folder,
} from "lucide-react";

import { ScrollArea } from "@/components/ui/scroll-area";

// File extension -> icon + color mapping (muted brand colors)
const EXT_ICONS: Record<string, { icon: LucideIcon; color: string }> = {
  // TypeScript / JavaScript
  ts: { icon: FileCode, color: "#3178c6" },
  tsx: { icon: FileCode, color: "#3178c6" },
  mts: { icon: FileCode, color: "#3178c6" },
  cts: { icon: FileCode, color: "#3178c6" },
  js: { icon: FileCode, color: "#e8a32e" },
  jsx: { icon: FileCode, color: "#e8a32e" },
  mjs: { icon: FileCode, color: "#e8a32e" },
  cjs: { icon: FileCode, color: "#e8a32e" },
  // Python
  py: { icon: FileCode, color: "#3572a5" },
  pyi: { icon: FileCode, color: "#3572a5" },
  pyx: { icon: FileCode, color: "#3572a5" },
  // Go
  go: { icon: FileCode, color: "#00add8" },
  // Rust
  rs: { icon: FileCode, color: "#dea584" },
  // Ruby
  rb: { icon: FileCode, color: "#cc342d" },
  // Java / Kotlin
  java: { icon: FileCode, color: "#b07219" },
  kt: { icon: FileCode, color: "#a97bff" },
  kts: { icon: FileCode, color: "#a97bff" },
  // C / C++ / C#
  c: { icon: FileCode, color: "#555d6b" },
  h: { icon: FileCode, color: "#555d6b" },
  cpp: { icon: FileCode, color: "#f34b7d" },
  hpp: { icon: FileCode, color: "#f34b7d" },
  cc: { icon: FileCode, color: "#f34b7d" },
  cs: { icon: FileCode, color: "#68217a" },
  // Swift
  swift: { icon: FileCode, color: "#f05138" },
  // PHP
  php: { icon: FileCode, color: "#777bb4" },
  // Lua
  lua: { icon: FileCode, color: "#000080" },
  // Shell
  sh: { icon: FileTerminal, color: "#4eaa25" },
  bash: { icon: FileTerminal, color: "#4eaa25" },
  zsh: { icon: FileTerminal, color: "#4eaa25" },
  fish: { icon: FileTerminal, color: "#4eaa25" },
  // HTML
  html: { icon: FileCode, color: "#e44d26" },
  htm: { icon: FileCode, color: "#e44d26" },
  // CSS / Styles
  css: { icon: FileType, color: "#563d7c" },
  scss: { icon: FileType, color: "#c6538c" },
  sass: { icon: FileType, color: "#c6538c" },
  less: { icon: FileType, color: "#1d365d" },
  // Vue / Svelte
  vue: { icon: FileCode, color: "#41b883" },
  svelte: { icon: FileCode, color: "#ff3e00" },
  // Data / Config (structured)
  json: { icon: FileJson, color: "#e8a32e" },
  jsonc: { icon: FileJson, color: "#e8a32e" },
  json5: { icon: FileJson, color: "#e8a32e" },
  yaml: { icon: FileCog, color: "#cb171e" },
  yml: { icon: FileCog, color: "#cb171e" },
  toml: { icon: FileCog, color: "#9c4121" },
  ini: { icon: FileCog, color: "#6d8086" },
  env: { icon: FileCog, color: "#6d8086" },
  // Markdown / Text
  md: { icon: FileText, color: "#083fa1" },
  mdx: { icon: FileText, color: "#083fa1" },
  txt: { icon: FileText, color: "#6d8086" },
  rst: { icon: FileText, color: "#6d8086" },
  // Images
  png: { icon: FileImage, color: "#a074c4" },
  jpg: { icon: FileImage, color: "#a074c4" },
  jpeg: { icon: FileImage, color: "#a074c4" },
  gif: { icon: FileImage, color: "#a074c4" },
  svg: { icon: FileImage, color: "#e8a32e" },
  webp: { icon: FileImage, color: "#a074c4" },
  ico: { icon: FileImage, color: "#a074c4" },
  // SQL
  sql: { icon: FileCode, color: "#e38c00" },
  // GraphQL
  graphql: { icon: FileCode, color: "#e10098" },
  gql: { icon: FileCode, color: "#e10098" },
  // Dart
  dart: { icon: FileCode, color: "#00b4ab" },
  // R
  r: { icon: FileCode, color: "#276dc3" },
  // Elixir / Erlang
  ex: { icon: FileCode, color: "#6e4a7e" },
  exs: { icon: FileCode, color: "#6e4a7e" },
  erl: { icon: FileCode, color: "#b83998" },
  // Zig
  zig: { icon: FileCode, color: "#f7a41d" },
  // Scala
  scala: { icon: FileCode, color: "#dc322f" },
  // Haskell
  hs: { icon: FileCode, color: "#5e5086" },
  // Proto
  proto: { icon: FileCode, color: "#6d8086" },
};

// Special full-filename matches (e.g. Dockerfile, Makefile)
const NAME_ICONS: Record<string, { icon: LucideIcon; color: string }> = {
  dockerfile: { icon: FileCog, color: "#2496ed" },
  makefile: { icon: FileCog, color: "#6d8086" },
  justfile: { icon: FileCog, color: "#6d8086" },
  rakefile: { icon: FileCog, color: "#cc342d" },
  gemfile: { icon: FileCog, color: "#cc342d" },
  cmakelists: { icon: FileCog, color: "#6d8086" },
};

function getFileIcon(filename: string): { Icon: LucideIcon; color: string } {
  // Check full filename (case-insensitive, without extension)
  const baseName = filename.includes(".") ? filename.slice(0, filename.lastIndexOf(".")) : filename;
  const nameMatch = NAME_ICONS[baseName.toLowerCase()];
  if (nameMatch) return { Icon: nameMatch.icon, color: nameMatch.color };

  // Also check full filename for extensionless files like "Dockerfile"
  const fullMatch = NAME_ICONS[filename.toLowerCase()];
  if (fullMatch) return { Icon: fullMatch.icon, color: fullMatch.color };

  // Check extension
  const dotIndex = filename.lastIndexOf(".");
  if (dotIndex >= 0) {
    const ext = filename.slice(dotIndex + 1).toLowerCase();
    const extMatch = EXT_ICONS[ext];
    if (extMatch) return { Icon: extMatch.icon, color: extMatch.color };
  }

  return { Icon: File, color: "#9ca3af" };
}

interface AtFileCompletionListProps {
  items: string[];
  loading: boolean;
  highlightIndex: number;
  onHighlightIndexChange: (index: number) => void;
  onSelect: (path: string) => void;
  dropUp?: boolean;
}

function getFileCompletionDisplay(path: string): {
  name: string;
  parent: string | null;
  isDirectory: boolean;
} {
  const isDirectory = path.endsWith("/");
  const strippedPath = isDirectory ? path.slice(0, -1) : path;
  const lastSlash = strippedPath.lastIndexOf("/");
  const name = `${lastSlash >= 0 ? strippedPath.slice(lastSlash + 1) : strippedPath}${isDirectory ? "/" : ""}`;
  const parent = lastSlash >= 0 ? `${strippedPath.slice(0, lastSlash)}/` : null;
  return { name, parent, isDirectory };
}

export function AtFileCompletionList({
  items,
  loading,
  highlightIndex,
  onHighlightIndexChange,
  onSelect,
  dropUp = true,
}: AtFileCompletionListProps): JSX.Element {
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const path = items[highlightIndex];
    if (!path || !listRef.current) {
      return;
    }
    const item = listRef.current.querySelector(`[data-file-completion="${CSS.escape(path)}"]`);
    item?.scrollIntoView({ block: "nearest" });
  }, [highlightIndex, items]);

  return (
    <div className={`absolute left-0 right-0 z-20 overflow-hidden rounded-lg border border-neutral-200/80 bg-white shadow-[0_4px_16px_rgba(0,0,0,0.08)] ${dropUp ? "bottom-full mb-1.5" : "top-full mt-1.5"}`}>
      <ScrollArea ref={listRef} className="w-full pb-1.5 pt-2" viewportClassName="max-h-72" type="hover">
        {items.map((path, index) => {
          const highlighted = index === highlightIndex;
          const display = getFileCompletionDisplay(path);
          const { Icon: FileIcon, color: iconColor } = display.isDirectory
            ? { Icon: Folder, color: undefined }
            : getFileIcon(display.name);
          return (
            <button
              key={path}
              data-file-completion={path}
              type="button"
              className={[
                "ml-2 mr-2.5 flex w-[calc(100%-1.125rem)] items-center gap-2.5 rounded-md px-2 py-1.5 text-left transition-colors",
                highlighted ? "bg-muted text-neutral-900" : "text-neutral-600 hover:bg-surface",
              ].join(" ")}
              onMouseDown={(event) => {
                event.preventDefault();
              }}
              onPointerEnter={() => {
                onHighlightIndexChange(index);
              }}
              onClick={() => {
                onSelect(path);
              }}
            >
              <FileIcon
                className="h-4 w-4 shrink-0"
                style={iconColor ? { color: iconColor } : undefined}
              />
              <span className="min-w-0 flex-1 truncate text-base leading-6">
                <span className="text-neutral-500">{display.parent ?? ""}</span>
                <span className="text-neutral-700">{display.name}</span>
              </span>
            </button>
          );
        })}
        {loading && items.length === 0 ? (
          <div className="px-2.5 py-1.5 text-base text-neutral-500">Searching files…</div>
        ) : null}
      </ScrollArea>
    </div>
  );
}
