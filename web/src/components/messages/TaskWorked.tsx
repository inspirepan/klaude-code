import { Check } from "lucide-react";

import type { TaskWorkedItem } from "../../types/message";

interface TaskWorkedProps {
  item: TaskWorkedItem;
}

function formatElapsedCompact(seconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(seconds));
  if (totalSeconds < 60) {
    return `${totalSeconds}s`;
  }

  const minutes = Math.floor(totalSeconds / 60);
  const remainSeconds = totalSeconds % 60;
  if (minutes < 60) {
    return `${minutes}m${String(remainSeconds).padStart(2, "0")}s`;
  }

  const hours = Math.floor(minutes / 60);
  const remainMinutes = minutes % 60;
  return `${hours}h${String(remainMinutes).padStart(2, "0")}m${String(remainSeconds).padStart(2, "0")}s`;
}

export function TaskWorked({ item }: TaskWorkedProps): JSX.Element {
  const suffix = item.turnCount === 1 ? "step" : "steps";

  return (
    <div className="inline-flex items-center gap-1.5 text-sm tracking-[0.03em] text-emerald-700">
      <Check className="w-3.5 h-3.5" strokeWidth={2.25} />
      <span>
        Worked for {formatElapsedCompact(item.durationSeconds)}
        {item.turnCount > 0 ? ` in ${item.turnCount} ${suffix}` : ""}
      </span>
    </div>
  );
}