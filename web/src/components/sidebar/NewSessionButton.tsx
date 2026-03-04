import { Button } from "@/components/ui/button";

interface NewSessionButtonProps {
  onClick: () => void;
}

export function NewSessionButton({ onClick }: NewSessionButtonProps): JSX.Element {
  return (
    <Button
      variant="outline"
      className="w-full justify-center rounded-lg text-[14px] font-normal text-zinc-900 border-gray-200 h-10 hover:bg-zinc-100"
      onClick={onClick}
    >
      New Agent
    </Button>
  );
}
