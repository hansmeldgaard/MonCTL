import { useAuth } from "@/hooks/useAuth.tsx";
import { useUpdateTablePreferences } from "@/api/hooks.ts";

export const PAGE_SIZE_OPTIONS = [50, 100, 250, 500] as const;

export function useTablePreferences() {
  const { user, refresh } = useAuth();
  const mutation = useUpdateTablePreferences();

  return {
    pageSize: user?.table_page_size ?? 50,
    scrollMode: (user?.table_scroll_mode ?? "paginated") as
      | "paginated"
      | "infinite",
    updatePreferences: async (prefs: {
      table_page_size?: number;
      table_scroll_mode?: "paginated" | "infinite";
    }) => {
      await mutation.mutateAsync(prefs);
      await refresh();
    },
    isUpdating: mutation.isPending,
  };
}
