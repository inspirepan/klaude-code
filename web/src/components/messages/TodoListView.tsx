import type { TodoListUIExtra } from "./message-ui-extra";

const statusConfig = {
  pending: { mark: "\u25A2", markClass: "text-neutral-300", textClass: "text-neutral-500" },
  in_progress: { mark: "\u25C9", markClass: "text-blue-500", textClass: "text-neutral-700" },
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

export function TodoListView({ uiExtra }: TodoListViewProps): JSX.Element {
  const { todos, new_completed } = uiExtra.todo_list;
  const newCompletedSet = new Set(new_completed);

  return (
    <div className="flex flex-col gap-0.5 py-1 text-sm">
      {todos.map((todo, i) => {
        const isNewCompleted = todo.status === "completed" && newCompletedSet.has(todo.content);
        const config = statusConfig[todo.status];
        const markClass = isNewCompleted ? "text-emerald-600 font-semibold" : config.markClass;
        const textClass = isNewCompleted ? "text-emerald-700 font-semibold" : config.textClass;

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
