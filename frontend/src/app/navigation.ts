import type { IconName } from "../components/Icon";

export type View = "chat" | "documents" | "criteria" | "products" | "history";
export const navigation: Array<{
  id: Exclude<View, "history">;
  label: string;
  title: string;
  icon: IconName;
}> = [
  { id: "chat", label: "Chat", title: "Trò chuyện", icon: "chat" },
  { id: "documents", label: "Tài liệu", title: "Thư viện văn bản", icon: "docs" },
  { id: "criteria", label: "Tiêu chí", title: "Bảng tiêu chí", icon: "criteria" },
  { id: "products", label: "Sản phẩm", title: "Sản phẩm đạt chuẩn", icon: "award" },
];
