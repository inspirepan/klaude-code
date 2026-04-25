export interface DiffUIExtra {
  type: "diff";
  files: Array<{
    file_path: string;
    lines: Array<{
      kind: "ctx" | "add" | "remove" | "gap";
      old_line_no?: number | null;
      new_line_no: number | null;
      spans: Array<{ op: "equal" | "insert" | "delete"; text: string }>;
    }>;
    stats_add: number;
    stats_remove: number;
  }>;
  raw_unified_diff: string | null;
}

export function isDiffUIExtra(extra: unknown): extra is DiffUIExtra {
  return (
    typeof extra === "object" && extra !== null && (extra as { type?: unknown }).type === "diff"
  );
}

export interface TodoItem {
  content: string;
  status: "pending" | "in_progress" | "completed";
}

export interface TodoListUIExtra {
  type: "todo_list";
  todo_list: {
    todos: TodoItem[];
    new_completed: string[];
  };
}

export function isTodoListUIExtra(extra: unknown): extra is TodoListUIExtra {
  return (
    typeof extra === "object" &&
    extra !== null &&
    (extra as { type?: unknown }).type === "todo_list"
  );
}

export interface MarkdownDocUIExtra {
  type: "markdown_doc";
  file_path: string;
  content: string;
}

export function isMarkdownDocUIExtra(extra: unknown): extra is MarkdownDocUIExtra {
  return (
    typeof extra === "object" &&
    extra !== null &&
    (extra as { type?: unknown }).type === "markdown_doc"
  );
}

export interface QuestionSummaryItem {
  question: string;
  summary: string;
  answered: boolean;
}

export interface AskUserQuestionSummaryUIExtra {
  type: "ask_user_question_summary";
  items: QuestionSummaryItem[];
}

export function isQuestionSummaryUIExtra(extra: unknown): extra is AskUserQuestionSummaryUIExtra {
  return (
    typeof extra === "object" &&
    extra !== null &&
    (extra as { type?: unknown }).type === "ask_user_question_summary"
  );
}

export interface ImageUIExtra {
  type: "image";
  file_path: string;
}

export function isImageUIExtra(extra: unknown): extra is ImageUIExtra {
  if (typeof extra !== "object" || extra === null) return false;
  const record = extra as Record<string, unknown>;
  return record.type === "image" && typeof record.file_path === "string";
}
