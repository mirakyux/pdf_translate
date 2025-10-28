"use client";
import * as React from "react";
import { cn } from "@/lib/utils";

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {}

const Select = React.forwardRef<HTMLSelectElement, SelectProps>(({ className, ...props }, ref) => {
  return (
    <select
      ref={ref}
      className={cn(
        "flex h-10 w-full rounded-md border border-neutral-200 bg-transparent px-3 py-2 text-sm outline-none focus:border-neutral-400 dark:border-neutral-800",
        className
      )}
      {...props}
    />
  );
});
Select.displayName = "Select";

export { Select };