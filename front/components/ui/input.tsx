"use client";
import * as React from "react";
import { cn } from "@/lib/utils";

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {}

const Input = React.forwardRef<HTMLInputElement, InputProps>(({ className, ...props }, ref) => {
  return (
    <input
      ref={ref}
      className={cn(
        "flex h-10 w-full rounded-md border border-neutral-200 bg-transparent px-3 py-2 text-sm outline-none placeholder:text-neutral-500 focus:border-neutral-400 dark:border-neutral-800 dark:placeholder:text-neutral-400",
        className
      )}
      {...props}
    />
  );
});
Input.displayName = "Input";

export { Input };