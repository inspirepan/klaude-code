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
  extra: Record<string, unknown>,
): extra is AskUserQuestionSummaryUIExtra {
  return extra.type === "ask_user_question_summary";
}

interface QuestionSummaryViewProps {
  uiExtra: AskUserQuestionSummaryUIExtra;
}

export function QuestionSummaryView({ uiExtra }: QuestionSummaryViewProps): JSX.Element {
  if (!uiExtra.items.length) {
    return <span className="text-sm text-amber-600">(No answer provided)</span>;
  }

  return (
    <div className="flex flex-col gap-1.5 text-sm py-1">
      {uiExtra.items.map((item, i) => (
        <div key={i} className="flex flex-col gap-0.5">
          <div className="flex items-start gap-1.5 text-zinc-600">
            <span className="shrink-0 text-zinc-400">●</span>
            <span>{item.question}</span>
          </div>
          <div className="flex items-start gap-1.5 pl-[calc(1ch+6px)]">
            <span className="shrink-0 text-zinc-300">&rarr;</span>
            <span className={item.answered ? "text-zinc-500" : "text-amber-600"}>
              {item.summary}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}
