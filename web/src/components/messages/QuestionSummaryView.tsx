import { Check } from "lucide-react";

import { useT } from "@/i18n";
import type { AskUserQuestionSummaryUIExtra } from "./message-ui-extra";

interface QuestionSummaryViewProps {
  uiExtra: AskUserQuestionSummaryUIExtra;
}

export function QuestionSummaryView({ uiExtra }: QuestionSummaryViewProps): JSX.Element {
  const t = useT();
  const title = <div className="text-sm font-medium text-neutral-500">{t("question.label")}</div>;

  if (!uiExtra.items.length) {
    return (
      <div className="flex flex-col gap-1 py-1">
        {title}
        <span className="text-sm text-amber-600">{t("question.noAnswer")}</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 py-1 text-sm leading-relaxed">
      {title}
      {uiExtra.items.map((item, i) => (
        <div key={i}>
          <div className="text-neutral-700">{item.question}</div>
          <div className="mt-0.5 flex items-start gap-1.5 pl-3">
            {item.answered ? (
              <Check className="mt-[0.35em] h-3 w-3 shrink-0 text-emerald-600" strokeWidth={2.5} />
            ) : (
              <span className="mt-[0.1em] shrink-0 text-sm text-amber-500">?</span>
            )}
            <span className={item.answered ? "text-neutral-700" : "text-amber-600"}>
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
