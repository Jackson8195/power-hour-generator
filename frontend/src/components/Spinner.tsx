import clsx from "clsx";

/** Three-bar VU loader; drop-in for a spinning icon (size it with h-/w- classes). */
export default function Spinner({ className }: { className?: string }) {
  return (
    <span className={clsx("vu-loader shrink-0", className)} role="status" aria-label="Working">
      <span />
      <span />
      <span />
    </span>
  );
}
