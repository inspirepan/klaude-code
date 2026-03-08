import { Circle } from "lucide-react";
import type { AskUserQuestionSummaryUIExtra } from "./message-ui-extra";

interface QuestionSummaryViewProps {
  uiExtra: AskUserQuestionSummaryUIExtra;
  compact?: boolean;
}

export function QuestionSummaryView({
  uiExtra,
  compact = false,
}: QuestionSummaryViewProps): JSX.Element {
  const title = (
    <div className={`${compact ? "text-2xs" : "text-xs"} font-semibold text-neutral-600`}>
      QUESTION
    </div>
  );

  if (!uiExtra.items.length) {
    return (
      <div className="flex flex-col gap-1.5 py-1">
        {title}
        <span className={`${compact ? "text-[13px]" : "text-sm"} text-amber-600`}>
          (No answer provided)
        </span>
      </div>
    );
  }

  return (
    <div
      className={`flex flex-col gap-2.5 ${compact ? "text-[13px]" : "text-sm"} py-1 leading-relaxed`}
    >
      {title}
      {uiExtra.items.map((item, i) => (
        <div key={i} className="flex flex-col gap-1">
          <div className="flex items-start gap-2 text-neutral-700">
            <Circle
              className="mt-[0.45em] h-2 w-2 shrink-0 text-neutral-900"
              fill="currentColor"
              stroke="none"
            />
            <span>{item.question}</span>
          </div>
          <div className="flex items-start gap-2 pl-[calc(1ch+8px)]">
            <span className="shrink-0 text-neutral-300">&rarr;</span>
            <span className={item.answered ? "text-neutral-500" : "text-amber-600"}>
              {item.summary}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}
