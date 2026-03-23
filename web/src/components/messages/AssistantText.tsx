import { useRef } from "react";
import type { UrlTransform } from "streamdown";
import { Streamdown } from "streamdown";
import { code } from "@streamdown/code";
import "streamdown/styles.css";

import { buildFileApiUrl } from "../../api/client";
import type { AssistantTextItem } from "../../types/message";
import { mermaid } from "../../lib/mermaid-plugin";
import { FrontmatterTable } from "./FrontmatterTable";
import { useParsedFrontmatter } from "./frontmatter";
import { useSearchHighlight } from "./useSearchHighlight";

interface AssistantTextProps {
  item: AssistantTextItem;
}

const plugins = { code, mermaid };
const REMOTE_URL_PREFIXES = ["http://", "https://", "data:", "blob:", "//", "#", "/api/"];
const WINDOWS_ABSOLUTE_PATH_RE = /^[A-Za-z]:[\\/]/;
const POSIX_LOCAL_ROOT_PREFIXES = ["/Users/", "/home/", "/tmp/", "/var/", "/private/", "/Volumes/"];

function parseFileUrl(url: string): string | null {
  if (!url.startsWith("file://")) {
    return null;
  }
  try {
    const parsed = new URL(url);
    let filePath = decodeURIComponent(parsed.pathname);
    if (/^\/[A-Za-z]:\//.test(filePath)) {
      filePath = filePath.slice(1);
    }
    return filePath;
  } catch {
    return null;
  }
}

function looksLikeLocalAbsolutePath(url: string): boolean {
  return (
    WINDOWS_ABSOLUTE_PATH_RE.test(url) ||
    POSIX_LOCAL_ROOT_PREFIXES.some((prefix) => url.startsWith(prefix))
  );
}

function transformImageUrl(url: string, sessionId: string | null): string {
  if (sessionId === null || REMOTE_URL_PREFIXES.some((prefix) => url.startsWith(prefix))) {
    return url;
  }

  const fileUrlPath = parseFileUrl(url);
  if (fileUrlPath !== null) {
    return buildFileApiUrl(fileUrlPath, sessionId);
  }

  if (url.startsWith("/")) {
    return looksLikeLocalAbsolutePath(url) ? buildFileApiUrl(url, sessionId) : url;
  }

  return buildFileApiUrl(url, sessionId);
}

export function AssistantText({ item }: AssistantTextProps): JSX.Element {
  const { entries, body } = useParsedFrontmatter(item.content);
  const containerRef = useRef<HTMLDivElement>(null);
  useSearchHighlight(containerRef, item.content);
  const urlTransform: UrlTransform = (url, key, node) => {
    if (key !== "src" || node.tagName !== "img") {
      return url;
    }
    return transformImageUrl(url, item.sessionId);
  };

  return (
    <div ref={containerRef} className="assistant-text relative">
      {entries ? <FrontmatterTable entries={entries} /> : null}
      <Streamdown
        // Use "static" during streaming to bypass Streamdown's useTransition,
        // which gets starved by frequent Zustand store updates.
        mode={item.isStreaming ? "static" : "streaming"}
        isAnimating={item.isStreaming}
        plugins={plugins}
        urlTransform={urlTransform}
      >
        {body}
      </Streamdown>
    </div>
  );
}
