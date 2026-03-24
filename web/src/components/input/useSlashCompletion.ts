import { useCallback, useEffect, useState, type RefObject } from "react";
import { fetchSkills, type SkillItem } from "@/api/client";
import type { SlashCompletionItem } from "./SlashCompletionList";

const SLASH_COMPLETION_PATTERN = /^(?<prefix>\/\/|\/)(?<frag>[^\s/]*)$/;

const COMPACT_COMPLETION_ITEM: SlashCompletionItem = {
  kind: "command",
  name: "compact",
  description: "Clear context, keep summary",
  insertText: "/compact ",
};

/** Rank a skill match. Lower values = better match. Returns null when no match. */
function skillMatchRank(
  name: string,
  description: string,
  frag: string,
): [number, number, number, number, number, number, number] | null {
  const nameLower = name.toLowerCase();
  const descLower = description.toLowerCase();
  const tokenLower = `skill:${nameLower}`;

  const namePrefix = nameLower.startsWith(frag);
  const segmentPrefix = nameLower.split(/[-_:]/).some((seg) => seg.startsWith(frag));
  const tokenPrefix = tokenLower.startsWith(frag);
  const nameContains = nameLower.includes(frag);
  const tokenContains = tokenLower.includes(frag);
  const descContains = descLower.includes(frag);

  if (!nameContains && !tokenContains && !descContains) return null;

  return [
    namePrefix ? 0 : 1,
    segmentPrefix ? 0 : 1,
    tokenPrefix ? 0 : 1,
    nameContains ? 0 : 1,
    tokenContains ? 0 : 1,
    descContains ? 0 : 1,
    nameLower.length,
  ];
}

function compareRanks(
  a: [number, number, number, number, number, number, number],
  b: [number, number, number, number, number, number, number],
): number {
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return a[i] - b[i];
  }
  return 0;
}

function buildSlashCompletionItems(
  prefix: string,
  fragment: string,
  skills: SkillItem[],
  showCommands: boolean,
): SlashCompletionItem[] {
  const items: SlashCompletionItem[] = [];
  const frag = fragment.toLowerCase();

  if (showCommands && prefix === "/") {
    if (frag === "" || "compact".includes(frag)) {
      items.push(COMPACT_COMPLETION_ITEM);
    }
  }

  if (frag === "") {
    for (const skill of skills) {
      items.push({
        kind: "skill",
        name: skill.name,
        description: skill.description,
        location: skill.location,
        insertText: `${prefix}skill:${skill.name} `,
      });
    }
    return items;
  }

  const ranked: { item: SlashCompletionItem; rank: ReturnType<typeof skillMatchRank> & object }[] =
    [];
  for (const skill of skills) {
    const rank = skillMatchRank(skill.name, skill.description, frag);
    if (rank === null) continue;
    ranked.push({
      item: {
        kind: "skill",
        name: skill.name,
        description: skill.description,
        location: skill.location,
        insertText: `${prefix}skill:${skill.name} `,
      },
      rank,
    });
  }
  ranked.sort((a, b) => compareRanks(a.rank, b.rank));
  for (const entry of ranked) {
    items.push(entry.item);
  }

  return items;
}

interface UseSlashCompletionOptions {
  skillWorkDir?: string;
  hasCompact: boolean;
  onTextChange: (text: string) => void;
  textareaRef: RefObject<HTMLTextAreaElement>;
}

export interface SlashCompletionState {
  items: SlashCompletionItem[];
  highlightIndex: number;
  open: boolean;
  setHighlightIndex: (index: number) => void;
  update: (nextText: string, cursorPosition: number | null) => void;
  apply: (item: SlashCompletionItem) => void;
  close: () => void;
}

export function useSlashCompletion({
  skillWorkDir,
  hasCompact,
  onTextChange,
  textareaRef,
}: UseSlashCompletionOptions): SlashCompletionState {
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [items, setItems] = useState<SlashCompletionItem[]>([]);
  const [highlightIndex, setHighlightIndex] = useState(0);

  const open = items.length > 0;

  const close = useCallback(() => {
    setItems([]);
    setHighlightIndex(0);
  }, []);

  const update = useCallback(
    (nextText: string, cursorPosition: number | null) => {
      const resolvedCursor = cursorPosition ?? nextText.length;
      const textBeforeCursor = nextText.slice(0, resolvedCursor);
      const match = SLASH_COMPLETION_PATTERN.exec(textBeforeCursor);
      if (!match?.groups) {
        setItems([]);
        setHighlightIndex(0);
        return;
      }
      const completionItems = buildSlashCompletionItems(
        match.groups.prefix,
        match.groups.frag,
        skills,
        hasCompact,
      );
      setItems(completionItems);
      setHighlightIndex(0);
    },
    [skills, hasCompact],
  );

  const apply = useCallback(
    (item: SlashCompletionItem) => {
      onTextChange(item.insertText);
      close();

      requestAnimationFrame(() => {
        const textarea = textareaRef.current;
        if (!textarea) {
          return;
        }
        textarea.focus();
        const pos = item.insertText.length;
        textarea.setSelectionRange(pos, pos);
      });
    },
    [close, onTextChange, textareaRef],
  );

  useEffect(() => {
    let cancelled = false;
    void fetchSkills(skillWorkDir)
      .then((fetchedSkills) => {
        if (!cancelled) {
          setSkills(fetchedSkills);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [skillWorkDir]);

  return { items, highlightIndex, open, setHighlightIndex, update, apply, close };
}
