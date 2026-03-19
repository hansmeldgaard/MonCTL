import { forwardRef, type InputHTMLAttributes } from "react";
import { X } from "lucide-react";
import { Input } from "@/components/ui/input.tsx";
import { cn } from "@/lib/utils.ts";

interface ClearableInputProps extends InputHTMLAttributes<HTMLInputElement> {
  onClear: () => void;
}

export const ClearableInput = forwardRef<HTMLInputElement, ClearableInputProps>(
  ({ value, onClear, className, ...props }, ref) => {
    const hasValue = value !== undefined && value !== "";
    return (
      <div className="relative">
        <Input
          ref={ref}
          value={value}
          className={cn(hasValue && "pr-7", className)}
          {...props}
        />
        {hasValue && (
          <button
            type="button"
            onClick={onClear}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 p-0.5 rounded text-zinc-500 hover:text-zinc-300 hover:bg-zinc-700/50 transition-colors"
            tabIndex={-1}
          >
            <X className="h-3 w-3" />
          </button>
        )}
      </div>
    );
  }
);
ClearableInput.displayName = "ClearableInput";
