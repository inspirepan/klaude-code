import { useT } from "@/i18n";
import type { AskUserQuestionSummaryUIExtra } from "./message-ui-extra";

interface QuestionSummaryViewProps {
  uiExtra: AskUserQuestionSummaryUIExtra;
}

export function QuestionSummaryView({ uiExtra }: QuestionSummaryViewProps): React.JSX.Element {
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
      {uiExtra.items.map((item, i) => {
        const lines = item.summary.split("\n").map((l) => l.replace(/^[•-]\s*/, ""));
        return (
          <div key={i}>
            <div className="text-neutral-500">{item.question}</div>
            <div className="mt-0.5 flex flex-col gap-0.5 pl-3">
              {lines.map((line, li) => (
                <div key={li} className="flex items-start gap-1.5">
                  <span className={`mt-[0.1em] shrink-0 text-xs ${item.answered ? "text-neutral-400" : "text-amber-500"}`}>→</span>
                  <span
                    className={
                      item.answered ? "font-medium text-neutral-800" : "text-amber-600"
                    }
                  >
                    {line}
                  </span>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
