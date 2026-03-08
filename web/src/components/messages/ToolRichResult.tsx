import type { ToolBlockItem } from "../../types/message";
import { DiffView } from "./DiffView";
import { ImageResultView } from "./ImageResultView";
import { MarkdownDocView } from "./MarkdownDocView";
import { QuestionSummaryView } from "./QuestionSummaryView";
import { TodoListView } from "./TodoListView";
import {
  isDiffUIExtra,
  isImageUIExtra,
  isMarkdownDocUIExtra,
  isQuestionSummaryUIExtra,
  isTodoListUIExtra,
} from "./message-ui-extra";

interface ToolRichResultProps {
  item: ToolBlockItem;
  compact: boolean;
}

function RichUIExtraBlock({
  extra,
  item,
  compact,
}: {
  extra: Record<string, unknown>;
  item: ToolBlockItem;
  compact: boolean;
}): JSX.Element | null {
  if (isDiffUIExtra(extra)) {
    return (
      <div className="mt-0.5 overflow-hidden rounded-lg border border-neutral-200/80">
        <DiffView item={item} uiExtra={extra} />
      </div>
    );
  }
  if (isTodoListUIExtra(extra)) {
    return <TodoListView uiExtra={extra} compact={compact} />;
  }
  if (isMarkdownDocUIExtra(extra)) {
    return <MarkdownDocView uiExtra={extra} compact={compact} />;
  }
  if (isQuestionSummaryUIExtra(extra)) {
    return (
      <div className="rounded-lg border border-neutral-200/80 bg-neutral-50/50 px-3.5 py-2.5">
        <QuestionSummaryView uiExtra={extra} compact={compact} />
      </div>
    );
  }
  if (isImageUIExtra(extra)) {
    return <ImageResultView uiExtra={extra} compact={compact} />;
  }
  return null;
}

export function ToolRichResult({ item, compact }: ToolRichResultProps): JSX.Element | null {
  const extra = item.uiExtra;
  if (!extra) return null;

  if (extra.type === "multi" && Array.isArray(extra.items)) {
    const items = extra.items as Record<string, unknown>[];
    return (
      <div className="flex flex-col gap-1">
        {items.map((sub, index) => (
          <RichUIExtraBlock key={index} extra={sub} item={item} compact={compact} />
        ))}
      </div>
    );
  }

  return <RichUIExtraBlock extra={extra} item={item} compact={compact} />;
}
