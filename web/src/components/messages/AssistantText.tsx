import type { UrlTransform } from "streamdown";
import { Streamdown } from "streamdown";
import { code } from "@streamdown/code";
import "streamdown/styles.css";

import { buildFileApiUrl } from "../../api/client";
import type { AssistantTextItem } from "../../types/message";
import { mermaid } from "../../lib/mermaid-plugin";
import { FrontmatterTable } from "./FrontmatterTable";
import { useParsedFrontmatter } from "./frontmatter";

interface AssistantTextProps {
  item: AssistantTextItem;
}

const plugins = { code, mermaid };
const streamAnimation = { animation: "fadeIn" as const, duration: 120, sep: "char" as const };
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
  const urlTransform: UrlTransform = (url, key, node) => {
    if (key !== "src" || node.tagName !== "img") {
      return url;
    }
    return transformImageUrl(url, item.sessionId);
  };

  return (
    <div className="assistant-text relative">
      {entries ? <FrontmatterTable entries={entries} /> : null}
      <Streamdown
        mode={item.isStreaming ? "static" : "streaming"}
        isAnimating={item.isStreaming}
        animated={streamAnimation}
        plugins={plugins}
        urlTransform={urlTransform}
      >
        {body}
      </Streamdown>
    </div>
  );
}
