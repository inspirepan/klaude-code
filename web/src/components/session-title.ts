/** Extract the last path segment from a work directory path. */
export function workDirLabel(workDir: string): string {
  const parts = workDir.split("/").filter((segment) => segment.length > 0);
  return parts[parts.length - 1] ?? workDir;
}

export function splitSessionTitle(title: string): { primary: string; secondary: string | null } {
  const separator = " — ";
  const separatorIndex = title.indexOf(separator);
  if (separatorIndex === -1) {
    return { primary: title, secondary: null };
  }
  return {
    primary: title.slice(0, separatorIndex),
    secondary: title.slice(separatorIndex + separator.length),
  };
}
