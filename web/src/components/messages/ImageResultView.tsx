import { buildFileApiUrl } from "../../api/client";
import type { ImageUIExtra } from "./message-ui-extra";

interface ImageResultViewProps {
  uiExtra: ImageUIExtra;
  sessionId?: string | null;
}

export function ImageResultView({ uiExtra, sessionId }: ImageResultViewProps): React.JSX.Element {
  return (
    <div className="mt-1 overflow-hidden rounded-lg border border-border/80 bg-card">
      <img
        src={buildFileApiUrl(uiExtra.file_path, sessionId)}
        alt={uiExtra.file_path}
        className="block h-auto max-h-[420px] w-auto max-w-full"
        loading="lazy"
      />
      <div className="truncate border-t border-border/80 bg-surface px-3 py-1.5 font-mono text-sm text-neutral-600">
        {uiExtra.file_path}
      </div>
    </div>
  );
}
