import { Circle } from "lucide-react";

interface QuestionSummaryItem {
  question: string;
  summary: string;
  answered: boolean;
}

interface AskUserQuestionSummaryUIExtra {
  type: "ask_user_question_summary";
  items: QuestionSummaryItem[];
}

export function isQuestionSummaryUIExtra(
  extra: unknown,
): extra is AskUserQuestionSummaryUIExtra {
  return typeof extra === "object" && extra !== null && (extra as { type?: unknown }).type === "ask_user_question_summary";
}

interface QuestionSummaryViewProps {
  uiExtra: AskUserQuestionSummaryUIExtra;
}

export function QuestionSummaryView({ uiExtra }: QuestionSummaryViewProps): JSX.Element {
  const title = <div className="text-xs text-neutral-600 font-semibold tracking-[0.06em]">QUESTION</div>;

  if (!uiExtra.items.length) {
    return (
      <div className="flex flex-col gap-1.5 py-1">
        {title}
        <span className="text-sm text-amber-600">(No answer provided)</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2.5 text-sm py-1 leading-relaxed">
      {title}
      {uiExtra.items.map((item, i) => (
        <div key={i} className="flex flex-col gap-1">
          <div className="flex items-start gap-2 text-neutral-700">
            <Circle
              className="w-2 h-2 shrink-0 mt-[0.45em] text-neutral-900"
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
