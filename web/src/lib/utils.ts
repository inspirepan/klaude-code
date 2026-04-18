import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// Single-line truncation with a right-edge fade mask instead of "…".
// Only use on elements whose width is forced to stretch (block-level,
// grid cell with 1fr, or w-full); otherwise a non-overflowing span will
// size to its content and fade visible characters on the right.
export const FADE_TRUNCATE =
  "overflow-hidden whitespace-nowrap [mask-image:linear-gradient(to_right,black_calc(100%-2rem),transparent)]";
