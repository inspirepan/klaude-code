import { OctagonX } from "lucide-react";

import { useT } from "@/i18n";
import type { InterruptItem } from "../../types/message";

interface InterruptMessageProps {
  item: InterruptItem;
}

export function InterruptMessage(props: InterruptMessageProps): JSX.Element {
  const t = useT();
  void props;
  return (
    <div className="inline-flex items-center gap-1.5 text-base text-amber-700">
      <OctagonX className="h-3.5 w-3.5" strokeWidth={2.25} />
      <span>{t("interrupt.message")}</span>
    </div>
  );
}
