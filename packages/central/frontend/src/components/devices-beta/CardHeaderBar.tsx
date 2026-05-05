import {
  Building2,
  FileText,
  FolderInput,
  ListChecks,
  Loader2,
  Monitor,
  Power,
  PowerOff,
  Trash2,
  X,
} from "lucide-react";

interface CardHeaderBarProps {
  selectedCount: number;
  canEdit: boolean;
  canDelete: boolean;
  busy?: boolean;
  autoAssigning?: boolean;
  onClear: () => void;
  onEnable: () => void;
  onDisable: () => void;
  onMoveGroup: () => void;
  onMoveTenant: () => void;
  onAutoAssignTemplate: () => void;
  onApplyTemplate: () => void;
  onDelete: () => void;
}

const actionBtn =
  "flex h-6 items-center gap-1.5 rounded px-2 text-[11px] font-medium border transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer";

/**
 * Fixed-height (44px) header slot inside the devices card. Two states share
 * the slot so selecting a row never reflows the table:
 *  - idle: monitor icon + "Devices" label
 *  - selecting: count + Clear + bulk action buttons
 * The slot height stays constant; only the content swaps.
 */
export function CardHeaderBar({
  selectedCount,
  canEdit,
  canDelete,
  busy,
  autoAssigning,
  onClear,
  onEnable,
  onDisable,
  onMoveGroup,
  onMoveTenant,
  onAutoAssignTemplate,
  onApplyTemplate,
  onDelete,
}: CardHeaderBarProps) {
  const selecting = selectedCount > 0;
  return (
    <div
      className="flex h-11 shrink-0 items-center gap-2 px-4 transition-colors duration-[120ms]"
      style={{
        borderBottom: "1px solid var(--border)",
        background: selecting
          ? "color-mix(in oklch, var(--brand) 8%, transparent)"
          : "transparent",
      }}
    >
      {!selecting && (
        <>
          <Monitor className="h-3.5 w-3.5" style={{ color: "var(--text-3)" }} />
          <span
            className="text-xs font-medium"
            style={{ color: "var(--text-3)" }}
          >
            Devices
          </span>
        </>
      )}
      {selecting && (
        <>
          <span className="text-xs" style={{ color: "var(--text-2)" }}>
            <span className="font-semibold" style={{ color: "var(--brand-2)" }}>
              {selectedCount}
            </span>{" "}
            selected
          </span>
          <button
            type="button"
            onClick={onClear}
            className="flex h-6 items-center gap-1 rounded px-1.5 text-[11px] cursor-pointer transition-colors hover:bg-white/5"
            style={{ color: "var(--text-3)" }}
          >
            <X className="h-3 w-3" /> Clear
          </button>
          <span
            aria-hidden
            className="mx-1 h-4 w-px"
            style={{ background: "var(--border-2)" }}
          />
          {canEdit && (
            <>
              <button
                type="button"
                onClick={onEnable}
                disabled={busy}
                className={actionBtn}
                style={{
                  background: "var(--surf-3)",
                  borderColor: "var(--border-2)",
                  color: "var(--text-2)",
                }}
              >
                <Power className="h-3 w-3" /> Enable
              </button>
              <button
                type="button"
                onClick={onDisable}
                disabled={busy}
                className={actionBtn}
                style={{
                  background: "var(--surf-3)",
                  borderColor: "var(--border-2)",
                  color: "var(--text-2)",
                }}
              >
                <PowerOff className="h-3 w-3" /> Disable
              </button>
              <button
                type="button"
                onClick={onMoveTenant}
                disabled={busy}
                className={actionBtn}
                style={{
                  background: "var(--surf-3)",
                  borderColor: "var(--border-2)",
                  color: "var(--text-2)",
                }}
              >
                <Building2 className="h-3 w-3" /> Move tenant
              </button>
              <button
                type="button"
                onClick={onMoveGroup}
                disabled={busy}
                className={actionBtn}
                style={{
                  background: "var(--surf-3)",
                  borderColor: "var(--border-2)",
                  color: "var(--text-2)",
                }}
              >
                <FolderInput className="h-3 w-3" /> Move group
              </button>
              <button
                type="button"
                onClick={onAutoAssignTemplate}
                disabled={autoAssigning}
                className={actionBtn}
                style={{
                  background: "var(--surf-3)",
                  borderColor: "var(--border-2)",
                  color: "var(--text-2)",
                }}
              >
                {autoAssigning ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <ListChecks className="h-3 w-3" />
                )}{" "}
                Auto-assign
              </button>
              <button
                type="button"
                onClick={onApplyTemplate}
                disabled={busy}
                className={actionBtn}
                style={{
                  background: "var(--surf-3)",
                  borderColor: "var(--border-2)",
                  color: "var(--text-2)",
                }}
              >
                <FileText className="h-3 w-3" /> Apply template
              </button>
            </>
          )}
          {canDelete && (
            <button
              type="button"
              onClick={onDelete}
              disabled={busy}
              className={actionBtn}
              style={{
                background: "var(--surf-3)",
                borderColor:
                  "color-mix(in oklch, var(--down) 35%, transparent)",
                color: "var(--down)",
              }}
            >
              <Trash2 className="h-3 w-3" /> Delete
            </button>
          )}
        </>
      )}
    </div>
  );
}
