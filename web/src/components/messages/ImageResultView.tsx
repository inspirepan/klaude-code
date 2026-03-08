import { buildFileApiUrl } from "../../api/client";
import type { ImageUIExtra } from "./message-ui-extra";

interface ImageResultViewProps {
  uiExtra: ImageUIExtra;
  compact?: boolean;
}

export function ImageResultView({ uiExtra, compact = false }: ImageResultViewProps): JSX.Element {
  return (
    <div className="mt-1 overflow-hidden rounded-lg border border-neutral-200/80 bg-white">
      <img
        src={buildFileApiUrl(uiExtra.file_path)}
        alt={uiExtra.file_path}
        className="block h-auto max-h-[420px] w-auto max-w-full"
        loading="lazy"
      />
      <div
        className={`border-t border-neutral-200/80 bg-neutral-50 px-3 py-1.5 ${compact ? "text-2xs" : "text-xs"} truncate font-mono text-neutral-400`}
      >
        {uiExtra.file_path}
      </div>
    </div>
  );
}
