/**
 * Streamdown DiagramPlugin adapter for beautiful-mermaid.
 *
 * beautiful-mermaid is ~2.5MB unminified, so it is imported dynamically: the
 * chunk is only fetched the first time a message actually contains a mermaid
 * block, instead of being bundled into the entry chunk. Vite caches the module,
 * so repeat renders do not re-download it.
 */
export const mermaid = {
  name: "mermaid" as const,
  type: "diagram" as const,
  language: "mermaid",
  getMermaid: () => ({
    initialize: () => {},
    render: async (_id: string, source: string) => {
      const { renderMermaidSVG } = await import("beautiful-mermaid");
      return {
        svg: renderMermaidSVG(source, {
          bg: "#ffffff",
          fg: "#262626",
          transparent: true,
          font: "Lilex Variable, ui-monospace, monospace",
          padding: 24,
        }),
      };
    },
  }),
};
