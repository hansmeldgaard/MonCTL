import { cn } from "@/lib/utils.ts";
import type { LabelHTMLAttributes } from "react";

interface LabelProps extends LabelHTMLAttributes<HTMLLabelElement> {}

function Label({ className, ...props }: LabelProps) {
  return (
    <label
      className={cn("text-sm font-medium text-zinc-300", className)}
      {...props}
    />
  );
}

export { Label };
