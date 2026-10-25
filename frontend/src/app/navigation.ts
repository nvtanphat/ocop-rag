import type { IconName } from "../components/Icon";

export type View = "chat" | "documents" | "criteria" | "products" | "history";
export const navigation: Array<{ id: View; label: string; icon: IconName }> = [
  { id: "chat", label: "Chat", icon: "chat" },
  { id: "documents", label: "Tài liệu", icon: "file" },
  { id: "criteria", label: "Tiêu chí", icon: "criteria" },
  { id: "products", label: "Sản phẩm", icon: "award" },
  { id: "history", label: "Lịch sử", icon: "history" },
];
