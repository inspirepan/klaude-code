import { useMemo, useState } from "react";
import { Check, CircleHelp, X } from "lucide-react";
import { useT } from "@/i18n";

import type {
  AskUserQuestionQuestion,
  AskUserQuestionResponsePayload,
  OperationSelectResponsePayload,
  PendingUserInteractionRequest,
  UserInteractionResponse,
} from "../../types/interaction";

interface UserInteractionCardProps {
  request: PendingUserInteractionRequest;
  pendingCount: number;
  disabled?: boolean;
  onRespond: (response: UserInteractionResponse) => Promise<void>;
}

function buildAskResponsePayload(
  questions: AskUserQuestionQuestion[],
  selectedByQuestion: Record<string, string[]>,
  noteByQuestion: Record<string, string>,
): AskUserQuestionResponsePayload {
  return {
    kind: "ask_user_question",
    answers: questions.map((question) => {
      const note = (noteByQuestion[question.id] ?? "").trim();
      let selectedOptionIds = [...(selectedByQuestion[question.id] ?? [])];
      if (note.length > 0) {
        if (question.multi_select) {
          if (!selectedOptionIds.includes("__other__")) {
            selectedOptionIds.push("__other__");
          }
        } else {
          selectedOptionIds = ["__other__"];
        }
      }
      return {
        question_id: question.id,
        selected_option_ids: selectedOptionIds,
        other_text: selectedOptionIds.includes("__other__") && note.length > 0 ? note : undefined,
        note: note.length > 0 ? note : undefined,
      };
    }),
  };
}

function isQuestionAnswered(
  question: AskUserQuestionQuestion,
  selectedByQuestion: Record<string, string[]>,
  noteByQuestion: Record<string, string>,
): boolean {
  const selected = selectedByQuestion[question.id] ?? [];
  const note = (noteByQuestion[question.id] ?? "").trim();
  return selected.length > 0 || note.length > 0;
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

/* ── Option pill (shared by ask + operation) ────────────────────────── */

function OptionPill({
  checked,
  disabled,
  label,
  description,
  onClick,
}: {
  checked: boolean;
  disabled: boolean;
  label: string;
  description: string;
  onClick: () => void;
}): JSX.Element {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`group/pill inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-left transition-all ${
        checked
          ? "border-blue-200 bg-blue-50/80 ring-1 ring-blue-200/60"
          : "border-border bg-card hover:border-neutral-300 hover:bg-surface"
      } disabled:cursor-not-allowed disabled:opacity-50`}
    >
      <span
        className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border transition-all ${
          checked
            ? "border-blue-500 bg-blue-500 text-white"
            : "border-neutral-300 bg-card group-hover/pill:border-neutral-400"
        }`}
      >
        {checked && <Check className="h-2.5 w-2.5" strokeWidth={3} />}
      </span>
      <span className="min-w-0">
        <span
          className={`block text-base font-medium leading-tight ${checked ? "text-blue-700" : "text-neutral-700"}`}
        >
          {label}
        </span>
        {description && (
          <span className="mt-0.5 block text-xs leading-snug text-neutral-500">{description}</span>
        )}
      </span>
    </button>
  );
}

/* ── Single question panel ──────────────────────────────────────────── */

function QuestionPanel({
  question,
  questionIndex,
  selected,
  note,
  answered,
  showValidation,
  actionDisabled,
  onToggleOption,
  onNoteChange,
}: {
  question: AskUserQuestionQuestion;
  questionIndex: number;
  selected: string[];
  note: string;
  answered: boolean;
  showValidation: boolean;
  actionDisabled: boolean;
  onToggleOption: (optionId: string) => void;
  onNoteChange: (value: string) => void;
}): JSX.Element {
  const t = useT();
  return (
    <div>
      {/* Question header chip */}
      <div className="mb-1.5 flex items-center gap-1.5">
        <span className="text-xs font-medium uppercase tracking-wider text-neutral-500">
          {question.header || `Question ${questionIndex + 1}`}
        </span>
        {question.multi_select && (
          <span className="text-xs text-neutral-500">{t("interaction.selectMultiple")}</span>
        )}
      </div>

      {/* Question text */}
      <p className="mb-3 text-base leading-relaxed text-neutral-700">{question.question}</p>

      {/* Option pills */}
      <div className="flex flex-wrap gap-2">
        {question.options.map((option) => (
          <OptionPill
            key={option.id}
            checked={selected.includes(option.id)}
            disabled={actionDisabled}
            label={option.label}
            description={option.description}
            onClick={() => { onToggleOption(option.id); }}
          />
        ))}
      </div>

      {/* Other text input */}
      <div className="mt-3">
        <input
          type="text"
          disabled={actionDisabled}
          value={note}
          onChange={(e) => { onNoteChange(e.target.value); }}
          placeholder={`Other: ${question.input_placeholder ?? "Type something."}`}
          className="h-9 w-full rounded-lg border border-border bg-surface/50 px-3 text-base text-neutral-700 outline-none transition placeholder:text-neutral-400 focus:border-blue-300 focus:bg-card focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
        />
      </div>

      {/* Validation hint — only after attempted submit */}
      {showValidation && !answered && (
        <p className="mt-2 text-xs text-amber-600">{t("interaction.validationHint")}</p>
      )}
    </div>
  );
}

/* ── Main card ──────────────────────────────────────────────────────── */

export function UserInteractionCard({
  request,
  pendingCount,
  disabled = false,
  onRespond,
}: UserInteractionCardProps): JSX.Element {
  const t = useT();
  const [selectedByQuestion, setSelectedByQuestion] = useState<Record<string, string[]>>({});
  const [noteByQuestion, setNoteByQuestion] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [showValidation, setShowValidation] = useState(false);
  const [activeTab, setActiveTab] = useState(0);

  const askPayload = request.payload.kind === "ask_user_question" ? request.payload : null;
  const operationPayload = request.payload.kind === "operation_select" ? request.payload : null;

  const askCanSubmit = useMemo(() => {
    if (askPayload === null) return false;
    return askPayload.questions.every((q) =>
      isQuestionAnswered(q, selectedByQuestion, noteByQuestion),
    );
  }, [askPayload, noteByQuestion, selectedByQuestion]);

  const operationCanSubmit = useMemo(() => {
    if (operationPayload === null) return false;
    return (selectedByQuestion["__operation_select__"] ?? []).length > 0;
  }, [operationPayload, selectedByQuestion]);

  const canSubmit = askPayload !== null ? askCanSubmit : operationCanSubmit;
  const actionDisabled = disabled || submitting;
  const multipleQuestions = askPayload !== null && askPayload.questions.length > 1;

  // Find first unanswered question index (for validation jump).
  const firstUnansweredIndex = useMemo(() => {
    if (askPayload === null) return -1;
    return askPayload.questions.findIndex(
      (q) => !isQuestionAnswered(q, selectedByQuestion, noteByQuestion),
    );
  }, [askPayload, selectedByQuestion, noteByQuestion]);

  async function submitAskResponse(): Promise<void> {
    if (askPayload === null || actionDisabled) return;
    if (!canSubmit) {
      setShowValidation(true);
      if (firstUnansweredIndex >= 0) setActiveTab(firstUnansweredIndex);
      return;
    }
    setSubmitting(true);
    try {
      await onRespond({
        status: "submitted",
        payload: buildAskResponsePayload(askPayload.questions, selectedByQuestion, noteByQuestion),
      });
    } finally {
      setSubmitting(false);
    }
  }

  async function submitOperationResponse(): Promise<void> {
    if (operationPayload === null || actionDisabled) return;
    if (!canSubmit) {
      setShowValidation(true);
      return;
    }
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
    <section className="overflow-hidden rounded-2xl border border-border/80 bg-card shadow-sm shadow-neutral-200/40">
      {/* Header */}
      <div className="flex items-center gap-2.5 px-5 pb-1 pt-4">
        <CircleHelp className="h-4 w-4 shrink-0 text-blue-500" />
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

      {/* Body */}
      <div className="px-5 pb-4 pt-3">
        {askPayload && (
          <div>
            {/* ── Tab bar (only when > 1 question) ── */}
            {multipleQuestions && (
              <div className="mb-4 flex flex-wrap gap-1.5">
                {askPayload.questions.map((q, i) => {
                  const isActive = i === activeTab;
                  const answered = isQuestionAnswered(q, selectedByQuestion, noteByQuestion);
                  return (
                    <button
                      key={q.id}
                      type="button"
                      onClick={() => { setActiveTab(i); }}
                      className={`flex items-center gap-1.5 rounded-[22px] px-3 py-1.5 text-sm font-medium transition ${
                        isActive
                          ? "bg-blue-50/55 text-blue-600"
                          : "bg-surface text-neutral-500 hover:bg-muted hover:text-neutral-700"
                      }`}
                    >
                      {/* Answered dot */}
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

            {/* ── Active question panel ── */}
            {askPayload.questions.map((question, qi) => {
              if (multipleQuestions && qi !== activeTab) return null;
              const selected = selectedByQuestion[question.id] ?? [];
              const note = noteByQuestion[question.id] ?? "";
              const answered = isQuestionAnswered(question, selectedByQuestion, noteByQuestion);
              return (
                <QuestionPanel
                  key={question.id}
                  question={question}
                  questionIndex={qi}
                  selected={selected}
                  note={note}
                  answered={answered}
                  showValidation={showValidation}
                  actionDisabled={actionDisabled}
                  onToggleOption={(optionId) => {
                    setSelectedByQuestion((cur) =>
                      toggleOption(question.id, optionId, question.multi_select, cur),
                    );
                    // Single-select: selecting a pill clears Other text
                    if (!question.multi_select) {
                      setNoteByQuestion((cur) => ({ ...cur, [question.id]: "" }));
                    }
                  }}
                  onNoteChange={(value) => {
                    setNoteByQuestion((cur) => ({ ...cur, [question.id]: value }));
                    // Single-select: typing in Other clears pill selection
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
              <span className="text-xs font-medium uppercase tracking-wider text-neutral-500">
                {operationPayload.header}
              </span>
            </div>
            <p className="mb-3 text-base leading-relaxed text-neutral-700">
              {operationPayload.question}
            </p>
            <div className="flex flex-wrap gap-2">
              {operationPayload.options.map((option) => (
                <OptionPill
                  key={option.id}
                  checked={(selectedByQuestion["__operation_select__"] ?? []).includes(option.id)}
                  disabled={actionDisabled}
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

        {/* Action bar */}
        <div className="mt-3 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => {
              void cancel();
            }}
            disabled={actionDisabled}
            className="inline-flex h-7 items-center gap-1 rounded-lg px-2.5 text-sm text-neutral-500 transition hover:bg-muted hover:text-neutral-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <X className="h-3 w-3" />
            {t("interaction.cancel")}
          </button>
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
            className="inline-flex h-7 items-center gap-1 rounded-lg bg-blue-500 px-3 text-sm text-white shadow-sm transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Check className="h-3 w-3" />
            {t("interaction.submit")}
          </button>
        </div>
      </div>
    </section>
  );
}
