import { renderMermaidSVG } from "beautiful-mermaid";

/**
 * Streamdown DiagramPlugin adapter for beautiful-mermaid.
 * Wraps the synchronous renderMermaidSVG into the async MermaidInstance interface.
 */
export const mermaid = {
  name: "mermaid" as const,
  type: "diagram" as const,
  language: "mermaid",
  getMermaid: () => ({
    initialize: () => {},
    render: (_id: string, source: string) =>
      Promise.resolve({
        svg: renderMermaidSVG(source, {
          bg: "#ffffff",
          fg: "#262626",
          transparent: true,
          font: "Lilex Variable, ui-monospace, monospace",
          padding: 24,
        }),
      }),
  }),
};
