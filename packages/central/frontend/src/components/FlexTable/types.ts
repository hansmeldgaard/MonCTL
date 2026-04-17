import type { ReactNode } from "react";

/** Declarative column shape consumed by FlexTable. Each column has a
 *  stable `key` — that's how hidden/width/order config travels across
 *  releases even as the `columns` array changes shape in code. */
export interface FlexColumnDef<TRow> {
  /** Unique, stable identifier. Used as the sort/filter field name AND
   *  as the key in stored ColumnConfigMap. Don't rename without a
   *  schema bump. */
  key: string;
  /** Header label. Accepts ReactNode so columns like the
   *  selection-checkbox can render a control in place of text. */
  label: ReactNode;
  /** Picker-menu label — required when `label` is a ReactNode so the
   *  checklist can show a human-readable string. Falls back to `label`
   *  if omitted. */
  pickerLabel?: string;
  /** Default true. Set false for columns with no backing sort field
   *  (checkbox, status dot, labels). */
  sortable?: boolean;
  /** Default true. Set false for columns without a filter box. */
  filterable?: boolean;
  /** Default false. True pins the column first in order and hides its
   *  toggle in the picker menu (used for the selection checkbox). */
  alwaysVisible?: boolean;
  /** Pixel floor for resize. Default 60. */
  minWidth?: number;
  /** Initial width in px. undefined = flex (auto). */
  defaultWidth?: number;
  /** Start collapsed. User can still reveal from the picker menu. */
  defaultHidden?: boolean;
  /** Render function for the cell body. */
  cell: (row: TRow) => ReactNode;
  /** Extra className on the <th>. */
  headerClassName?: string;
  /** Extra className on the <td>. */
  cellClassName?: string;
}

export interface ColumnConfig {
  width?: number;
  hidden?: boolean;
  order?: number;
}

export type ColumnConfigMap = Record<string, ColumnConfig>;
