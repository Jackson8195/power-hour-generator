import { matchPath } from "react-router-dom";

export type Crumb = { label: string; to?: string };

/** Where each screen sits, so the nav can show breadcrumbs and Back never leaves the app. */
const ROUTES: { pattern: string; label: string; parent: string | null }[] = [
  { pattern: "/create", label: "Create New", parent: "/" },
  { pattern: "/works-in-progress", label: "Works In Progress", parent: "/" },
  { pattern: "/project/:id", label: "Project", parent: "/works-in-progress" },
  { pattern: "/power-hours", label: "Tape Shelf", parent: "/" },
  { pattern: "/auto-generate", label: "Auto Generate", parent: "/" },
  { pattern: "/auto-generate/progress/:jobId", label: "Building", parent: "/auto-generate" },
];

function findRoute(pathname: string) {
  return ROUTES.find((route) => matchPath(route.pattern, pathname));
}

export function parentPath(pathname: string): string {
  return findRoute(pathname)?.parent ?? "/";
}

/** Breadcrumbs after HOME. `currentLabel` overrides the last crumb (e.g. the project name). */
export function crumbsFor(pathname: string, currentLabel?: string): Crumb[] {
  const chain: Crumb[] = [];
  let route = findRoute(pathname);
  let path = pathname;
  while (route) {
    chain.unshift({ label: route.label, to: path });
    if (!route.parent || route.parent === "/") break;
    path = route.parent;
    route = findRoute(path);
  }
  if (chain.length && currentLabel) {
    chain[chain.length - 1] = { ...chain[chain.length - 1], label: currentLabel };
  }
  // The last crumb is the current page: not a link.
  if (chain.length) chain[chain.length - 1] = { label: chain[chain.length - 1].label };
  return chain;
}
