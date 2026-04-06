export type UserInteractionSource =
  | "tool"
  | "approval"
  | "operation_model"
  | "operation_thinking"
  | "operation_sub_agent_model";

export interface AskUserQuestionOption {
  id: string;
  label: string;
  description: string;
  markdown: string | null;
}

export interface AskUserQuestionQuestion {
  id: string;
  header: string;
  question: string;
  options: AskUserQuestionOption[];
  multi_select: boolean;
  input_placeholder: string | null;
}

export interface AskUserQuestionRequestPayload {
  kind: "ask_user_question";
  questions: AskUserQuestionQuestion[];
}

export interface OperationSelectOption {
  id: string;
  label: string;
  description: string;
}

export interface OperationSelectRequestPayload {
  kind: "operation_select";
  header: string;
  question: string;
  options: OperationSelectOption[];
  input_placeholder: string | null;
}

export type UserInteractionRequestPayload =
  | AskUserQuestionRequestPayload
  | OperationSelectRequestPayload;

export interface PendingUserInteractionRequest {
  requestId: string;
  source: UserInteractionSource;
  toolCallId: string | null;
  payload: UserInteractionRequestPayload;
}

export interface AskUserQuestionAnswer {
  annotation?: {
    markdown?: string;
  };
  question_id: string;
  selected_option_ids: string[];
  other_text?: string;
  note?: string;
}

export interface AskUserQuestionResponsePayload {
  kind: "ask_user_question";
  answers: AskUserQuestionAnswer[];
}

export interface OperationSelectResponsePayload {
  kind: "operation_select";
  selected_option_id: string;
}

export type UserInteractionResponsePayload =
  | AskUserQuestionResponsePayload
  | OperationSelectResponsePayload;

export interface UserInteractionResponse {
  status: "submitted" | "cancelled";
  payload: UserInteractionResponsePayload | null;
}

function asObject(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null) return null;
  return value as Record<string, unknown>;
}

function parseString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function parseAskUserQuestionPayload(
  raw: Record<string, unknown>,
): AskUserQuestionRequestPayload | null {
  if (raw.kind !== "ask_user_question") return null;
  if (!Array.isArray(raw.questions)) return null;

  const questions: AskUserQuestionQuestion[] = [];
  for (const rawQuestion of raw.questions) {
    const questionObj = asObject(rawQuestion);
    if (questionObj === null) return null;
    const id = parseString(questionObj.id);
    const header = parseString(questionObj.header);
    const question = parseString(questionObj.question);
    if (id === null || header === null || question === null) return null;
    if (!Array.isArray(questionObj.options)) return null;

    const options: AskUserQuestionOption[] = [];
    for (const rawOption of questionObj.options) {
      const optionObj = asObject(rawOption);
      if (optionObj === null) return null;
      const optionId = parseString(optionObj.id);
      const label = parseString(optionObj.label);
      const description = parseString(optionObj.description);
      const markdown = parseString(optionObj.markdown);
      if (optionId === null || label === null || description === null) return null;
      options.push({ id: optionId, label, description, markdown });
    }

    const multiSelect = questionObj.multi_select;
    const inputPlaceholderRaw = questionObj.input_placeholder;
    questions.push({
      id,
      header,
      question,
      options,
      multi_select: typeof multiSelect === "boolean" ? multiSelect : false,
      input_placeholder: typeof inputPlaceholderRaw === "string" ? inputPlaceholderRaw : null,
    });
  }

  return { kind: "ask_user_question", questions };
}

function parseOperationSelectPayload(
  raw: Record<string, unknown>,
): OperationSelectRequestPayload | null {
  if (raw.kind !== "operation_select") return null;

  const header = parseString(raw.header);
  const question = parseString(raw.question);
  if (header === null || question === null || !Array.isArray(raw.options)) return null;

  const options: OperationSelectOption[] = [];
  for (const rawOption of raw.options) {
    const optionObj = asObject(rawOption);
    if (optionObj === null) return null;
    const id = parseString(optionObj.id);
    const label = parseString(optionObj.label);
    const description = parseString(optionObj.description);
    if (id === null || label === null || description === null) return null;
    options.push({ id, label, description });
  }

  return {
    kind: "operation_select",
    header,
    question,
    options,
    input_placeholder: typeof raw.input_placeholder === "string" ? raw.input_placeholder : null,
  };
}

function parseRequestPayload(raw: unknown): UserInteractionRequestPayload | null {
  const payload = asObject(raw);
  if (payload === null) return null;
  if (payload.kind === "ask_user_question") {
    return parseAskUserQuestionPayload(payload);
  }
  if (payload.kind === "operation_select") {
    return parseOperationSelectPayload(payload);
  }
  return null;
}

export function parsePendingUserInteractionRequest(
  event: Record<string, unknown>,
): PendingUserInteractionRequest | null {
  const requestId = parseString(event.request_id);
  const payload = parseRequestPayload(event.payload);
  const source = parseString(event.source);

  if (requestId === null || payload === null || source === null) {
    return null;
  }

  const toolCallId = parseString(event.tool_call_id);
  return {
    requestId,
    source: source as UserInteractionSource,
    toolCallId,
    payload,
  };
}
