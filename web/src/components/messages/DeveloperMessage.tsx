import { useState } from "react";
import { ChevronRight } from "lucide-react";

import type { DeveloperMessageItem, AtFileOp, DeveloperUIItem } from "../../types/message";
import { buildFileApiUrl } from "../../api/client";
import { FilePath } from "./FilePath";

interface DeveloperMessageProps {
  item: DeveloperMessageItem;
}

function PathPill({ path }: { path: string }): JSX.Element {
  return <FilePath path={path} />;
}

function plural(n: number, word: string): string {
  return n === 1 ? word : `${word}s`;
}

function groupAtFileOps(ops: AtFileOp[]): Array<{ operation: string; mentionedIn: string | null; paths: string[] }> {
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

function CollapsibleRow({
  label,
  children,
  defaultOpen = false,
}: {
  label: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}): JSX.Element {
  const [open, setOpen] = useState(defaultOpen);
  const expandable = children !== null && children !== undefined;

  return (
    <div
      className={`-my-1 grid grid-cols-[auto_1fr] gap-x-1.5 items-start text-[15px] font-mono ${expandable ? "cursor-pointer" : "cursor-default"}`}
      onClick={() => expandable && setOpen((v) => !v)}
    >
      <div className="flex items-start gap-1.5 self-stretch">
        <div className="flex flex-col items-center self-stretch">
          <ChevronRight
            className={`w-4 h-4 text-neutral-300 transition-transform duration-150 shrink-0 mt-0.5 ${open ? "rotate-90" : ""} ${!expandable ? "opacity-0" : ""}`}
          />
          {open ? <div className="w-px bg-neutral-200 flex-1 mt-1" /> : null}
        </div>
        <span className="font-normal text-neutral-500 whitespace-nowrap font-sans tracking-[0.03em]">{label}</span>
      </div>

      <div className="min-w-0" />

      {open ? (
        <div className="col-span-2 min-w-0 mt-0.5 grid grid-cols-[16px_1fr] gap-x-1.5">
          <div className="flex justify-center">
            <div className="w-px bg-neutral-200" />
          </div>
          <div className="min-w-0 pb-1" onClick={(e) => e.stopPropagation()}>
            {children}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function PathList({ paths }: { paths: string[] }): JSX.Element {
  return (
    <ul className="list-disc pl-5 space-y-0.5 marker:text-neutral-400 text-sm">
      {paths.map((p) => (
        <li key={p}>
          <PathPill path={p} />
        </li>
      ))}
    </ul>
  );
}

export function DeveloperMessage({ item }: DeveloperMessageProps): JSX.Element {
  const images = collectImages(item.items);

  return (
    <div className="flex flex-col gap-0.5 text-sm text-neutral-500 font-sans">
      {item.items.map((ui, idx) => {
        switch (ui.type) {
          case "memory_loaded":
            return (
              <CollapsibleRow key={`memory-${idx}`} label="Load memory">
                <PathList paths={ui.files.map((f) => f.path)} />
              </CollapsibleRow>
            );
          case "external_file_changes":
            return (
              <CollapsibleRow key={`external-${idx}`} label="Read after external changes">
                <PathList paths={ui.paths} />
              </CollapsibleRow>
            );
          case "todo_reminder": {
            const text = ui.reason === "empty" ? "Todo list is empty" : "Todo hasn't been updated recently";
            return (
              <CollapsibleRow key={`todo-${idx}`} label={text}>
                {null}
              </CollapsibleRow>
            );
          }
          case "at_file_ops":
            return groupAtFileOps(ui.ops).map((g) => (
              <CollapsibleRow
                key={`${g.operation}-${g.mentionedIn ?? ""}-${g.paths.join(",")}`}
                label={g.operation}
              >
                <div className="flex flex-col gap-0.5">
                  <PathList paths={g.paths} />
                  {g.mentionedIn ? (
                    <div className="text-sm">
                      <span className="mr-1">mentioned in</span>
                      <PathPill path={g.mentionedIn} />
                    </div>
                  ) : null}
                </div>
              </CollapsibleRow>
            ));
          case "user_images":
            return (
              <CollapsibleRow key={`images-${idx}`} label={`Attached ${ui.count} ${plural(ui.count, "image")}`}>
                {null}
              </CollapsibleRow>
            );
          case "skill_activated":
            return (
              <CollapsibleRow key={`skill-${idx}`} label={`Activated skill`}>
                <PathPill path={ui.name} />
              </CollapsibleRow>
            );
          case "at_file_images":
            return null;
        }
      })}

      {images.length > 0 ? (
        <div className="mt-2 grid grid-cols-2 sm:grid-cols-3 gap-2">
          {images.map((p) => (
            <img
              key={p}
              src={buildFileApiUrl(p)}
              alt={p}
              className="block w-full h-auto max-h-[220px] object-contain rounded-md border border-neutral-200/70 bg-white"
              loading="lazy"
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}
