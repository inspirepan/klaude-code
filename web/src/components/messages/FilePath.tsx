import { toDisplayPath } from "./file-path-utils";

interface FilePathProps {
  path: string;
  workDir?: string;
  className?: string;
  truncateFromStart?: boolean;
}

function splitPath(display: string): { dir: string; name: string } {
  const idx = display.lastIndexOf("/");
  if (idx === -1) return { dir: "", name: display };
  return { dir: display.slice(0, idx + 1), name: display.slice(idx + 1) };
}

export function FilePathContent({ display }: { display: string }): React.JSX.Element {
  const { dir, name } = splitPath(display);
  return (
    <>
      {dir ? <span className="text-neutral-500">{dir}</span> : null}
      <span className="text-neutral-700">{name}</span>
    </>
  );
}

// Shared file path display component.
// All file path references should use this so click-to-open can be added in one place.
export function FilePath({
  path,
  workDir,
  className,
  truncateFromStart = false,
}: FilePathProps): React.JSX.Element {
  const display = toDisplayPath(path, workDir);

  if (truncateFromStart) {
    return (
      <code
        className={`inline-block max-w-full truncate rounded bg-surface px-1.5 py-0.5 text-left align-middle font-mono text-sm leading-5 [direction:rtl] ${className ?? ""}`}
        title={path}
      >
        {display}
      </code>
    );
  }

  return (
    <code
      className={`inline-block max-w-full truncate rounded bg-surface px-1.5 py-0.5 align-middle font-mono text-sm leading-5 ${className ?? ""}`}
      title={path}
    >
      <FilePathContent display={display} />
    </code>
  );
}
