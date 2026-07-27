import { describe, it, expect } from "vitest";
// Read the backend protocol definition directly so this test fails the moment a
// new event class is added without triage on the web side.
import eventsSource from "../../../src/klaude_code/protocol/events.py?raw";
import { createInitialState, reduceEvent, SKIP_EVENT_TYPES } from "./event-reducer";

/** Base classes in events.py that are not concrete events. */
const BASE_CLASSES = new Set(["Event", "ResponseEvent"]);

/**
 * Event types that reach the reducer but are not declared in events.py.
 * `usage.snapshot` is synthesised by the web WS route (routes/ws.py).
 */
const NON_PROTOCOL_EVENT_TYPES = new Set(["usage.snapshot"]);

/** Port of `_event_type_name_from_class_name` in protocol/events.py. */
function eventTypeNameFromClassName(className: string): string {
  const base = className.endsWith("Event") ? className.slice(0, -5) : className;
  const words = base.match(/[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+/g);
  if (words === null) return "event.unknown";
  return words.map((word) => word.toLowerCase()).join(".");
}

function protocolEventTypes(): string[] {
  const classNames = [...eventsSource.matchAll(/^class (\w+)\((?:Event|ResponseEvent)\):/gm)]
    .map((match) => match[1])
    .filter((name) => !BASE_CLASSES.has(name));
  return [...new Set(classNames.map(eventTypeNameFromClassName))].sort();
}

describe("protocol event coverage", () => {
  const eventTypes = protocolEventTypes();

  it("parses the protocol definition", () => {
    // Guards against a regex that silently stops matching, which would make
    // every coverage assertion below vacuously pass.
    expect(eventTypes.length).toBeGreaterThan(50);
    expect(eventTypes).toContain("tool.result");
    expect(eventTypes).toContain("tool.long.running");
  });

  it("never renders a protocol event as an unknown_event block", () => {
    const leaked = eventTypes.filter((eventType) => {
      const state = reduceEvent(createInitialState(), eventType, { session_id: "sess-1" }, null);
      return state.items.some((item) => item.type === "unknown_event");
    });
    expect(leaked).toEqual([]);
  });

  it("has no stale entries in SKIP_EVENT_TYPES", () => {
    const known = new Set([...eventTypes, ...NON_PROTOCOL_EVENT_TYPES]);
    const stale = [...SKIP_EVENT_TYPES].filter((eventType) => !known.has(eventType));
    expect(stale).toEqual([]);
  });
});
