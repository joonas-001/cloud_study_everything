export type NavigationItem = {
  id: "today" | "learning" | "evidence" | "goals" | "inbox" | "settings";
  label: string;
  href: string;
  paths: readonly string[];
};

export type MobileNavigationItem = {
  id: "today" | "learning" | "evidence" | "inbox" | "more";
  label: string;
  shortLabel: string;
  href: string;
};

export const PRIMARY_NAVIGATION: readonly NavigationItem[] = [
  { id: "today", label: "今日", href: "/", paths: ["/"] },
  {
    id: "learning",
    label: "学习",
    href: "/learning",
    paths: ["/learning", "/diagnostic"],
  },
  { id: "evidence", label: "证据", href: "/evidence", paths: ["/evidence"] },
  {
    id: "goals",
    label: "目标与行动",
    href: "/goals",
    paths: ["/goals", "/readiness", "/market-research", "/experiments"],
  },
  { id: "inbox", label: "收件箱", href: "/inbox", paths: ["/inbox"] },
  { id: "settings", label: "设置", href: "/settings", paths: ["/settings"] },
] as const;

export const MOBILE_NAVIGATION: readonly MobileNavigationItem[] = [
  { id: "today", label: "今日", shortLabel: "今", href: "/" },
  { id: "learning", label: "学习", shortLabel: "学", href: "/learning" },
  { id: "evidence", label: "证据", shortLabel: "证", href: "/evidence" },
  { id: "inbox", label: "收件箱", shortLabel: "信", href: "/inbox" },
  { id: "more", label: "更多", shortLabel: "···", href: "/more" },
] as const;

function pathMatches(pathname: string, candidate: string): boolean {
  if (candidate === "/") {
    return pathname === "/";
  }
  return pathname === candidate || pathname.startsWith(`${candidate}/`);
}

export function getActiveSection(pathname: string): NavigationItem["id"] | null {
  return (
    PRIMARY_NAVIGATION.find((item) =>
      item.paths.some((candidate) => pathMatches(pathname, candidate)),
    )?.id ?? null
  );
}

export function getActiveMobileSection(pathname: string): MobileNavigationItem["id"] {
  if (pathMatches(pathname, "/more")) {
    return "more";
  }
  const section = getActiveSection(pathname);
  if (section === "goals" || section === "settings") {
    return "more";
  }
  return section ?? "today";
}
