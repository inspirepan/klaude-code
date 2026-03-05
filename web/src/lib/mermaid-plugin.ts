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
    render: async (_id: string, source: string) => ({
      svg: renderMermaidSVG(source, {
        bg: "#ffffff",
        fg: "#27272a",
        transparent: true,
        font: "Geist, system-ui, sans-serif",
        padding: 24,
      }),
    }),
  }),
};
