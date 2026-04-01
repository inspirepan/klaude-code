import { describe, expect, it, vi } from "vitest";

// Mock the transitive localStorage dependency from message-list-ui -> i18n
vi.mock("@/i18n", () => ({ t: (k: string) => k }));

import type {
  AssistantTextItem,
  CompactionSummaryItem,
  MessageItem,
  ToolBlockItem,
} from "@/types/message";
import type { TodoItem, TodoListUIExtra } from "./message-ui-extra";
import {
  buildSectionBlocks,
  buildSections,
  type SectionBlock,
  type SectionItemBlock,
} from "./message-sections";

const SESSION = "sess-1";

function makeTodoUIExtra(todos: TodoItem[]): TodoListUIExtra {
  return {
    type: "todo_list",
    todo_list: { todos, new_completed: [] },
  };
}

function makeToolBlock(
  id: string,
  toolName: string,
  uiExtra: Record<string, unknown> | null = null,
): ToolBlockItem {
  return {
    id,
    type: "tool_block",
    timestamp: null,
    sessionId: null,
    toolCallId: `tc-${id}`,
    toolName,
    arguments: "{}",
    result: "ok",
    resultStatus: "success",
    uiExtra,
    isStreaming: false,
    streamingContent: "",
  };
}

function makeAssistantText(id: string, content = ""): AssistantTextItem {
  return {
    id,
    type: "assistant_text",
    timestamp: null,
    sessionId: null,
    responseId: null,
    content,
    isStreaming: false,
  };
}

function makeCompaction(id: string): CompactionSummaryItem {
  return { id, type: "compaction_summary", timestamp: null, sessionId: null, content: "summary" };
}

function makeTodoWrite(id: string, todos: TodoItem[]): ToolBlockItem {
  return makeToolBlock(
    id,
    "TodoWrite",
    makeTodoUIExtra(todos) as unknown as Record<string, unknown>,
  );
}

function flatBlockTypes(blocks: SectionBlock[]): string[] {
  return blocks.map((b) => {
    if (b.type === "item" && b.item.type === "tool_block" && b.item.toolName === "TodoWrite") {
      return "todo_card";
    }
    if (b.type === "item" && b.item.type === "assistant_text") return "assistant_text";
    if (b.type === "item" && b.item.type === "compaction_summary") return "compaction_summary";
    if (b.type === "collapse_group") return "collapse_group";
    return b.type;
  });
}

function todoCardIds(blocks: SectionBlock[]): string[] {
  return blocks
    .filter(
      (b): b is SectionItemBlock =>
        b.type === "item" && b.item.type === "tool_block" && b.item.toolName === "TodoWrite",
    )
    .map((b) => b.item.id);
}

function run(items: MessageItem[]): SectionBlock[] {
  const sections = buildSections(items, SESSION, SESSION);
  const result = buildSectionBlocks(sections, SESSION, SESSION, {}, {}, {});
  return result[0];
}

describe("buildSectionBlocks todo cards", () => {
  const pending = (content: string): TodoItem => ({ content, status: "pending" });
  const inProgress = (content: string): TodoItem => ({ content, status: "in_progress" });
  const completed = (content: string): TodoItem => ({ content, status: "completed" });

  it("keeps each TodoWrite as its own card", () => {
    const blocks = run([
      makeTodoWrite("tw1", [pending("A"), pending("B")]),
      makeTodoWrite("tw2", [inProgress("A"), pending("B")]),
      makeToolBlock("t1", "Bash"),
      makeTodoWrite("tw3", [completed("A"), completed("B")]),
    ]);

    expect(flatBlockTypes(blocks)).toEqual([
      "todo_card",
      "todo_card",
      "collapse_group",
      "todo_card",
    ]);
    expect(todoCardIds(blocks)).toEqual(["tw1", "tw2", "tw3"]);
  });

  it("does not suppress TodoWrite cards around other collapsible content", () => {
    const blocks = run([
      makeToolBlock("r1", "Read"),
      makeTodoWrite("tw1", [completed("setup")]),
      makeTodoWrite("tw2", [inProgress("work")]),
      makeToolBlock("t1", "Bash"),
      makeAssistantText("a1", "Done"),
      makeTodoWrite("tw3", [completed("work")]),
    ]);

    expect(flatBlockTypes(blocks)).toEqual([
      "collapse_group",
      "todo_card",
      "todo_card",
      "collapse_group",
      "assistant_text",
      "todo_card",
    ]);
    expect(todoCardIds(blocks)).toEqual(["tw1", "tw2", "tw3"]);
  });

  it("leaves non-todo items in the normal flow", () => {
    const blocks = run([
      makeTodoWrite("tw1", [inProgress("A")]),
      makeToolBlock("t1", "Bash"),
      makeCompaction("c1"),
      makeToolBlock("t2", "Bash"),
      makeTodoWrite("tw2", [completed("A")]),
    ]);

    expect(flatBlockTypes(blocks)).toEqual([
      "todo_card",
      "collapse_group",
      "compaction_summary",
      "collapse_group",
      "todo_card",
    ]);
  });
});
