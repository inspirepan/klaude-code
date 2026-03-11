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
      <span className="ml-1.5">New Agent</span>
      <span className="inline-flex items-center text-neutral-400" aria-hidden="true">
        <span className="inline-flex whitespace-pre text-[12px] leading-none">
          <kbd className="inline-flex font-sans">
            <span className="min-w-[1em] text-center">⇧</span>
          </kbd>
          <kbd className="inline-flex font-sans">
            <span className="min-w-[1em] text-center">⌘</span>
          </kbd>
          <kbd className="inline-flex font-sans">
            <span className="min-w-[1em] text-center">O</span>
          </kbd>
        </span>
      </span>
    </Button>
  );
}
