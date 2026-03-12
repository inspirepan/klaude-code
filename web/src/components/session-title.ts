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
