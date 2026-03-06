import { Button } from "@/components/ui/button";

interface NewSessionButtonProps {
  onClick: () => void;
}

export function NewSessionButton({ onClick }: NewSessionButtonProps): JSX.Element {
  return (
    <Button
      variant="outline"
      className="w-full justify-center rounded-lg text-[14px] font-normal text-neutral-900 border-gray-200 h-8 hover:bg-neutral-100"
      onClick={onClick}
    >
      New Agent
    </Button>
  );
}
