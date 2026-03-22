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

import { CommandListPanel, CommandListScroll, CommandListItem } from "@/components/ui/command-list";
import { useT } from "@/i18n";

// File extension -> icon + color mapping (muted brand colors)
const EXT_ICONS: Record<string, { icon: LucideIcon; color: string }> = {
  ts: { icon: FileCode, color: "#3178c6" },
  tsx: { icon: FileCode, color: "#3178c6" },
  mts: { icon: FileCode, color: "#3178c6" },
  cts: { icon: FileCode, color: "#3178c6" },
  js: { icon: FileCode, color: "#e8a32e" },
  jsx: { icon: FileCode, color: "#e8a32e" },
  mjs: { icon: FileCode, color: "#e8a32e" },
  cjs: { icon: FileCode, color: "#e8a32e" },
  py: { icon: FileCode, color: "#3572a5" },
  pyi: { icon: FileCode, color: "#3572a5" },
  pyx: { icon: FileCode, color: "#3572a5" },
  go: { icon: FileCode, color: "#00add8" },
  rs: { icon: FileCode, color: "#dea584" },
  rb: { icon: FileCode, color: "#cc342d" },
  java: { icon: FileCode, color: "#b07219" },
  kt: { icon: FileCode, color: "#a97bff" },
  kts: { icon: FileCode, color: "#a97bff" },
  c: { icon: FileCode, color: "#555d6b" },
  h: { icon: FileCode, color: "#555d6b" },
  cpp: { icon: FileCode, color: "#f34b7d" },
  hpp: { icon: FileCode, color: "#f34b7d" },
  cc: { icon: FileCode, color: "#f34b7d" },
  cs: { icon: FileCode, color: "#68217a" },
  swift: { icon: FileCode, color: "#f05138" },
  php: { icon: FileCode, color: "#777bb4" },
  lua: { icon: FileCode, color: "#000080" },
  sh: { icon: FileTerminal, color: "#4eaa25" },
  bash: { icon: FileTerminal, color: "#4eaa25" },
  zsh: { icon: FileTerminal, color: "#4eaa25" },
  fish: { icon: FileTerminal, color: "#4eaa25" },
  html: { icon: FileCode, color: "#e44d26" },
  htm: { icon: FileCode, color: "#e44d26" },
  css: { icon: FileType, color: "#563d7c" },
  scss: { icon: FileType, color: "#c6538c" },
  sass: { icon: FileType, color: "#c6538c" },
  less: { icon: FileType, color: "#1d365d" },
  vue: { icon: FileCode, color: "#41b883" },
  svelte: { icon: FileCode, color: "#ff3e00" },
  json: { icon: FileJson, color: "#e8a32e" },
  jsonc: { icon: FileJson, color: "#e8a32e" },
  json5: { icon: FileJson, color: "#e8a32e" },
  yaml: { icon: FileCog, color: "#cb171e" },
  yml: { icon: FileCog, color: "#cb171e" },
  toml: { icon: FileCog, color: "#9c4121" },
  ini: { icon: FileCog, color: "#6d8086" },
  env: { icon: FileCog, color: "#6d8086" },
  md: { icon: FileText, color: "#083fa1" },
  mdx: { icon: FileText, color: "#083fa1" },
  txt: { icon: FileText, color: "#6d8086" },
  rst: { icon: FileText, color: "#6d8086" },
  png: { icon: FileImage, color: "#a074c4" },
  jpg: { icon: FileImage, color: "#a074c4" },
  jpeg: { icon: FileImage, color: "#a074c4" },
  gif: { icon: FileImage, color: "#a074c4" },
  svg: { icon: FileImage, color: "#e8a32e" },
  webp: { icon: FileImage, color: "#a074c4" },
  ico: { icon: FileImage, color: "#a074c4" },
  sql: { icon: FileCode, color: "#e38c00" },
  graphql: { icon: FileCode, color: "#e10098" },
  gql: { icon: FileCode, color: "#e10098" },
  dart: { icon: FileCode, color: "#00b4ab" },
  r: { icon: FileCode, color: "#276dc3" },
  ex: { icon: FileCode, color: "#6e4a7e" },
  exs: { icon: FileCode, color: "#6e4a7e" },
  erl: { icon: FileCode, color: "#b83998" },
  zig: { icon: FileCode, color: "#f7a41d" },
  scala: { icon: FileCode, color: "#dc322f" },
  hs: { icon: FileCode, color: "#5e5086" },
  proto: { icon: FileCode, color: "#6d8086" },
};

const NAME_ICONS: Record<string, { icon: LucideIcon; color: string }> = {
  dockerfile: { icon: FileCog, color: "#2496ed" },
  makefile: { icon: FileCog, color: "#6d8086" },
  justfile: { icon: FileCog, color: "#6d8086" },
  rakefile: { icon: FileCog, color: "#cc342d" },
  gemfile: { icon: FileCog, color: "#cc342d" },
  cmakelists: { icon: FileCog, color: "#6d8086" },
};

function getFileIcon(filename: string): { Icon: LucideIcon; color: string } {
  const baseName = filename.includes(".") ? filename.slice(0, filename.lastIndexOf(".")) : filename;
  const nameMatch = NAME_ICONS[baseName.toLowerCase()];
  if (nameMatch) return { Icon: nameMatch.icon, color: nameMatch.color };

  const fullMatch = NAME_ICONS[filename.toLowerCase()];
  if (fullMatch) return { Icon: fullMatch.icon, color: fullMatch.color };

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
  const t = useT();
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
    <CommandListPanel
      className={`absolute left-0 right-0 z-20 shadow-float ${dropUp ? "bottom-full mb-1.5" : "top-full mt-1.5"}`}
    >
      <CommandListScroll ref={listRef}>
        {items.map((path, index) => {
          const display = getFileCompletionDisplay(path);
          const { Icon: FileIcon, color: iconColor } = display.isDirectory
            ? { Icon: Folder, color: undefined }
            : getFileIcon(display.name);
          return (
            <CommandListItem
              key={path}
              data-file-completion={path}
              highlighted={index === highlightIndex}
              onPointerEnter={() => onHighlightIndexChange(index)}
              onClick={() => onSelect(path)}
            >
              <FileIcon
                className="h-4 w-4 shrink-0"
                style={iconColor ? { color: iconColor } : undefined}
              />
              <span className="min-w-0 flex-1 truncate">
                <span className="text-neutral-500">{display.parent ?? ""}</span>
                <span className="text-neutral-700">{display.name}</span>
              </span>
            </CommandListItem>
          );
        })}
        {loading && items.length === 0 ? (
          <div className="px-3 py-1.5 text-sm text-neutral-500">{t("fileSearch.searching")}</div>
        ) : null}
      </CommandListScroll>
    </CommandListPanel>
  );
}
