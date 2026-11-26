import type { ReactNode } from "react";
import clsx from "clsx";
import CrtStaticText from "./CrtStaticText";

type StudioPageProps = {
  eyebrow: string;
  title: string;
  /** Short line under the title. */
  subtitle?: ReactNode;
  /** The page's main action(s), shown on the right of the header. */
  actions?: ReactNode;
  /** Header sticks under the nav bar (for long pages whose main action matters everywhere). */
  stickyHeader?: boolean;
  children: ReactNode;
  className?: string;
};

/** Shared frame for every screen under the nav: background, scanlines, shell and header. */
export default function StudioPage({
  eyebrow,
  title,
  subtitle,
  actions,
  stickyHeader,
  children,
  className,
}: StudioPageProps) {
  return (
    <div className="relative flex flex-1 flex-col bg-crt-bg px-2 py-3 scanlines sm:px-6 sm:py-6">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(255,43,157,0.12),transparent_28%),radial-gradient(circle_at_bottom_right,rgba(26,255,228,0.08),transparent_30%)]" />

      <section className={clsx("retro-shell relative mx-auto w-full max-w-[1800px] flex-1 px-4 py-5 sm:px-8 sm:py-8", stickyHeader && "!overflow-visible")}>
        <div className="relative z-10 flex h-full flex-col gap-6">
          <div
            className={clsx(
              "flex flex-col gap-5 border-b border-phosphor/15 pb-6 lg:flex-row lg:items-end lg:justify-between",
              stickyHeader && "z-40 -mx-4 -mt-5 bg-crt-deep/95 px-4 pb-4 pt-5 backdrop-blur-md sm:-mx-8 sm:-mt-8 sm:px-8 sm:pt-6 md:sticky md:top-16"
            )}
          >
            <div className="min-w-0 max-w-3xl">
              <p className="type-eyebrow">{eyebrow}</p>
              <CrtStaticText
                as="h1"
                text={title}
                className="mt-1 max-w-full"
                textClassName={clsx("type-display glow-text break-words text-magenta-soft", stickyHeader ? "text-3xl sm:text-4xl" : "text-4xl sm:text-5xl")}
              />
              {subtitle ? <div className="type-body mt-3">{subtitle}</div> : null}
            </div>
            {actions ? <div className="flex flex-wrap items-center gap-3">{actions}</div> : null}
          </div>

          <div className={clsx("flex flex-1 flex-col gap-6", className)}>{children}</div>
        </div>
      </section>
    </div>
  );
}
