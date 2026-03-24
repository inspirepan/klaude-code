import { describe, expect, it, vi } from "vitest";

// Mock the transitive localStorage dependency from message-list-ui -> i18n
vi.mock("@/i18n", () => ({ t: (k: string) => k }));

import type {
  AssistantTextItem,
  MessageItem,
  TaskMetadataItem,
  ToolBlockItem,
} from "../../types/message";
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
    timestamp: { utc: "", local: "" },
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
    timestamp: { utc: "", local: "" },
    sessionId: null,
    responseId: null,
    content,
    isStreaming: false,
  };
}

function makeTaskMetadata(id: string): TaskMetadataItem {
  return {
    id,
    type: "task_metadata",
    timestamp: null,
    sessionId: null,
    mainAgent: { model: "test", durationMs: 0, inputTokens: 0, outputTokens: 0, turnCount: 0 },
    subAgents: [],
    isPartial: false,
  };
}

function makeTodoWrite(id: string, todos: TodoItem[]): ToolBlockItem {
  return makeToolBlock(
    id,
    "TodoWrite",
    makeTodoUIExtra(todos) as unknown as Record<string, unknown>,
  );
}

/** Return a summary of block types for easy assertion. */
function flatBlockTypes(blocks: SectionBlock[]): string[] {
  return blocks.map((b) => {
    if (b.type === "item" && b.item.type === "tool_block" && b.item.toolName === "TodoWrite") {
      return "todo_card";
    }
    if (b.type === "item" && b.item.type === "assistant_text") return "assistant_text";
    if (b.type === "planned_group") return "planned_group";
    if (b.type === "collapse_group") return "collapse_group";
    return b.type;
  });
}

/** Extract the item id from a todo_card block. */
function overviewItemId(blocks: SectionBlock[]): string[] {
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

describe("buildSectionBlocks planned overview", () => {
  const pending = (c: string): TodoItem => ({ content: c, status: "pending" });
  const inProgress = (c: string): TodoItem => ({ content: c, status: "in_progress" });
  const completed = (c: string): TodoItem => ({ content: c, status: "completed" });

  it("normal flow: one overview card using latest state, precursor and summary suppressed", () => {
    const items: MessageItem[] = [
      makeTodoWrite("tw1", [pending("A"), pending("B")]),
      makeTodoWrite("tw2", [inProgress("A"), pending("B")]),
      makeToolBlock("t1", "Bash"),
      makeTodoWrite("tw3", [completed("A"), completed("B")]),
    ];
    const blocks = run(items);
    // tw1 (precursor) suppressed, tw3 (summary) used as overview, tw3 not shown again
    expect(flatBlockTypes(blocks)).toEqual(["todo_card", "planned_group"]);
    // The overview card uses tw3 (latest state with all completed)
    expect(overviewItemId(blocks)).toEqual(["tw3"]);
  });

  it("direct in_progress without prior overview — overview uses summary state", () => {
    const items: MessageItem[] = [
      makeTodoWrite("tw1", [inProgress("A"), pending("B")]),
      makeToolBlock("t1", "Bash"),
      makeTodoWrite("tw2", [completed("A"), completed("B")]),
    ];
    const blocks = run(items);
    expect(flatBlockTypes(blocks)).toEqual(["todo_card", "planned_group"]);
    // Overview uses tw2 (summary = latest state)
    expect(overviewItemId(blocks)).toEqual(["tw2"]);
  });

  it("two tasks in same section — single overview with latest state", () => {
    const items: MessageItem[] = [
      // Task 1: normal flow
      makeTodoWrite("tw1", [pending("A"), pending("B")]),
      makeTodoWrite("tw2", [inProgress("A"), pending("B")]),
      makeToolBlock("t1", "Bash"),
      makeTodoWrite("tw3", [completed("A"), completed("B")]),
      // Task 2: direct in_progress
      makeTodoWrite("tw4", [inProgress("X"), pending("Y")]),
      makeToolBlock("t2", "Read"),
      makeTodoWrite("tw5", [completed("X"), completed("Y")]),
    ];
    const blocks = run(items);
    // All in one section → single chain, single overview (tw5 = latest)
    expect(flatBlockTypes(blocks)).toEqual(["todo_card", "planned_group", "planned_group"]);
    expect(overviewItemId(blocks)).toEqual(["tw5"]);
  });

  it("chained in_progress intervals — single overview with latest state", () => {
    const items: MessageItem[] = [
      makeTodoWrite("tw1", [inProgress("A"), pending("B")]),
      makeToolBlock("t1", "Bash"),
      makeTodoWrite("tw2", [completed("A"), inProgress("B")]),
      makeToolBlock("t2", "Bash"),
      makeTodoWrite("tw3", [completed("A"), completed("B")]),
    ];
    const blocks = run(items);
    // Single chain: overview(tw3) + pg(tw1) + pg(tw2)
    expect(flatBlockTypes(blocks)).toEqual(["todo_card", "planned_group", "planned_group"]);
    expect(overviewItemId(blocks)).toEqual(["tw3"]);
  });

  it("live session: no summary yet — overview uses last interval start", () => {
    const items: MessageItem[] = [
      makeTodoWrite("tw1", [inProgress("A"), pending("B")]),
      makeToolBlock("t1", "Bash"),
    ];
    const blocks = run(items);
    // No summary TodoWrite; overview falls back to tw1
    expect(flatBlockTypes(blocks)).toEqual(["todo_card", "planned_group"]);
    expect(overviewItemId(blocks)).toEqual(["tw1"]);
  });

  it("live session mid-chain: overview updates to latest interval start", () => {
    const items: MessageItem[] = [
      makeTodoWrite("tw1", [inProgress("A"), pending("B")]),
      makeToolBlock("t1", "Bash"),
      makeTodoWrite("tw2", [completed("A"), inProgress("B")]),
      makeToolBlock("t2", "Bash"),
    ];
    const blocks = run(items);
    // Chain still live (no summary); overview uses tw2 (latest interval start)
    expect(flatBlockTypes(blocks)).toEqual(["todo_card", "planned_group", "planned_group"]);
    expect(overviewItemId(blocks)).toEqual(["tw2"]);
  });

  it("non-TodoWrite blocks in gap are preserved", () => {
    const items: MessageItem[] = [
      makeToolBlock("r1", "Read"),
      makeTodoWrite("tw1", [pending("A")]),
      makeTodoWrite("tw2", [inProgress("A")]),
      makeToolBlock("t1", "Bash"),
      makeTodoWrite("tw3", [completed("A")]),
    ];
    const blocks = run(items);
    // r1 preserved, tw1 suppressed, overview(tw3) + pg(tw2)
    expect(flatBlockTypes(blocks)).toEqual(["collapse_group", "todo_card", "planned_group"]);
    expect(overviewItemId(blocks)).toEqual(["tw3"]);
  });

  it("standalone TodoWrite without planned chain is not suppressed", () => {
    const items: MessageItem[] = [makeTodoWrite("tw1", [pending("A"), pending("B")])];
    const blocks = run(items);
    // No planned chain; TodoWrite rendered as regular card
    expect(flatBlockTypes(blocks)).toEqual(["todo_card"]);
    expect(overviewItemId(blocks)).toEqual(["tw1"]);
  });

  it("non-in_progress TodoWrite between intervals does not split the chain", () => {
    const items: MessageItem[] = [
      makeTodoWrite("tw1", [inProgress("A"), pending("B"), pending("C")]),
      makeToolBlock("t1", "Bash"),
      // Intermediate: marks A complete but no in_progress yet
      makeTodoWrite("tw2", [completed("A"), pending("B"), pending("C")]),
      makeTodoWrite("tw3", [completed("A"), inProgress("B"), pending("C")]),
      makeToolBlock("t2", "Bash"),
      makeTodoWrite("tw4", [completed("A"), completed("B"), completed("C")]),
    ];
    const blocks = run(items);
    // Single chain: overview(tw4) + pg(tw1) + pg(tw3), tw2 suppressed
    expect(flatBlockTypes(blocks)).toEqual(["todo_card", "planned_group", "planned_group"]);
    expect(overviewItemId(blocks)).toEqual(["tw4"]);
  });

  it("all-completed standalone TodoWrite between chains belongs to preceding gap", () => {
    const items: MessageItem[] = [
      // Task 1: standalone completion
      makeTodoWrite("tw1", [completed("A")]),
      // Task 2: direct in_progress
      makeTodoWrite("tw2", [inProgress("X")]),
      makeToolBlock("t1", "Bash"),
      makeTodoWrite("tw3", [completed("X")]),
    ];
    const blocks = run(items);
    // tw1 is in the gap before chain → suppressed (it's a TodoWrite in the gap)
    // chain overview uses tw3
    expect(flatBlockTypes(blocks)).toEqual(["todo_card", "planned_group"]);
    expect(overviewItemId(blocks)).toEqual(["tw3"]);
  });

  it("trailing assistant_text without closing TodoWrite is excluded from planned group", () => {
    const items: MessageItem[] = [
      makeTodoWrite("tw1", [inProgress("A")]),
      makeToolBlock("t1", "Bash"),
      makeAssistantText("a1", "Done!"),
    ];
    const blocks = run(items);
    // assistant_text should stand alone after the planned group
    expect(flatBlockTypes(blocks)).toEqual(["todo_card", "planned_group", "assistant_text"]);
    expect(overviewItemId(blocks)).toEqual(["tw1"]);
  });

  it("trailing assistant_text + task_metadata without closing TodoWrite are both excluded", () => {
    const items: MessageItem[] = [
      makeTodoWrite("tw1", [inProgress("A")]),
      makeToolBlock("t1", "Bash"),
      makeAssistantText("a1", "Done!"),
      makeTaskMetadata("tm1"),
    ];
    const blocks = run(items);
    // Both trailing items should stand alone after the planned group
    expect(flatBlockTypes(blocks)).toEqual(["todo_card", "planned_group", "assistant_text", "item"]);
    expect(overviewItemId(blocks)).toEqual(["tw1"]);
  });

  it("trailing assistant_text with closing TodoWrite stays outside planned group normally", () => {
    const items: MessageItem[] = [
      makeTodoWrite("tw1", [inProgress("A")]),
      makeToolBlock("t1", "Bash"),
      makeTodoWrite("tw2", [completed("A")]),
      makeAssistantText("a1", "All done!"),
    ];
    const blocks = run(items);
    // assistant_text after the closing TodoWrite is already outside the chain
    expect(flatBlockTypes(blocks)).toEqual(["todo_card", "planned_group", "assistant_text"]);
    expect(overviewItemId(blocks)).toEqual(["tw2"]);
  });

  it("mid-stream assistant_text followed by tool call stays in planned group", () => {
    const items: MessageItem[] = [
      makeTodoWrite("tw1", [inProgress("A")]),
      makeAssistantText("a1", "Let me check..."),
      makeToolBlock("t1", "Bash"),
    ];
    const blocks = run(items);
    // assistant_text is not trailing — it's followed by a tool call, stays in planned group
    expect(flatBlockTypes(blocks)).toEqual(["todo_card", "planned_group"]);
  });
});
