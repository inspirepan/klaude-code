interface FilePathProps {
  path: string;
  expanded?: boolean;
}

// Shared file path display component.
// All file path references should use this so click-to-open can be added in one place.
export function FilePath({ path, expanded = false }: FilePathProps): JSX.Element {
  return (
    <code
      className={`inline-block max-w-full align-middle font-mono text-sm text-neutral-400 bg-neutral-100 rounded px-1.5 py-0.5 ${expanded ? "whitespace-pre-wrap break-words" : "truncate"}`}
      title={path}
    >
      {path}
    </code>
  );
}
