import { cn } from "@/lib/utils";
import { splitSessionTitle } from "./session-title";

interface SessionTitleTextProps {
  title: string;
  as?: "div" | "span";
  truncate?: boolean;
  className?: string;
  primaryClassName?: string;
  separatorClassName?: string;
  secondaryClassName?: string;
}

export function SessionTitleText({
  title,
  as = "div",
  truncate = true,
  className,
  primaryClassName,
  separatorClassName,
  secondaryClassName,
}: SessionTitleTextProps): JSX.Element {
  const { primary, secondary } = splitSessionTitle(title);
  const Container = as;

  return (
    <Container className={cn("min-w-0", className)}>
      <span
        className={cn("min-w-0 shrink text-neutral-800", truncate && "truncate", primaryClassName)}
        title={primary}
      >
        {primary}
      </span>
      {secondary ? (
        <>
          <span
            className={cn("mx-1 shrink-0 text-neutral-300", separatorClassName)}
            aria-hidden="true"
          >
            |
          </span>
          <span
            className={cn(
              "min-w-0 flex-1 text-neutral-500",
              truncate && "truncate",
              secondaryClassName,
            )}
            title={secondary}
          >
            {secondary}
          </span>
        </>
      ) : null}
    </Container>
  );
}
