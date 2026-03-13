interface FilePathProps {
  path: string;
  expanded?: boolean;
  workDir?: string;
  className?: string;
  truncateFromStart?: boolean;
}

function toDisplayPath(path: string, workDir?: string): string {
  if (!workDir) return path;
  const normalized = workDir.endsWith("/") ? workDir : workDir + "/";
  if (path.startsWith(normalized)) {
    return path.slice(normalized.length);
  }
  return path;
}

function splitPath(display: string): { dir: string; name: string } {
  const idx = display.lastIndexOf("/");
  if (idx === -1) return { dir: "", name: display };
  return { dir: display.slice(0, idx + 1), name: display.slice(idx + 1) };
}

function FilePathContent({ display }: { display: string }): JSX.Element {
  const { dir, name } = splitPath(display);
  return (
    <>
      {dir ? <span className="text-neutral-500">{dir}</span> : null}
      <span className="text-neutral-600">{name}</span>
    </>
  );
}

// Shared file path display component.
// All file path references should use this so click-to-open can be added in one place.
export function FilePath({
  path,
  expanded = false,
  workDir,
  className,
  truncateFromStart = false,
}: FilePathProps): JSX.Element {
  const display = toDisplayPath(path, workDir);

  if (!expanded && truncateFromStart) {
    return (
      <code
        className={`inline-block max-w-full truncate rounded bg-surface px-1.5 py-0.5 text-left align-middle font-mono text-sm [direction:rtl] ${className ?? ""}`}
        title={path}
      >
        {display}
      </code>
    );
  }

  return (
    <code
      className={`inline-block max-w-full rounded bg-surface px-1.5 py-0.5 align-middle font-mono text-sm ${expanded ? "whitespace-pre-wrap break-words" : "truncate"} ${className ?? ""}`}
      title={path}
    >
      <FilePathContent display={display} />
    </code>
  );
}
