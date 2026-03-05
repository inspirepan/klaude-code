import type { DeveloperMessageItem, AtFileOp, DeveloperUIItem } from "../../types/message";
import { buildFileApiUrl } from "../../api/client";

interface DeveloperMessageProps {
  item: DeveloperMessageItem;
}

function PathPill({ path }: { path: string }): JSX.Element {
  const classes = "font-mono text-xs text-neutral-400 bg-neutral-100 border border-neutral-200/70 rounded px-1.5 py-0.5";
  return (
    <code className={classes} title={path}>
      {path}
    </code>
  );
}

function Row({ children }: { children: React.ReactNode }): JSX.Element {
  return (
    <div className="grid grid-cols-[14px_1fr] gap-x-2 items-start">
      <span className="text-neutral-400 font-mono leading-6 select-none">+</span>
      <div className="min-w-0 leading-6">{children}</div>
    </div>
  );
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

export function DeveloperMessage({ item }: DeveloperMessageProps): JSX.Element {
  const images = collectImages(item.items);

  return (
    <div className="rounded-lg border border-neutral-200/80 bg-neutral-50/40 px-3.5 py-2.5 text-[15px]">
      <div className="flex flex-col gap-0.5 text-sm text-neutral-500 font-sans">
        {item.items.map((ui, idx) => {
          switch (ui.type) {
            case "memory_loaded":
              return (
                <Row key={`memory-${idx}`}>
                  <div className="flex flex-col gap-0.5">
                    <span>Load memory</span>
                    <ul className="list-disc pl-5 space-y-0.5 marker:text-neutral-400">
                      {ui.files.map((f) => (
                        <li key={f.path}>
                          <PathPill path={f.path} />
                        </li>
                      ))}
                    </ul>
                  </div>
                </Row>
              );
            case "external_file_changes":
              return (
                <Row key={`external-${idx}`}>
                  <div className="flex flex-col gap-0.5">
                    <span>Read after external changes</span>
                    <ul className="list-disc pl-5 space-y-0.5 marker:text-neutral-400">
                      {ui.paths.map((p) => (
                        <li key={p}>
                          <PathPill path={p} />
                        </li>
                      ))}
                    </ul>
                  </div>
                </Row>
              );
            case "todo_reminder": {
              const text = ui.reason === "empty" ? "Todo list is empty" : "Todo hasn't been updated recently";
              return (
                <Row key={`todo-${idx}`}>
                  <span>{text}</span>
                </Row>
              );
            }
            case "at_file_ops":
              return (
                <div key={`ops-${idx}`} className="flex flex-col gap-0.5">
                  {groupAtFileOps(ui.ops).map((g) => (
                    <Row key={`${g.operation}-${g.mentionedIn ?? ""}-${g.paths.join(",")}`}>
                      <div className="flex flex-col gap-0.5">
                        <span>{g.operation}</span>
                        <ul className="list-disc pl-5 space-y-0.5 marker:text-neutral-400">
                          {g.paths.map((p) => (
                            <li key={p}>
                              <PathPill path={p} />
                            </li>
                          ))}
                        </ul>
                        {g.mentionedIn ? (
                          <div>
                            <span className="mr-1">mentioned in</span>
                            <PathPill path={g.mentionedIn} />
                          </div>
                        ) : null}
                      </div>
                    </Row>
                  ))}
                </div>
              );
            case "user_images":
              return (
                <Row key={`images-${idx}`}>
                  <span>
                    Attached {ui.count} {plural(ui.count, "image")}
                  </span>
                </Row>
              );
            case "skill_activated":
              return (
                <Row key={`skill-${idx}`}>
                  <span className="mr-1">Activated skill</span>
                  <PathPill path={ui.name} />
                </Row>
              );
            case "at_file_images":
              // Image-only: displayed below.
              return null;
          }
        })}
      </div>

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
