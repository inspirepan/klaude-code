import { Circle, CircleCheck, CircleDashed } from "lucide-react";

import { useT } from "@/i18n";
import type { TodoListUIExtra } from "./message-ui-extra";

const iconSize = "h-3.5 w-3.5 shrink-0";

const statusConfig = {
  pending: { iconClass: `${iconSize} text-neutral-300`, textClass: "text-neutral-500" },
  in_progress: {
    iconClass: `${iconSize} text-amber-500 animate-spin-slow`,
    textClass: "text-amber-600",
  },
  completed: {
    iconClass: `${iconSize} text-emerald-500`,
    textClass: "text-neutral-500 line-through decoration-neutral-400",
  },
} as const;

const statusIcon = {
  pending: Circle,
  in_progress: CircleDashed,
  completed: CircleCheck,
} as const;

interface TodoListViewProps {
  uiExtra: TodoListUIExtra;
}

export function TodoListView({ uiExtra }: TodoListViewProps): JSX.Element {
  const t = useT();
  const { todos, new_completed, explanation } = uiExtra.todo_list;
  const newCompletedSet = new Set(new_completed);

  return (
    <div className="flex w-fit flex-col gap-0.5 py-1 text-base">
      <span className="mb-0.5 font-semibold text-neutral-700">{t("tool.todoTitle")}</span>
      {todos.map((todo, i) => {
        const isNewCompleted = todo.status === "completed" && newCompletedSet.has(todo.content);
        const config = statusConfig[todo.status];
        const Icon = statusIcon[todo.status];
        const iconClass = isNewCompleted ? `${iconSize} text-emerald-600` : config.iconClass;
        const textClass = isNewCompleted ? "text-emerald-700" : config.textClass;

        return (
          <div key={i} className="flex items-center gap-2 leading-relaxed">
            <Icon className={iconClass} />
            <span className={textClass}>{todo.content}</span>
          </div>
        );
      })}
      {explanation && <p className="mt-1 text-sm italic text-neutral-400">{explanation}</p>}
    </div>
  );
}
