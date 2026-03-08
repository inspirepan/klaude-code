interface FilePathProps {
  path: string;
  expanded?: boolean;
  workDir?: string;
  className?: string;
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
}: FilePathProps): JSX.Element {
  const display = toDisplayPath(path, workDir);
  return (
    <code
      className={`inline-block max-w-full rounded bg-neutral-100 px-1.5 py-0.5 align-middle font-mono text-sm text-neutral-400 ${expanded ? "whitespace-pre-wrap break-words" : "truncate"} ${className ?? ""}`}
      title={path}
    >
      {display}
    </code>
  );
}
