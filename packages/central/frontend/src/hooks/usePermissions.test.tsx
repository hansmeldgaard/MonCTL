/**
 * Tests for the `usePermissions` hook.
 *
 * Pure logic on top of `useAuth().user.{role,permissions}`:
 *   - role === "admin" bypasses the permission list
 *   - hasPermission(resource, action) checks `${resource}:${action}`
 *     against `user.permissions`
 *   - canView/canCreate/canEdit/canDelete/canManage are thin
 *     forwarders that hard-code the action
 */
import { describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";

import { usePermissions } from "./usePermissions.ts";

vi.mock("@/hooks/useAuth.tsx", () => ({
  useAuth: vi.fn(),
}));

import { useAuth } from "@/hooks/useAuth.tsx";

const mockedUseAuth = vi.mocked(useAuth);

function setUser(user: unknown) {
  mockedUseAuth.mockReturnValue({ user } as never);
}

describe("usePermissions — admin bypass", () => {
  it("admin role grants every permission, ignoring the permissions list", () => {
    setUser({ role: "admin", permissions: [] });
    const { result } = renderHook(() => usePermissions());
    expect(result.current.isAdmin).toBe(true);
    expect(result.current.hasPermission("device", "delete")).toBe(true);
    expect(result.current.canManage("anything")).toBe(true);
    expect(result.current.canCreate("apps_with_a_typo")).toBe(true);
  });
});

describe("usePermissions — non-admin users", () => {
  it("returns false when user is null/undefined (logged out / loading)", () => {
    setUser(null);
    const { result } = renderHook(() => usePermissions());
    expect(result.current.isAdmin).toBe(false);
    expect(result.current.hasPermission("device", "view")).toBe(false);
    expect(result.current.canView("anything")).toBe(false);
  });

  it("returns false when permissions list is missing", () => {
    setUser({ role: "user" });
    const { result } = renderHook(() => usePermissions());
    expect(result.current.hasPermission("device", "view")).toBe(false);
  });

  it("matches `${resource}:${action}` against the permissions list", () => {
    setUser({ role: "user", permissions: ["device:view", "alert:edit"] });
    const { result } = renderHook(() => usePermissions());
    expect(result.current.hasPermission("device", "view")).toBe(true);
    expect(result.current.hasPermission("device", "edit")).toBe(false);
    expect(result.current.hasPermission("alert", "edit")).toBe(true);
    expect(result.current.hasPermission("alert", "view")).toBe(false);
  });

  it("canView/canCreate/canEdit/canDelete/canManage forward the right action", () => {
    setUser({
      role: "user",
      permissions: [
        "device:view",
        "device:create",
        "alert:edit",
        "credential:delete",
        "user:manage",
      ],
    });
    const { result } = renderHook(() => usePermissions());
    expect(result.current.canView("device")).toBe(true);
    expect(result.current.canCreate("device")).toBe(true);
    expect(result.current.canEdit("alert")).toBe(true);
    expect(result.current.canDelete("credential")).toBe(true);
    expect(result.current.canManage("user")).toBe(true);

    // Negative cases — same resource, wrong action
    expect(result.current.canEdit("device")).toBe(false);
    expect(result.current.canManage("device")).toBe(false);
  });

  it("admin shortcut wins even with an empty permissions list", () => {
    setUser({ role: "admin" });
    const { result } = renderHook(() => usePermissions());
    expect(result.current.canDelete("anything")).toBe(true);
  });
});
