import { Button } from "@/components/ui/button";

interface NewSessionButtonProps {
  onClick: () => void;
}

export function NewSessionButton({ onClick }: NewSessionButtonProps): JSX.Element {
  return (
    <Button
      type="button"
      variant="outline"
      className="h-8 w-full justify-center gap-1.5 rounded-lg border-neutral-200 text-[13px] font-normal text-neutral-900 hover:bg-neutral-100"
      onClick={() => {
        onClick();
      }}
    >
      <span>New Agent</span>
      <span className="inline-flex items-center text-neutral-400" aria-hidden="true">
        <kbd className="inline-flex h-4 items-center justify-center rounded-[4px] border border-neutral-300 bg-neutral-100 px-1.5 text-[10px] leading-none">
          ⇧ ⌘ O
        </kbd>
      </span>
    </Button>
  );
}
