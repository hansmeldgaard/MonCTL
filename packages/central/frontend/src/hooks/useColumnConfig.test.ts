/**
 * Tests for `useColumnConfig.compact()` (T-WEB-001 / memory
 * `feedback_column_config_compact_false`).
 *
 * The pure helper survived a regression: a truthy `if (entry.hidden)`
 * check used to drop `hidden: false`, which broke columns the user had
 * explicitly un-hid from a `defaultHidden: true` definition. Once the
 * stored config dropped the explicit `false`, `cfg?.hidden ?? col.defaultHidden`
 * resolved back to `defaultHidden=true` on the next render and the
 * column re-hid itself — reverting the user's preference silently.
 *
 * The fix flipped the check to `entry.hidden != null` so both `true`
 * and `false` survive. This file pins that contract.
 */
import { describe, expect, it } from "vitest";
import { compact } from "./useColumnConfig.ts";

describe("compact", () => {
  it("keeps hidden:true entries intact", () => {
    expect(compact({ name: { hidden: true } })).toEqual({
      name: { hidden: true },
    });
  });

  it("keeps hidden:false entries intact (the regression case)", () => {
    // Pre-fix: truthy `if (entry.hidden)` dropped this entry, so
    // `defaultHidden=true` would silently re-hide on next render.
    expect(compact({ name: { hidden: false } })).toEqual({
      name: { hidden: false },
    });
  });

  it("drops empty entries (no width / hidden / order)", () => {
    expect(compact({ name: {} })).toEqual({});
  });

  it("preserves width-only entries", () => {
    expect(compact({ name: { width: 200 } })).toEqual({
      name: { width: 200 },
    });
  });

  it("preserves order-only entries including order:0", () => {
    // `order: 0` must survive — pinning a column to the leftmost
    // position is a meaningful preference. A truthy check would
    // wrongly drop it.
    expect(compact({ name: { order: 0 } })).toEqual({
      name: { order: 0 },
    });
  });

  it("preserves combinations + drops sibling empty entries", () => {
    const input = {
      name: { width: 240, hidden: false, order: 1 },
      address: {},
      type: { hidden: true },
    };
    expect(compact(input)).toEqual({
      name: { width: 240, hidden: false, order: 1 },
      type: { hidden: true },
    });
  });

  it("treats null/undefined fields as absent", () => {
    expect(
      compact({
        name: { width: undefined, hidden: undefined, order: undefined },
        address: { width: null as unknown as number },
      }),
    ).toEqual({});
  });

  it("returns a new object — input is not mutated", () => {
    const input = { name: { width: 100 } };
    const out = compact(input);
    expect(out).not.toBe(input);
    expect(input).toEqual({ name: { width: 100 } });
  });
});
