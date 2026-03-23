import { OctagonX } from "lucide-react";

import { useT } from "@/i18n";
import type { InterruptItem } from "../../types/message";
import { COLLAPSE_RAIL_GRID_CLASS_NAME } from "./CollapseRail";

interface InterruptMessageProps {
  item: InterruptItem;
}

export function InterruptMessage(props: InterruptMessageProps): JSX.Element {
  const t = useT();
  void props;
  return (
    <div className={`grid items-center ${COLLAPSE_RAIL_GRID_CLASS_NAME} py-1 text-base text-amber-700`}>
      <span className="flex h-[1lh] items-center justify-center">
        <OctagonX className="h-3.5 w-3.5" strokeWidth={2.25} />
      </span>
      <span>{t("interrupt.message")}</span>
    </div>
  );
}
