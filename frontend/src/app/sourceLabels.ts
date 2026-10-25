import type { Source } from "../api/client";

export type DocGroup = "OCOP" | "LAW" | "LOCAL";
export const docGroups: Array<{ id: DocGroup; label: string; color: string }> = [
  { id: "OCOP", label: "Quy định OCOP", color: "#e8453c" },
  { id: "LAW", label: "Luật & Nghị định", color: "#13a06a" },
  { id: "LOCAL", label: "Văn bản địa phương", color: "#f09a1a" },
];

export function groupOf(kind: string | null): DocGroup {
  if (kind?.startsWith("ocop")) return "OCOP";
  if (kind && /law|decree|resolution|labeling|food_safety/.test(kind)) return "LAW";
  return "LOCAL";
}

export const groupColor = (kind: string | null) =>
  docGroups.find((group) => group.id === groupOf(kind))!.color;

export const sourceTitle = (source: Source | undefined, fallback: string) =>
  source?.document_number || source?.filename || fallback;

// Short badge: the leading number of a document code ("525/QĐ-UBND" -> "525").
export const sourceBadge = (source: Source) => {
  const lead = source.document_number?.split("/")[0]?.trim();
  return lead && lead.length <= 4 ? lead : "PDF";
};

export const normalize = (value: string) =>
  value
    .toLowerCase()
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/đ/g, "d");
