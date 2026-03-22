import { Button } from "@/components/ui/button";

interface NewSessionButtonProps {
  onClick: () => void;
}

export function NewSessionButton({ onClick }: NewSessionButtonProps): JSX.Element {
  return (
    <Button
      type="button"
      variant="outline"
      className="h-8 w-full min-w-0 justify-center gap-1.5 overflow-hidden rounded-lg border-border px-2.5 text-base font-normal text-neutral-900 hover:bg-muted"
      onClick={() => {
        onClick();
      }}
    >
      <span className="truncate">New</span>
      <span className="inline-flex shrink-0 items-center text-neutral-500" aria-hidden="true">
        <span className="inline-flex whitespace-pre text-sm leading-none">
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
