import { Circle } from "lucide-react";

import { useT } from "@/i18n";
import type { AskUserQuestionSummaryUIExtra } from "./message-ui-extra";

interface QuestionSummaryViewProps {
  uiExtra: AskUserQuestionSummaryUIExtra;
}

export function QuestionSummaryView({ uiExtra }: QuestionSummaryViewProps): JSX.Element {
  const t = useT();
  const title = <div className="text-sm font-semibold text-neutral-600">{t("question.label")}</div>;

  if (!uiExtra.items.length) {
    return (
      <div className="flex flex-col gap-1.5 py-1">
        {title}
        <span className="text-base text-amber-600">{t("question.noAnswer")}</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2.5 py-1 text-base leading-relaxed">
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
            <span className={item.answered ? "text-neutral-600" : "text-amber-600"}>
              {item.summary.includes("\n") ? (
                <span className="flex flex-col">
                  {item.summary.split("\n").map((line, li) => (
                    <span key={li}>{line}</span>
                  ))}
                </span>
              ) : (
                item.summary
              )}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}
