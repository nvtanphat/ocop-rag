import type { CSSProperties } from "react";

// Static SVG fragments (no user input), drawn on a 24x24 grid.
const inner = {
  chat: '<path d="M4 5h16v11H11l-5 4v-4H4z"/><path d="M8 9.5h8M8 12.5h5"/>',
  docs: '<rect x="5" y="3" width="14" height="18" rx="2.5"/><path d="M8.5 8h7M8.5 12h7M8.5 16h4"/>',
  criteria: '<rect x="5" y="3" width="14" height="18" rx="2.5"/><path d="M9 12l2 2 4-4"/>',
  award: '<circle cx="12" cy="9" r="5"/><path d="M9 13.5L7.5 21l4.5-2.5 4.5 2.5L15 13.5"/>',
  store: '<path d="M4 9l2-5h12l2 5v1a3 3 0 01-6 0 3 3 0 01-6 0 3 3 0 01-4 0zM5 13v7h14v-7"/>',
  history: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>',
  moon: '<path d="M21 13A9 9 0 1 1 11 3a7 7 0 0 0 10 10Z"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.5a2.5 2.5 0 114 2c-.9.6-1.6 1-1.6 2M12 17v.2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M16 16l5 5"/>',
  send: '<path d="M21 3L3 10l7 3 3 7z"/><path d="M10 13l11-10"/>',
  bolt: '<path d="M13 2L4 14h6l-1 8 9-12h-6z" fill="#f5b014" stroke="#f5b014" stroke-width="1"/>',
  graph: '<circle cx="5" cy="6" r="2.2"/><circle cx="19" cy="6" r="2.2"/><circle cx="12" cy="18" r="2.2"/><path d="M7 7l4 9M17 7l-4 9M7.2 6h9.6"/>',
  left: '<path d="M15 5l-7 7 7 7"/>',
  right: '<path d="M9 5l7 7-7 7"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  refresh: '<path d="M20 7a9 9 0 0 0-15-2L2 8m0-6v6h6m-4 9a9 9 0 0 0 15 2l3-3m0 6v-6h-6"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 00-2-2H6a2 2 0 00-2 2v8a2 2 0 002 2h2"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1h5"/>',
  expand: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  open: '<path d="M14 4h6v6M20 4l-8 8M10 20H4v-6"/>',
  region: '<rect x="4" y="4" width="16" height="16" rx="3"/><circle cx="12" cy="12" r="3"/>',
  fit: '<rect x="5" y="5" width="14" height="14" rx="3"/><circle cx="12" cy="12" r="2.5"/>',
  gridView: '<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/>',
  listView: '<path d="M5 7h14M5 12h14M5 17h14"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  list: '<path d="M5 6h14M5 12h14M5 18h8"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16v.5"/>',
  compare: '<path d="M7 7h12l-3-3M17 17H5l3 3"/>',
  person: '<circle cx="12" cy="8" r="4"/><path d="M5 21c0-4 3-6 7-6s7 2 7 6"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/>',
  page: '<rect x="5" y="3" width="14" height="18" rx="2"/>',
  pages: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6"/>',
  box: '<path d="m12 2 9 5v10l-9 5-9-5V7l9-5Zm-9 5 9 5 9-5M12 12v10"/>',
  userSolid: '<g fill="currentColor" stroke="none"><circle cx="12" cy="8" r="4.2"/><path d="M4 21c0-4.2 3.6-7 8-7s8 2.8 8 7z"/></g>',
  hlDot: '<circle cx="12" cy="12" r="10" fill="#e0343c" stroke="none"/><circle cx="12" cy="12" r="3.5" stroke="#fff" stroke-width="2"/>',
  checkBadge: '<circle cx="12" cy="12" r="10" fill="#18a56e" stroke="none"/><path d="M7 12.5l3.2 3L17 9" stroke="#fff" stroke-width="2.6"/>',
  leaf: '<path d="M20 4C8 2 2 9 6 16s16 3 14-12ZM4 21 16 9"/>',
} as const;

export type IconName = keyof typeof inner;
export function Icon({
  name,
  size = 20,
  strokeWidth = 1.7,
  className,
  style,
}: {
  name: IconName;
  size?: number;
  strokeWidth?: number;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
      style={style}
      dangerouslySetInnerHTML={{ __html: inner[name] }}
    />
  );
}
