import type { ComponentProps } from "react";

type Props = Omit<ComponentProps<"svg">, "open"> & {
  open: boolean;
  /** Milliseconds for the morph. */
  duration?: number;
};

/** A hamburger that draws itself into a cross. One path slides its dash, the whole icon turns. Styles: `.mt-ico` in globals.css. */
export function MenuToggleIcon({ open, className, duration = 500, style, ...props }: Props) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={["mt-ico", open ? "open" : "", className].filter(Boolean).join(" ")}
      style={{ ["--mt-d" as string]: `${duration}ms`, ...style }}
      {...props}
    >
      <path className="mt-path" d="M27 10 13 10C10.8 10 9 8.2 9 6 9 3.5 10.8 2 13 2 15.2 2 17 3.8 17 6L17 26C17 28.2 18.8 30 21 30 23.2 30 25 28.2 25 26 25 23.8 23.2 22 21 22L7 22" />
      <path d="M7 16 27 16" />
    </svg>
  );
}
