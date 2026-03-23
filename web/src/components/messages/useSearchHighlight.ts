import { useEffect, type RefObject } from "react";

import { useSearch } from "./search-context";

const ATTR = "data-search-hl";

function clearMarks(container: HTMLElement): void {
  for (const mark of container.querySelectorAll(`mark[${ATTR}]`)) {
    const parent = mark.parentNode;
    if (!parent) continue;
    parent.replaceChild(document.createTextNode(mark.textContent || ""), mark);
  }
  container.normalize();
}

function applyMarks(container: HTMLElement, query: string): void {
  const lower = query.toLowerCase();
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  const hits: { node: Text; index: number }[] = [];
  let node: Text | null;
  while ((node = walker.nextNode() as Text | null)) {
    const text = node.textContent;
    if (!text) continue;
    const textLower = text.toLowerCase();
    let start = 0;
    while (start < textLower.length) {
      const idx = textLower.indexOf(lower, start);
      if (idx === -1) break;
      hits.push({ node, index: idx });
      start = idx + query.length;
    }
  }

  // Apply in reverse so earlier split indices stay valid
  for (let i = hits.length - 1; i >= 0; i--) {
    const { node: textNode, index } = hits[i];
    const after = textNode.splitText(index + query.length);
    const matched = textNode.splitText(index);
    const mark = document.createElement("mark");
    mark.setAttribute(ATTR, "");
    mark.className = "rounded-[2px] bg-amber-200/80 text-inherit";
    mark.textContent = matched.textContent;
    matched.parentNode?.replaceChild(mark, matched);
    void after;
  }
}

/**
 * Highlight search query matches inside a Streamdown-rendered container
 * by injecting <mark> elements into the DOM.
 */
export function useSearchHighlight(
  containerRef: RefObject<HTMLElement | null>,
  content: string,
): void {
  const { query } = useSearch();

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    if (!query) {
      clearMarks(el);
      return;
    }

    // Wait one frame so Streamdown has committed its DOM
    const raf = requestAnimationFrame(() => {
      clearMarks(el);
      applyMarks(el, query);
    });

    return () => {
      cancelAnimationFrame(raf);
      clearMarks(el);
    };
  }, [query, content, containerRef]);
}
