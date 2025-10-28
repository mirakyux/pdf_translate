"use client";
import * as React from "react";
import { cn } from "@/lib/utils";

export function Table({ className, ...props }: React.HTMLAttributes<HTMLTableElement>) {
  return <table className={cn("w-full text-sm", className)} {...props} />;
}

export function THead(props: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <thead {...props} />;
}

export function TBody(props: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody {...props} />;
}

export function TR(props: React.HTMLAttributes<HTMLTableRowElement>) {
  return <tr className="border-b border-neutral-200 dark:border-neutral-800" {...props} />;
}

export function TH(props: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return <th className="px-3 py-2 text-left font-medium" {...props} />;
}

export function TD(props: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className="px-3 py-2" {...props} />;
}