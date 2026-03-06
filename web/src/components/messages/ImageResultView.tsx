import { buildFileApiUrl } from "../../api/client";

interface ImageUIExtra {
  type: "image";
  file_path: string;
}

export function isImageUIExtra(extra: unknown): extra is ImageUIExtra {
  if (typeof extra !== "object" || extra === null) return false;
  const record = extra as Record<string, unknown>;
  return record.type === "image" && typeof record.file_path === "string";
}

interface ImageResultViewProps {
  uiExtra: ImageUIExtra;
  compact?: boolean;
}

export function ImageResultView({ uiExtra, compact = false }: ImageResultViewProps): JSX.Element {
  return (
    <div className="mt-1 rounded-lg border border-neutral-200/80 overflow-hidden bg-white">
      <img
        src={buildFileApiUrl(uiExtra.file_path)}
        alt={uiExtra.file_path}
        className="block max-w-full max-h-[420px] w-auto h-auto"
        loading="lazy"
      />
      <div className={`px-3 py-1.5 bg-neutral-50 border-t border-neutral-200/80 ${compact ? "text-[11px]" : "text-xs"} text-neutral-400 font-mono truncate`}>
        {uiExtra.file_path}
      </div>
    </div>
  );
}
