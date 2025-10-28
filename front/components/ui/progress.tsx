"use client";
import * as React from "react";
import { cn } from "@/lib/utils";

export interface ProgressProps {
  value: number; // 0 - 100
  className?: string;
}

export function Progress({ value, className }: ProgressProps) {
  return (
    <div className={cn("h-2 w-full rounded bg-neutral-200 dark:bg-neutral-800", className)}>
      <div
        className="h-2 rounded bg-black dark:bg-white transition-all"
        style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
      />
    </div>
  );
}