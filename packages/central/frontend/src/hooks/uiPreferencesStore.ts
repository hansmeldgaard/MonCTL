import type { UiPreferences } from "@/types/api.ts";

/** Module-level store for the user's ui_preferences blob. Both
 *  useColumnConfig and useDisplayPreferences fire `PUT /users/me/
 *  ui-preferences` with the *full* blob on every change — if each
 *  hook merged into its own cached copy of `user.ui_preferences`,
 *  concurrent edits would clobber each other (later writes overwrite
 *  the earlier ones because they don't know about the other hook's
 *  in-flight change). A single shared snapshot keeps them atomic. */

let current: UiPreferences = {};
const listeners = new Set<() => void>();

function notify() {
  for (const l of listeners) l();
}

/** Hydrate the store from an authoritative server value (auth refresh,
 *  login response). Does nothing if the incoming value is undefined. */
export function hydrateUiPreferences(next: UiPreferences | undefined): void {
  if (!next) return;
  current = next;
  notify();
}

/** Read the current best-known prefs. */
export function readUiPreferences(): UiPreferences {
  return current;
}

/** Atomically mutate and return the new value. Callers pass a pure
 *  transform so interleaved writes from multiple hooks compose. */
export function mutateUiPreferences(
  fn: (prev: UiPreferences) => UiPreferences,
): UiPreferences {
  current = fn(current);
  notify();
  return current;
}

/** Subscribe to any change — used by hooks that want to re-render on
 *  store updates triggered by sibling hooks. */
export function subscribeUiPreferences(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
