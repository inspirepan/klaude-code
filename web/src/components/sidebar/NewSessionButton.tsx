import { Button } from "@/components/ui/button";

interface NewSessionButtonProps {
  onClick: () => void;
}

export function NewSessionButton({ onClick }: NewSessionButtonProps): JSX.Element {
  return (
    <Button
      type="button"
      variant="outline"
      className="h-8 w-full justify-center rounded-lg border-gray-200 text-[13px] font-normal text-neutral-900 hover:bg-neutral-100"
      onClick={() => {
        onClick();
      }}
    >
      New Agent
    </Button>
  );
}
