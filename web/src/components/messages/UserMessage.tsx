import type { UserMessageItem } from "../../types/message";

interface UserMessageProps {
  item: UserMessageItem;
}

export function UserMessage({ item }: UserMessageProps): JSX.Element {
  return (
    <div className="rounded-xl bg-[#f0f0f2] border border-zinc-200/60 px-4 py-3">
      <p className="text-[15px] leading-relaxed text-zinc-800 whitespace-pre-wrap break-words m-0">
        {item.content}
      </p>
    </div>
  );
}
