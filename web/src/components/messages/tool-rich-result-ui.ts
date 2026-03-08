import {
  isDiffUIExtra,
  isImageUIExtra,
  isMarkdownDocUIExtra,
  isQuestionSummaryUIExtra,
  isTodoListUIExtra,
} from "./message-ui-extra";

export function hasRichUIExtra(extra: Record<string, unknown>): boolean {
  if (
    isDiffUIExtra(extra) ||
    isTodoListUIExtra(extra) ||
    isMarkdownDocUIExtra(extra) ||
    isQuestionSummaryUIExtra(extra) ||
    isImageUIExtra(extra)
  ) {
    return true;
  }
  if (extra.type === "multi" && Array.isArray(extra.items)) {
    return (extra.items as Record<string, unknown>[]).some(hasRichUIExtra);
  }
  return false;
}

export function hasDiffUIExtra(extra: Record<string, unknown>): boolean {
  if (isDiffUIExtra(extra)) return true;
  if (extra.type === "multi" && Array.isArray(extra.items)) {
    return (extra.items as Record<string, unknown>[]).some(hasDiffUIExtra);
  }
  return false;
}
