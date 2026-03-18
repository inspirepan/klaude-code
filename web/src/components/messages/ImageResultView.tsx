import { buildFileApiUrl } from "../../api/client";
import type { ImageUIExtra } from "./message-ui-extra";

interface ImageResultViewProps {
  uiExtra: ImageUIExtra;
  compact?: boolean;
  sessionId?: string | null;
}

export function ImageResultView({
  uiExtra,
  compact = false,
  sessionId,
}: ImageResultViewProps): JSX.Element {
  return (
    <div className="mt-1 overflow-hidden rounded-lg border border-neutral-200/80 bg-white">
      <img
        src={buildFileApiUrl(uiExtra.file_path, sessionId)}
        alt={uiExtra.file_path}
        className="block h-auto max-h-[420px] w-auto max-w-full"
        loading="lazy"
      />
      <div
        className={`border-t border-neutral-200/80 bg-surface px-3 py-1.5 ${compact ? "text-xs" : "text-sm"} truncate font-mono text-neutral-500`}
      >
        {uiExtra.file_path}
      </div>
    </div>
  );
}
