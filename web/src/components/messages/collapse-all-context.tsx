import { createContext, useContext } from "react";

export interface CollapseAllState {
  /** Incremented each time "collapse all" is triggered. */
  collapseGen: number;
  /** Incremented each time "expand all" is triggered. */
  expandGen: number;
}

export const CollapseAllContext = createContext<CollapseAllState>({ collapseGen: 0, expandGen: 0 });

export function useCollapseAll(): CollapseAllState {
  return useContext(CollapseAllContext);
}
