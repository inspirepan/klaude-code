import { describe, it, expect } from "vitest";
import { createInitialState, reduceEvent, reduceBatch } from "./event-reducer";

function makeEvent(fields: Record<string, unknown> = {}): Record<string, unknown> {
  return { session_id: "sess-1", ...fields };
}

describe("reduceEvent — streaming accumulation", () => {
  it("thinking.start creates a streaming thinking item", () => {
    const state = reduceEvent(createInitialState(), "thinking.start", makeEvent(), null);
    expect(state.items).toHaveLength(1);
    expect(state.items[0]).toMatchObject({
      type: "thinking",
      content: "",
      isStreaming: true,
    });
    expect(state.activeThinkingIndex).toBe(0);
  });

  it("thinking.delta accumulates content across multiple events", () => {
    let state = createInitialState();
    state = reduceEvent(state, "thinking.start", makeEvent(), null);
    state = reduceEvent(state, "thinking.delta", makeEvent({ content: "Hello" }), null);
    state = reduceEvent(state, "thinking.delta", makeEvent({ content: " world" }), null);
    state = reduceEvent(state, "thinking.delta", makeEvent({ content: "!" }), null);

    expect(state.items).toHaveLength(1);
    expect(state.items[0]).toMatchObject({
      type: "thinking",
      content: "Hello world!",
      isStreaming: true,
    });
  });

  it("thinking.end stops streaming and preserves content", () => {
    let state = createInitialState();
    state = reduceEvent(state, "thinking.start", makeEvent(), null);
    state = reduceEvent(state, "thinking.delta", makeEvent({ content: "thought" }), null);
    state = reduceEvent(state, "thinking.end", makeEvent(), null);

    expect(state.items[0]).toMatchObject({
      type: "thinking",
      content: "thought",
      isStreaming: false,
    });
    expect(state.activeThinkingIndex).toBe(-1);
  });

  it("assistant.text.start creates a streaming assistant_text item", () => {
    const state = reduceEvent(createInitialState(), "assistant.text.start", makeEvent(), null);
    expect(state.items).toHaveLength(1);
    expect(state.items[0]).toMatchObject({
      type: "assistant_text",
      content: "",
      isStreaming: true,
    });
    expect(state.activeTextIndex).toBe(0);
  });

  it("assistant.text.delta accumulates content across multiple events", () => {
    let state = createInitialState();
    state = reduceEvent(state, "assistant.text.start", makeEvent(), null);
    state = reduceEvent(state, "assistant.text.delta", makeEvent({ content: "Hi" }), null);
    state = reduceEvent(state, "assistant.text.delta", makeEvent({ content: " there" }), null);
    state = reduceEvent(state, "assistant.text.delta", makeEvent({ content: "!" }), null);

    expect(state.items).toHaveLength(1);
    expect(state.items[0]).toMatchObject({
      type: "assistant_text",
      content: "Hi there!",
      isStreaming: true,
    });
  });

  it("assistant.text.end stops streaming and preserves content", () => {
    let state = createInitialState();
    state = reduceEvent(state, "assistant.text.start", makeEvent(), null);
    state = reduceEvent(state, "assistant.text.delta", makeEvent({ content: "done" }), null);
    state = reduceEvent(state, "assistant.text.end", makeEvent(), null);

    expect(state.items[0]).toMatchObject({
      type: "assistant_text",
      content: "done",
      isStreaming: false,
    });
    expect(state.activeTextIndex).toBe(-1);
  });

  it("each delta produces a new items array reference", () => {
    let state = createInitialState();
    state = reduceEvent(state, "assistant.text.start", makeEvent(), null);
    const items1 = state.items;

    state = reduceEvent(state, "assistant.text.delta", makeEvent({ content: "a" }), null);
    const items2 = state.items;

    state = reduceEvent(state, "assistant.text.delta", makeEvent({ content: "b" }), null);
    const items3 = state.items;

    expect(items1).not.toBe(items2);
    expect(items2).not.toBe(items3);
  });

  it("each delta produces a new item object reference", () => {
    let state = createInitialState();
    state = reduceEvent(state, "thinking.start", makeEvent(), null);
    const item1 = state.items[0];

    state = reduceEvent(state, "thinking.delta", makeEvent({ content: "a" }), null);
    const item2 = state.items[0];

    state = reduceEvent(state, "thinking.delta", makeEvent({ content: "b" }), null);
    const item3 = state.items[0];

    expect(item1).not.toBe(item2);
    expect(item2).not.toBe(item3);
  });

  it("each delta produces a new top-level state reference", () => {
    let state = createInitialState();
    state = reduceEvent(state, "assistant.text.start", makeEvent(), null);
    const prev = state;

    state = reduceEvent(state, "assistant.text.delta", makeEvent({ content: "x" }), null);
    expect(state).not.toBe(prev);
  });
});

describe("reduceEvent — interleaved thinking and text", () => {
  it("handles thinking followed by assistant text", () => {
    let state = createInitialState();
    state = reduceEvent(state, "thinking.start", makeEvent(), null);
    state = reduceEvent(state, "thinking.delta", makeEvent({ content: "think" }), null);
    state = reduceEvent(state, "thinking.end", makeEvent(), null);
    state = reduceEvent(state, "assistant.text.start", makeEvent(), null);
    state = reduceEvent(state, "assistant.text.delta", makeEvent({ content: "reply" }), null);
    state = reduceEvent(state, "assistant.text.end", makeEvent(), null);

    expect(state.items).toHaveLength(2);
    expect(state.items[0]).toMatchObject({ type: "thinking", content: "think", isStreaming: false });
    expect(state.items[1]).toMatchObject({
      type: "assistant_text",
      content: "reply",
      isStreaming: false,
    });
  });
});

describe("reduceBatch", () => {
  it("replays a full streaming sequence correctly", () => {
    const events = [
      { event_type: "thinking.start", event: makeEvent() },
      { event_type: "thinking.delta", event: makeEvent({ content: "A" }) },
      { event_type: "thinking.delta", event: makeEvent({ content: "B" }) },
      { event_type: "thinking.end", event: makeEvent() },
      { event_type: "assistant.text.start", event: makeEvent() },
      { event_type: "assistant.text.delta", event: makeEvent({ content: "1" }) },
      { event_type: "assistant.text.delta", event: makeEvent({ content: "2" }) },
      { event_type: "assistant.text.delta", event: makeEvent({ content: "3" }) },
      { event_type: "assistant.text.end", event: makeEvent() },
    ];

    const state = reduceBatch(events);
    expect(state.items).toHaveLength(2);
    expect(state.items[0]).toMatchObject({ type: "thinking", content: "AB", isStreaming: false });
    expect(state.items[1]).toMatchObject({
      type: "assistant_text",
      content: "123",
      isStreaming: false,
    });
  });
});
