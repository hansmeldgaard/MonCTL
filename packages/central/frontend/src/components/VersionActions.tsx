import { Star, Code2, Pencil, Copy, Trash2 } from "lucide-react";

interface VersionActionsProps {
  isLatest: boolean;
  onSetLatest?: () => void;
  onView: () => void;
  onEdit: () => void;
  onClone?: () => void;
  onDelete: () => void;
  disabled?: boolean;
}

export function VersionActions({
  isLatest,
  onSetLatest,
  onView,
  onEdit,
  onClone,
  onDelete,
  disabled = false,
}: VersionActionsProps) {
  const btnClass =
    "rounded p-1.5 text-zinc-500 hover:text-zinc-200 hover:bg-zinc-700/50 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed";
  const deleteClass =
    "rounded p-1.5 text-zinc-600 hover:text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer";
  const iconSize = "h-3.5 w-3.5";
  const slotClass = "w-7 flex items-center justify-center";

  return (
    <div className="flex items-center justify-end gap-0">
      <div className={slotClass}>
        {!isLatest && onSetLatest && (
          <button
            onClick={onSetLatest}
            disabled={disabled}
            className={btnClass}
            title="Set as Latest"
          >
            <Star className={iconSize} />
          </button>
        )}
      </div>
      <div className={slotClass}>
        <button
          onClick={onView}
          disabled={disabled}
          className={btnClass}
          title="View"
        >
          <Code2 className={iconSize} />
        </button>
      </div>
      <div className={slotClass}>
        <button
          onClick={onEdit}
          disabled={disabled}
          className={btnClass}
          title="Edit"
        >
          <Pencil className={iconSize} />
        </button>
      </div>
      <div className={slotClass}>
        {onClone && (
          <button
            onClick={onClone}
            disabled={disabled}
            className={btnClass}
            title="Clone"
          >
            <Copy className={iconSize} />
          </button>
        )}
      </div>
      <div className={slotClass}>
        <button
          onClick={onDelete}
          className={deleteClass}
          title="Delete version"
        >
          <Trash2 className={iconSize} />
        </button>
      </div>
    </div>
  );
}
