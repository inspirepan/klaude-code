interface TodoItem {
  content: string;
  status: "pending" | "in_progress" | "completed";
}

interface TodoListUIExtra {
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

const statusConfig = {
  pending: { mark: "\u25A2", markClass: "text-neutral-300", textClass: "text-neutral-500" },
  in_progress: { mark: "\u25C9", markClass: "text-amber-500", textClass: "text-neutral-700" },
  completed: {
    mark: "\u2714",
    markClass: "text-emerald-500",
    textClass: "text-neutral-400 line-through",
  },
} as const;

interface TodoListViewProps {
  uiExtra: TodoListUIExtra;
  compact?: boolean;
}

export function TodoListView({ uiExtra, compact = false }: TodoListViewProps): JSX.Element {
  const { todos, new_completed } = uiExtra.todo_list;
  const newCompletedSet = new Set(new_completed);

  return (
    <div className={`flex flex-col gap-0.5 ${compact ? "text-[13px]" : "text-sm"} py-1`}>
      {todos.map((todo, i) => {
        const isNewCompleted = todo.status === "completed" && newCompletedSet.has(todo.content);
        const config = statusConfig[todo.status];
        const markClass = isNewCompleted ? "text-emerald-600 font-semibold" : config.markClass;
        const textClass = isNewCompleted ? "text-emerald-700 font-medium" : config.textClass;

        return (
          <div key={i} className="flex items-start gap-2 leading-relaxed">
            <span className={`w-4 shrink-0 text-center ${markClass}`}>{config.mark}</span>
            <span className={textClass}>{todo.content}</span>
          </div>
        );
      })}
    </div>
  );
}
