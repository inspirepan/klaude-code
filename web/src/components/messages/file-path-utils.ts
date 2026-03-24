export function toDisplayPath(path: string, workDir?: string): string {
  if (!workDir) return path;
  const normalized = workDir.endsWith("/") ? workDir : workDir + "/";
  if (path.startsWith(normalized)) {
    return path.slice(normalized.length);
  }
  return path;
}
