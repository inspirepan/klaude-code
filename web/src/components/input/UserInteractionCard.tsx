import { useMemo, useState } from "react";
import { Check, CircleHelp, X } from "lucide-react";
import { Streamdown } from "streamdown";
import { code } from "@streamdown/code";

import { ScrollArea } from "@/components/ui/scroll-area";
import { useT } from "@/i18n";
import { mermaid } from "@/lib/mermaid-plugin";

import type {
  AskUserQuestionOption,
  AskUserQuestionQuestion,
  AskUserQuestionResponsePayload,
  OperationSelectResponsePayload,
  PendingUserInteractionRequest,
  UserInteractionResponse,
} from "@/types/interaction";

interface UserInteractionCardProps {
  request: PendingUserInteractionRequest;
  pendingCount: number;
  disabled?: boolean;
  onRespond: (response: UserInteractionResponse) => Promise<void>;
}

const markdownPlugins = { code, mermaid };

function questionHasMarkdownPreview(question: AskUserQuestionQuestion): boolean {
  return (
    !question.multi_select &&
    question.options.some((option) => (option.markdown ?? "").trim().length > 0)
  );
}

function getPreviewOption(
  question: AskUserQuestionQuestion,
  selectedOptionIds: string[],
): AskUserQuestionOption | null {
  for (const optionId of selectedOptionIds) {
    const option = question.options.find((item) => item.id === optionId);
    if (option) {
      return option;
    }
  }
  return question.options[0] ?? null;
}

function buildAskResponsePayload(
  questions: AskUserQuestionQuestion[],
  selectedByQuestion: Record<string, string[]>,
  otherTextByQuestion: Record<string, string>,
): AskUserQuestionResponsePayload {
  return {
    kind: "ask_user_question",
    answers: questions.map((question) => {
      const otherText = (otherTextByQuestion[question.id] ?? "").trim();
      let selectedOptionIds = [...(selectedByQuestion[question.id] ?? [])];

      if (otherText.length > 0) {
        if (question.multi_select) {
          if (!selectedOptionIds.includes("__other__")) {
            selectedOptionIds.push("__other__");
          }
        } else {
          selectedOptionIds = ["__other__"];
        }
      }

      const previewOption = getPreviewOption(question, selectedOptionIds);
      const selectedMarkdown = (previewOption?.markdown ?? "").trim();
      const annotation =
        questionHasMarkdownPreview(question) && selectedMarkdown
          ? { markdown: selectedMarkdown }
          : undefined;

      return {
        annotation,
        question_id: question.id,
        selected_option_ids: selectedOptionIds,
        other_text:
          selectedOptionIds.includes("__other__") && otherText.length > 0 ? otherText : undefined,
        note: otherText.length > 0 ? otherText : undefined,
      };
    }),
  };
}

function isQuestionAnswered(
  question: AskUserQuestionQuestion,
  selectedByQuestion: Record<string, string[]>,
  otherTextByQuestion: Record<string, string>,
): boolean {
  const selected = selectedByQuestion[question.id] ?? [];
  const otherText = (otherTextByQuestion[question.id] ?? "").trim();
  return selected.length > 0 || otherText.length > 0;
}

function toggleOption(
  questionId: string,
  optionId: string,
  multiSelect: boolean,
  current: Record<string, string[]>,
): Record<string, string[]> {
  const previous = current[questionId] ?? [];
  if (multiSelect) {
    const nextSet = new Set(previous);
    if (nextSet.has(optionId)) {
      nextSet.delete(optionId);
    } else {
      nextSet.add(optionId);
    }
    return { ...current, [questionId]: [...nextSet] };
  }
  const isAlreadySelected = previous.includes(optionId);
  return { ...current, [questionId]: isAlreadySelected ? [] : [optionId] };
}

function OptionPill({
  checked,
  disabled,
  multiSelect,
  label,
  description,
  className,
  onClick,
}: {
  checked: boolean;
  disabled: boolean;
  multiSelect: boolean;
  label: string;
  description: string;
  className?: string;
  onClick: () => void;
}): React.JSX.Element {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`group/pill inline-flex items-center gap-2.5 rounded-lg border px-3 py-2 text-left transition-all ${
        checked
          ? "border-sky-200 bg-sky-50/80 ring-1 ring-sky-200/60"
          : "border-border bg-card hover:border-neutral-300 hover:bg-surface"
      } ${className ?? ""} disabled:cursor-not-allowed disabled:opacity-50`}
    >
      {multiSelect ? (
        <span
          className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-all ${
            checked
              ? "border-sky-500 bg-sky-500 text-white"
              : "border-neutral-300 bg-card group-hover/pill:border-neutral-400"
          }`}
        >
          {checked && <Check className="h-2.5 w-2.5" strokeWidth={3} />}
        </span>
      ) : (
        <span
          className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border transition-all ${
            checked
              ? "border-sky-500 bg-white"
              : "border-neutral-300 bg-card group-hover/pill:border-neutral-400"
          }`}
        >
          {checked && <span className="h-2 w-2 rounded-full bg-sky-500" />}
        </span>
      )}
      <span className="min-w-0">
        <span
          className={`block text-base font-semibold leading-tight ${checked ? "text-sky-700" : "text-neutral-800"}`}
        >
          {label}
        </span>
        {description && (
          <span className="mt-0.5 block text-xs leading-relaxed text-neutral-500">
            {description}
          </span>
        )}
      </span>
    </button>
  );
}

function QuestionPanel({
  question,
  questionIndex,
  selected,
  otherText,
  actionDisabled,
  onToggleOption,
  onOtherTextChange,
}: {
  question: AskUserQuestionQuestion;
  questionIndex: number;
  selected: string[];
  otherText: string;
  actionDisabled: boolean;
  onToggleOption: (optionId: string) => void;
  onOtherTextChange: (value: string) => void;
}): React.JSX.Element {
  const t = useT();
  const hasMarkdownPreview = questionHasMarkdownPreview(question);
  const previewOption = getPreviewOption(question, selected);
  const previewMarkdown = (previewOption?.markdown ?? "").trim();

  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5">
        <span className="font-mono text-xs font-medium uppercase tracking-wider text-neutral-500">
          {question.header || `Question ${questionIndex + 1}`}
        </span>
        {question.multi_select && (
          <span className="text-xs text-neutral-500">{t("interaction.selectMultiple")}</span>
        )}
      </div>

      <p className="mb-3 text-pretty text-base leading-relaxed text-neutral-700">
        {question.question}
      </p>

      {hasMarkdownPreview ? (
        <>
          <div className="grid gap-3 lg:grid-cols-[minmax(0,18rem)_minmax(0,1fr)]">
            <div className="flex flex-col gap-2">
              {question.options.map((option) => (
                <OptionPill
                  key={option.id}
                  checked={selected.includes(option.id)}
                  disabled={actionDisabled}
                  multiSelect={question.multi_select}
                  label={option.label}
                  description={option.description}
                  className="w-full justify-start"
                  onClick={() => {
                    onToggleOption(option.id);
                  }}
                />
              ))}
            </div>

            <div className="min-w-0">
              <div className="overflow-hidden rounded-xl bg-surface/50 shadow-sm ring-1 ring-inset ring-black/10">
                <div className="truncate border-b border-border px-3 py-1.5 font-mono text-xs font-medium uppercase tracking-wider text-neutral-500">
                  {previewOption?.label ?? t("interaction.previewLabel")}
                </div>
                <ScrollArea viewportClassName="max-h-80">
                  <div className="assistant-text px-4 py-3 text-base">
                    <Streamdown mode="static" isAnimating={false} plugins={markdownPlugins}>
                      {previewMarkdown || t("interaction.noPreview")}
                    </Streamdown>
                  </div>
                </ScrollArea>
              </div>
            </div>
          </div>

          <div className="mt-3">
            <input
              type="text"
              disabled={actionDisabled}
              value={otherText}
              onChange={(e) => {
                onOtherTextChange(e.target.value);
              }}
              placeholder={t("interaction.otherPlaceholder")}
              className="h-9 w-full rounded-lg border border-border bg-surface/50 px-3 text-base text-neutral-700 outline-none transition placeholder:text-neutral-400 focus:border-sky-300 focus:bg-card focus:ring-2 focus:ring-sky-100 disabled:cursor-not-allowed disabled:opacity-50"
            />
          </div>
        </>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            {question.options.map((option) => (
              <OptionPill
                key={option.id}
                checked={selected.includes(option.id)}
                disabled={actionDisabled}
                multiSelect={question.multi_select}
                label={option.label}
                description={option.description}
                onClick={() => {
                  onToggleOption(option.id);
                }}
              />
            ))}
          </div>

          <div className="mt-3">
            <input
              type="text"
              disabled={actionDisabled}
              value={otherText}
              onChange={(e) => {
                onOtherTextChange(e.target.value);
              }}
              placeholder={t("interaction.otherPlaceholder")}
              className="h-9 w-full rounded-lg border border-border bg-surface/50 px-3 text-base text-neutral-700 outline-none transition placeholder:text-neutral-400 focus:border-sky-300 focus:bg-card focus:ring-2 focus:ring-sky-100 disabled:cursor-not-allowed disabled:opacity-50"
            />
          </div>
        </>
      )}
    </div>
  );
}

export function UserInteractionCard({
  request,
  pendingCount,
  disabled = false,
  onRespond,
}: UserInteractionCardProps): React.JSX.Element {
  const t = useT();
  const [selectedByQuestion, setSelectedByQuestion] = useState<Record<string, string[]>>({});
  const [otherTextByQuestion, setOtherTextByQuestion] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [activeTab, setActiveTab] = useState(0);

  const askPayload = request.payload.kind === "ask_user_question" ? request.payload : null;
  const operationPayload = request.payload.kind === "operation_select" ? request.payload : null;

  const askCanSubmit = useMemo(() => {
    if (askPayload === null) return false;
    return askPayload.questions.every((q) =>
      isQuestionAnswered(q, selectedByQuestion, otherTextByQuestion),
    );
  }, [askPayload, otherTextByQuestion, selectedByQuestion]);

  const operationCanSubmit = useMemo(() => {
    if (operationPayload === null) return false;
    return (selectedByQuestion["__operation_select__"] ?? []).length > 0;
  }, [operationPayload, selectedByQuestion]);

  const canSubmit = askPayload !== null ? askCanSubmit : operationCanSubmit;
  const actionDisabled = disabled || submitting;
  const multipleQuestions = askPayload !== null && askPayload.questions.length > 1;

  const nextUnansweredIndex = useMemo(() => {
    if (askPayload === null) return -1;
    const len = askPayload.questions.length;
    for (let offset = 1; offset <= len; offset++) {
      const idx = (activeTab + offset) % len;
      if (!isQuestionAnswered(askPayload.questions[idx], selectedByQuestion, otherTextByQuestion)) {
        return idx;
      }
    }
    return -1;
  }, [askPayload, activeTab, selectedByQuestion, otherTextByQuestion]);

  async function submitAskResponse(): Promise<void> {
    if (askPayload === null || actionDisabled || !canSubmit) return;
    setSubmitting(true);
    try {
      await onRespond({
        status: "submitted",
        payload: buildAskResponsePayload(
          askPayload.questions,
          selectedByQuestion,
          otherTextByQuestion,
        ),
      });
    } finally {
      setSubmitting(false);
    }
  }

  async function submitOperationResponse(): Promise<void> {
    if (operationPayload === null || actionDisabled || !canSubmit) return;
    const selectedOptionId = (selectedByQuestion["__operation_select__"] ?? [])[0];
    if (!selectedOptionId) return;
    const payload: OperationSelectResponsePayload = {
      kind: "operation_select",
      selected_option_id: selectedOptionId,
    };
    setSubmitting(true);
    try {
      await onRespond({ status: "submitted", payload });
    } finally {
      setSubmitting(false);
    }
  }

  async function cancel(): Promise<void> {
    if (actionDisabled) return;
    setSubmitting(true);
    try {
      await onRespond({ status: "cancelled", payload: null });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="overflow-hidden rounded-2xl bg-card shadow-sm shadow-neutral-200/40 ring-1 ring-black/[0.06]">
      <div className="flex items-center gap-2.5 px-5 pb-1 pt-4">
        <CircleHelp className="h-4 w-4 shrink-0 text-sky-500" />
        <div className="min-w-0 flex-1">
          <span className="text-base font-semibold text-neutral-800">
            {askPayload
              ? t("interaction.agentQuestion")(askPayload.questions.length)
              : t("interaction.agentNeedsInput")}
          </span>
        </div>
        {pendingCount > 1 && (
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-neutral-500">
            {t("interaction.pending")(pendingCount)}
          </span>
        )}
      </div>

      <div className="px-5 pb-4 pt-3">
        {askPayload && (
          <div>
            {multipleQuestions && (
              <div className="mb-4 flex flex-wrap gap-1.5">
                {askPayload.questions.map((q, i) => {
                  const isActive = i === activeTab;
                  const answered = isQuestionAnswered(q, selectedByQuestion, otherTextByQuestion);
                  return (
                    <button
                      key={q.id}
                      type="button"
                      onClick={() => {
                        setActiveTab(i);
                      }}
                      className={`flex items-center gap-1.5 rounded-[22px] px-3 py-1.5 text-sm font-medium transition ${
                        isActive
                          ? "bg-sky-50/55 text-sky-600"
                          : "bg-surface text-neutral-500 hover:bg-muted hover:text-neutral-700"
                      }`}
                    >
                      <span
                        className={`h-1.5 w-1.5 shrink-0 rounded-full transition-colors ${
                          answered ? "bg-emerald-600" : "bg-neutral-300"
                        }`}
                      />
                      {q.header || `Q${i + 1}`}
                    </button>
                  );
                })}
              </div>
            )}

            {askPayload.questions.map((question, qi) => {
              if (multipleQuestions && qi !== activeTab) return null;
              const selected = selectedByQuestion[question.id] ?? [];
              const otherText = otherTextByQuestion[question.id] ?? "";
              return (
                <QuestionPanel
                  key={question.id}
                  question={question}
                  questionIndex={qi}
                  selected={selected}
                  otherText={otherText}
                  actionDisabled={actionDisabled}
                  onToggleOption={(optionId) => {
                    setSelectedByQuestion((cur) =>
                      toggleOption(question.id, optionId, question.multi_select, cur),
                    );
                    if (!question.multi_select) {
                      setOtherTextByQuestion((cur) => ({ ...cur, [question.id]: "" }));
                    }
                  }}
                  onOtherTextChange={(value) => {
                    setOtherTextByQuestion((cur) => ({ ...cur, [question.id]: value }));
                    if (!question.multi_select && value.length > 0) {
                      setSelectedByQuestion((cur) => ({ ...cur, [question.id]: [] }));
                    }
                  }}
                />
              );
            })}
          </div>
        )}

        {operationPayload && (
          <div>
            <div className="mb-1.5">
              <span className="font-mono text-xs font-medium uppercase tracking-wider text-neutral-500">
                {operationPayload.header}
              </span>
            </div>
            <p className="mb-3 text-pretty text-base leading-relaxed text-neutral-700">
              {operationPayload.question}
            </p>
            <div className="flex flex-wrap gap-2">
              {operationPayload.options.map((option) => (
                <OptionPill
                  key={option.id}
                  checked={(selectedByQuestion["__operation_select__"] ?? []).includes(option.id)}
                  disabled={actionDisabled}
                  multiSelect={false}
                  label={option.label}
                  description={option.description}
                  onClick={() => {
                    setSelectedByQuestion((cur) =>
                      toggleOption("__operation_select__", option.id, false, cur),
                    );
                  }}
                />
              ))}
            </div>
          </div>
        )}

        <div className="mt-3 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => {
              void cancel();
            }}
            disabled={actionDisabled}
            className="inline-flex h-7 items-center gap-1 rounded-full px-2.5 text-sm text-neutral-500 transition hover:bg-muted hover:text-neutral-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <X className="h-3 w-3" />
            {t("interaction.cancel")}
          </button>
          {multipleQuestions && !canSubmit ? (
            <button
              type="button"
              onClick={() => {
                if (nextUnansweredIndex >= 0) setActiveTab(nextUnansweredIndex);
              }}
              disabled={actionDisabled || nextUnansweredIndex < 0}
              className={`inline-flex h-7 items-center gap-1 rounded-full px-3 text-sm shadow-sm transition disabled:cursor-not-allowed disabled:opacity-50 ${
                isQuestionAnswered(
                  askPayload.questions[activeTab],
                  selectedByQuestion,
                  otherTextByQuestion,
                )
                  ? "bg-sky-500 text-white hover:bg-sky-600"
                  : "bg-card text-neutral-500 ring-1 ring-black/[0.06] hover:bg-surface hover:text-neutral-700"
              }`}
            >
              {t("interaction.next")}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => {
                if (askPayload !== null) {
                  void submitAskResponse();
                  return;
                }
                void submitOperationResponse();
              }}
              disabled={actionDisabled}
              className="inline-flex h-7 items-center gap-1 rounded-full bg-sky-500 px-3 text-sm text-white shadow-sm transition hover:bg-sky-600 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Check className="h-3 w-3" />
              {t("interaction.submit")}
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
