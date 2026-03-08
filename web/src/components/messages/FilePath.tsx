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
  const lastSlashIndex = display.lastIndexOf("/");
  const hasParentPath = lastSlashIndex > 0;
  const parentPath = hasParentPath ? display.slice(0, lastSlashIndex + 1) : "";
  const fileName = hasParentPath ? display.slice(lastSlashIndex + 1) : display;

  if (!expanded && truncateFromStart && hasParentPath) {
    return (
      <code
        className={`inline-flex min-w-0 max-w-full items-baseline rounded bg-neutral-100 px-1.5 py-0.5 align-middle font-mono text-sm text-neutral-400 ${className ?? ""}`}
        title={path}
      >
        <span className="min-w-0 truncate">{parentPath}</span>
        <span className="shrink-0">{fileName}</span>
      </code>
    );
  }

  return (
    <code
      className={`inline-block max-w-full rounded bg-neutral-100 px-1.5 py-0.5 align-middle font-mono text-sm text-neutral-400 ${expanded ? "whitespace-pre-wrap break-words" : "truncate"} ${className ?? ""}`}
      title={path}
    >
      {display}
    </code>
  );
}
