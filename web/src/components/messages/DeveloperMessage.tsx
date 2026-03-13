import { useState } from "react";

import type {
  DeveloperMessageItem,
  AtFileOp,
  DeveloperUIItem,
  TodoReminderUIItem,
} from "../../types/message";
import { buildFileApiUrl } from "../../api/client";
import { FilePath } from "./FilePath";

interface DeveloperMessageProps {
  items: DeveloperMessageItem[];
}

function PathPill({ path }: { path: string }): JSX.Element {
  return (
    <span className="inline-flex origin-left scale-[0.92] align-middle">
      <FilePath path={path} />
    </span>
  );
}

function plural(n: number, word: string): string {
  return n === 1 ? word : `${word}s`;
}

function groupAtFileOps(
  ops: AtFileOp[],
): Array<{ operation: string; mentionedIn: string | null; paths: string[] }> {
  const ordered: Array<{ operation: string; mentionedIn: string | null; paths: string[] }> = [];
  const idxByKey = new Map<string, number>();

  for (const op of ops) {
    const key = `${op.operation}\n${op.mentioned_in ?? ""}`;
    const existingIdx = idxByKey.get(key);
    if (existingIdx === undefined) {
      idxByKey.set(key, ordered.length);
      ordered.push({ operation: op.operation, mentionedIn: op.mentioned_in, paths: [op.path] });
    } else {
      ordered[existingIdx]!.paths.push(op.path);
    }
  }
  return ordered;
}

function collectImages(items: DeveloperUIItem[]): string[] {
  const paths: string[] = [];
  for (const it of items) {
    if (it.type === "at_file_images") {
      paths.push(...it.paths);
      continue;
    }
    if (it.type === "user_images") {
      paths.push(...it.paths);
    }
  }
  return paths;
}

function buildAttachedSummary(devItems: DeveloperMessageItem[]): string {
  let memoryCount = 0;
  const skillNames: string[] = [];
  let fileCount = 0;
  let folderListCount = 0;
  let rereadCount = 0;
  let imageCount = 0;

  for (const devItem of devItems) {
    for (const ui of devItem.items) {
      switch (ui.type) {
        case "memory_loaded":
          memoryCount += ui.files.length;
          break;
        case "skill_activated":
          skillNames.push(ui.name);
          break;
        case "at_file_ops":
          for (const op of ui.ops) {
            if (op.operation === "Read") fileCount++;
            else if (op.operation === "List") folderListCount++;
          }
          break;
        case "external_file_changes":
          rereadCount += ui.paths.length;
          break;
        case "user_images":
          imageCount += ui.count;
          break;
        case "at_file_images":
          imageCount += ui.paths.length;
          break;
        case "todo_reminder":
          break;
      }
    }
  }

  const parts: string[] = [];
  if (memoryCount > 0) parts.push(`${memoryCount} ${memoryCount === 1 ? "memory" : "memories"}`);
  for (const name of skillNames) parts.push(`skill:${name}`);
  if (fileCount > 0) parts.push(`${fileCount} ${plural(fileCount, "file")}`);
  if (folderListCount > 0)
    parts.push(`${folderListCount} folder ${plural(folderListCount, "list")}`);
  if (rereadCount > 0) parts.push(`${rereadCount} re-read ${plural(rereadCount, "file")}`);
  if (imageCount > 0) parts.push(`${imageCount} ${plural(imageCount, "image")}`);
  return parts.join(", ");
}

function CollapsibleRow({
  label,
  children,
  defaultOpen = false,
  labelClassName,
}: {
  label: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
  labelClassName?: string;
}): JSX.Element {
  const [open, setOpen] = useState(defaultOpen);
  const expandable = children !== null && children !== undefined;

  return (
    <div
      className={`grid grid-cols-[auto_1fr] items-start gap-x-1.5 font-mono text-sm leading-5 ${expandable ? "cursor-pointer" : "cursor-default"}`}
      onClick={() => expandable && setOpen((v) => !v)}
    >
      <div className="flex items-start gap-1.5 self-stretch">
        <div className="flex flex-col items-center self-stretch">
          <span
            className={`mt-0.5 font-mono text-xs text-neutral-500 ${!expandable ? "opacity-0" : ""}`}
          >
            {open ? "[-]" : "[+]"}
          </span>
          {open ? <div className="mt-1 w-px flex-1 bg-neutral-200" /> : null}
        </div>
        <span
          className={`whitespace-nowrap font-mono font-normal text-neutral-500 ${labelClassName ?? ""}`}
        >
          {label}
        </span>
      </div>

      <div className="min-w-0" />

      {expandable ? (
        <div
          className="col-span-2 grid transition-[grid-template-rows,opacity] duration-200 ease-in-out"
          style={{ gridTemplateRows: open ? "1fr" : "0fr", opacity: open ? 1 : 0 }}
        >
          <div className="overflow-hidden">
            <div className="mt-1 grid min-w-0 grid-cols-[16px_1fr] gap-x-1.5">
              <div className="flex justify-center">
                <div className="w-px bg-neutral-200" />
              </div>
              <div className="min-w-0 pb-1.5" onClick={(e) => e.stopPropagation()}>
                {children}
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function PathList({ paths }: { paths: string[] }): JSX.Element {
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm leading-6 marker:text-neutral-500">
      {paths.map((p) => (
        <li key={p}>
          <PathPill path={p} />
        </li>
      ))}
    </ul>
  );
}

function AttachDetail({
  devItems,
  images,
}: {
  devItems: DeveloperMessageItem[];
  images: string[];
}): JSX.Element {
  const allUIItems = devItems.flatMap((d) => d.items).filter((ui) => ui.type !== "todo_reminder");

  return (
    <div className="flex flex-col gap-1">
      {allUIItems.map((ui, idx) => {
        switch (ui.type) {
          case "memory_loaded":
            return <PathList key={`memory-${idx}`} paths={ui.files.map((f) => f.path)} />;
          case "external_file_changes":
            return <PathList key={`external-${idx}`} paths={ui.paths} />;
          case "at_file_ops":
            return groupAtFileOps(ui.ops).map((g) => (
              <div key={`${g.operation}-${g.mentionedIn ?? ""}-${g.paths.join(",")}`}>
                <PathList paths={g.paths} />
                {g.mentionedIn ? (
                  <div className="mt-0.5 text-sm leading-6">
                    <span className="mr-1 text-neutral-500">mentioned in</span>
                    <PathPill path={g.mentionedIn} />
                  </div>
                ) : null}
              </div>
            ));
          case "skill_activated":
          case "user_images":
          case "at_file_images":
            return null;
        }
      })}
      {images.length > 0 ? (
        <div className="mt-1 grid grid-cols-2 gap-2 sm:grid-cols-3">
          {images.map((p) => (
            <img
              key={p}
              src={buildFileApiUrl(p)}
              alt={p}
              className="block h-auto max-h-[220px] w-full rounded-md border border-neutral-200/70 bg-white object-contain"
              loading="lazy"
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function DeveloperMessage({ items }: DeveloperMessageProps): JSX.Element {
  const images = items.flatMap((d) => collectImages(d.items));
  const allUIItems = items.flatMap((d) => d.items);
  const todoItems = allUIItems.filter(
    (ui): ui is TodoReminderUIItem => ui.type === "todo_reminder",
  );
  const attachItems = allUIItems.filter((ui) => ui.type !== "todo_reminder");
  const hasAttachments = attachItems.length > 0 || images.length > 0;
  const summary = hasAttachments ? buildAttachedSummary(items) : "";

  return (
    <div className="flex flex-col font-sans text-sm text-neutral-500">
      {hasAttachments ? (
        <CollapsibleRow label={`Attached ${summary}`}>
          <AttachDetail devItems={items} images={images} />
        </CollapsibleRow>
      ) : null}
      {todoItems.map((todo, idx) => {
        const text =
          todo.reason === "empty" ? "Todo list is empty" : "Todo hasn't been updated recently";
        const labelClassName = todo.reason === "empty" ? "text-emerald-700" : "text-blue-700";
        return (
          <CollapsibleRow key={`todo-${idx}`} label={text} labelClassName={labelClassName}>
            {null}
          </CollapsibleRow>
        );
      })}
    </div>
  );
}
