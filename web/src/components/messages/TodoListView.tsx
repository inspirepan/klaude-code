import { Circle, CircleCheck, CircleDashed } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useT } from "@/i18n";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { TodoListUIExtra } from "./message-ui-extra";

const iconSize = "h-3.5 w-3.5 shrink-0";

const statusConfig = {
  pending: { iconClass: `${iconSize} text-neutral-300`, textClass: "text-neutral-500" },
  in_progress: {
    iconClass: `${iconSize} text-blue-500 animate-spin-slow`,
    textClass: "text-blue-600",
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

interface TodoItemProps {
  content: string;
  iconClass: string;
  textClass: string;
  Icon: typeof Circle;
}

function TodoItem({ content, iconClass, textClass, Icon }: TodoItemProps): JSX.Element {
  const spanRef = useRef<HTMLSpanElement>(null);
  const [isTruncated, setIsTruncated] = useState(false);

  useEffect(() => {
    const el = spanRef.current;
    if (!el) return;
    const check = () => { setIsTruncated(el.scrollWidth > el.clientWidth); };
    check();
    const observer = new ResizeObserver(check);
    observer.observe(el);
    return () => { observer.disconnect(); };
  }, [content]);

  const row = (
    <div className="flex min-w-0 cursor-default items-center gap-2 leading-relaxed">
      <Icon className={iconClass} />
      <span ref={spanRef} className={`${textClass} truncate`}>{content}</span>
    </div>
  );

  if (!isTruncated) return row;

  return (
    <Tooltip>
      <TooltipTrigger asChild>{row}</TooltipTrigger>
      <TooltipContent className="max-w-xs whitespace-pre-wrap break-words">
        {content}
      </TooltipContent>
    </Tooltip>
  );
}

interface TodoListViewProps {
  uiExtra: TodoListUIExtra;
}

export function TodoListView({ uiExtra }: TodoListViewProps): JSX.Element {
  const t = useT();
  const { todos, new_completed, explanation } = uiExtra.todo_list;
  const newCompletedSet = new Set(new_completed);

  return (
    <div className="flex w-full min-w-0 flex-col gap-0.5 py-1 text-sm">
      <span className="mb-0.5 font-semibold text-neutral-700">{t("tool.todoTitle")}</span>
      {todos.map((todo, i) => {
        const isNewCompleted = todo.status === "completed" && newCompletedSet.has(todo.content);
        const config = statusConfig[todo.status];
        const Icon = statusIcon[todo.status];
        const iconClass = isNewCompleted ? `${iconSize} text-emerald-600` : config.iconClass;
        const textClass = isNewCompleted ? "text-emerald-700" : config.textClass;

        return (
          <TodoItem key={i} content={todo.content} iconClass={iconClass} textClass={textClass} Icon={Icon} />
        );
      })}
      {explanation && <p className="mt-1 text-sm italic text-neutral-400">{explanation}</p>}
    </div>
  );
}
