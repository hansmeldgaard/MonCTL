import { useAuth } from "@/hooks/useAuth.tsx";

export function useTimezone(): string {
  const { user } = useAuth();
  return user?.timezone ?? "UTC";
}
