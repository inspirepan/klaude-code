import { createContext, useContext } from "react";

export interface SearchState {
  query: string;
  matchItemIds: string[];
  activeIndex: number;
}

const defaultState: SearchState = {
  query: "",
  matchItemIds: [],
  activeIndex: -1,
};

const SearchContext = createContext(defaultState);

export const SearchProvider = SearchContext.Provider;

export function useSearch(): SearchState {
  return useContext(SearchContext);
}
