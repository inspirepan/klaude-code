import { describe, expect, it } from "vitest";

import type { TodoItem } from "./message-ui-extra";
import { getVisibleTodos } from "./todo-list-view";

describe("getVisibleTodos", () => {
  it("keeps pending, in-progress, and newly completed todos", () => {
    const todos: TodoItem[] = [
      { content: "pending", status: "pending" },
      { content: "fresh done", status: "completed" },
      { content: "old done", status: "completed" },
      { content: "working", status: "in_progress" },
    ];

    expect(getVisibleTodos(todos, ["fresh done"])).toEqual([
      { content: "pending", status: "pending" },
      { content: "fresh done", status: "completed" },
      { content: "working", status: "in_progress" },
    ]);
  });

  it("hides completed todos when they are not newly completed", () => {
    const todos: TodoItem[] = [
      { content: "done A", status: "completed" },
      { content: "done B", status: "completed" },
    ];

    expect(getVisibleTodos(todos, [])).toEqual([]);
  });
});
