import { useAuth } from "@/hooks/useAuth.tsx";

export function usePermissions() {
  const { user } = useAuth();

  const isAdmin = user?.role === "admin";

  function hasPermission(resource: string, action: string): boolean {
    if (isAdmin) return true;
    return user?.permissions?.includes(`${resource}:${action}`) ?? false;
  }

  function canView(resource: string) { return hasPermission(resource, "view"); }
  function canCreate(resource: string) { return hasPermission(resource, "create"); }
  function canEdit(resource: string) { return hasPermission(resource, "edit"); }
  function canDelete(resource: string) { return hasPermission(resource, "delete"); }
  function canManage(resource: string) { return hasPermission(resource, "manage"); }

  return { isAdmin, hasPermission, canView, canCreate, canEdit, canDelete, canManage };
}
