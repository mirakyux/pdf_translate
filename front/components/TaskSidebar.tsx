"use client";
import React, { useEffect, useMemo, useRef, useState, useLayoutEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Table, THead, TBody, TR, TH, TD } from "@/components/ui/table";
import { Progress } from "@/components/ui/progress";
import { ChevronLeft, ChevronRight, Trash2, Download, RefreshCcw, User, UserCheck } from "lucide-react";
import type { TaskItem } from "@/lib/api";
import { debounce } from "@/lib/utils";

export interface TaskSidebarProps {
  open: boolean;
  onToggle: () => void;
  tasks: TaskItem[];
  loading: boolean;
  error: string | null;
  refreshTasks: (showLoading?: boolean, overrides?: { page?: number; page_size?: number; only_mine?: boolean }) => void;
  onDeleteTasks: (task_id?: string) => void;
  onDownloadMono: (task_id: string) => void;
  clientIp: string;
  ownerTokens: Record<string, string>;
  // Blur/darken overlay controls
  blurEnabled?: boolean; // enable/disable blur overlay
  overlayBlockInteractions?: boolean; // if true, overlay intercepts pointer events to block interactions
  overlayOpacity?: number; // 0.3 - 0.5
  overlayBrightness?: number; // 0.75 - 0.85 (i.e., 15%-25% darker)
  overlayTransitionMs?: number; // 300 - 500
  // Pagination & filtering
  total: number;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  onlyMine: boolean;
  onToggleOnlyMine: () => void;
  onPageSizeChange: (size: number) => void;
  onJumpToPage: (page: number) => void;
}

export default function TaskSidebar({
  open,
  onToggle,
  tasks,
  loading,
  error,
  refreshTasks,
  onDeleteTasks,
  onDownloadMono,
  clientIp,
  ownerTokens,
  blurEnabled = true,
  overlayBlockInteractions = true,
  overlayOpacity = 0.35,
  overlayBrightness = 0.85,
  overlayTransitionMs = 300,
  total,
  page,
  pageSize,
  onPageChange,
  onlyMine,
  onToggleOnlyMine,
  onPageSizeChange,
  onJumpToPage,
}: TaskSidebarProps) {
  const DEFAULT_WIDTH = 300;
  const MIN_WIDTH = 240;
  const MAX_WIDTH = 600;

  const clamp = (v: number, min: number, max: number) => Math.max(min, Math.min(max, v));

  // Storage helpers with cookie fallback
  const readStoredWidth = (): number | undefined => {
    try {
      const v = localStorage.getItem("taskSidebarWidth");
      if (v != null) return Number(v);
    } catch {}
    try {
      const match = document.cookie.match(/(?:^|; )taskSidebarWidth=(\d+)/);
      if (match && match[1]) return Number(match[1]);
    } catch {}
    return undefined;
  };

  const writeStoredWidth = (w: number) => {
    try { localStorage.setItem("taskSidebarWidth", String(w)); } catch {}
    try { document.cookie = `taskSidebarWidth=${w}; path=/; max-age=${60 * 60 * 24 * 365}; SameSite=Lax`; } catch {}
  };

  // Sidebar width with persistence
  const [width, setWidth] = useState<number>(DEFAULT_WIDTH);
  useEffect(() => {
    const saved = readStoredWidth();
    const value = saved == null || isNaN(saved) ? DEFAULT_WIDTH : saved;
    setWidth(clamp(value, MIN_WIDTH, MAX_WIDTH));
  }, []);

  const persistWidthDebounced = useMemo(
    () => debounce((w: number) => writeStoredWidth(w), 200),
    []
  );

  // Drag handle logic
  const draggingRef = useRef(false);
  const startXRef = useRef(0);
  const startWidthRef = useRef(DEFAULT_WIDTH);

  const onHandlePointerDown: React.PointerEventHandler<HTMLDivElement> = (e) => {
    e.preventDefault();
    draggingRef.current = true;
    startXRef.current = e.clientX;
    startWidthRef.current = width;
    try { (e.currentTarget as HTMLDivElement).setPointerCapture(e.pointerId); } catch {}
    // Visual feedback during dragging
    try {
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    } catch {}
    window.addEventListener("pointermove", onWindowPointerMove);
    window.addEventListener("pointerup", onWindowPointerUp);
  };

  const onWindowPointerMove = (e: PointerEvent) => {
    if (!draggingRef.current) return;
    const dx = startXRef.current - e.clientX; // move left => increase width
    const next = clamp(startWidthRef.current + dx, MIN_WIDTH, MAX_WIDTH);
    setWidth(next);
    persistWidthDebounced(next);
  };

  const onWindowPointerUp = () => {
    draggingRef.current = false;
    try {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    } catch {}
    window.removeEventListener("pointermove", onWindowPointerMove);
    window.removeEventListener("pointerup", onWindowPointerUp);
  };

  // Lock page scroll when sidebar is open: only sidebar should scroll
  useEffect(() => {
    try {
      if (open) {
        document.documentElement.style.overflow = "hidden";
        document.body.style.overflow = "hidden";
      } else {
        document.documentElement.style.overflow = "";
        document.body.style.overflow = "";
      }
    } catch {}
    return () => {
      try {
        document.documentElement.style.overflow = "";
        document.body.style.overflow = "";
      } catch {}
    };
  }, [open]);

  // Preserve horizontal scroll position across renders
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const lastScrollLeftRef = useRef<number>(0);

  const handleScroll: React.UIEventHandler<HTMLDivElement> = (e) => {
    lastScrollLeftRef.current = (e.currentTarget as HTMLDivElement).scrollLeft;
  };

  // Re-apply saved scroll position after tasks update (and layout changes)
  useLayoutEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const maxScrollLeft = Math.max(0, el.scrollWidth - el.clientWidth);
    const target = Math.max(0, Math.min(lastScrollLeftRef.current, maxScrollLeft));
    el.scrollLeft = target;
  }, [tasks]);

  return (
    <>
      {/* Glass blur + darken overlay covering all visible area except the sidebar */}
      <div
        aria-hidden="true"
        className={
          ((overlayBlockInteractions && open) ? "pointer-events-auto cursor-pointer " : "pointer-events-none ") +
          "fixed inset-y-0 left-0 z-30 transition-opacity ease-in-out"
        }
        style={{
          right: 0,
          opacity: blurEnabled && open ? 1 : 0,
          backgroundColor: `rgba(0,0,0,${Math.max(0.3, Math.min(overlayOpacity, 0.5))})`,
          transitionDuration: `${Math.max(300, Math.min(overlayTransitionMs, 500))}ms`,
          // Use inline backdropFilter to ensure consistent behavior across Tailwind configs
          backdropFilter: blurEnabled && open ? `blur(5px) brightness(${Math.max(0.75, Math.min(overlayBrightness, 0.85))})` : "none",
          WebkitBackdropFilter: blurEnabled && open ? `blur(5px) brightness(${Math.max(0.75, Math.min(overlayBrightness, 0.85))})` : "none",
        }}
        onClick={(e) => {
          // Clicking the blur area closes the sidebar
          e.preventDefault();
          e.stopPropagation();
          if (open) onToggle();
        }}
      />
      {/* Toggle button - visible at all times. When open, dock to the sidebar; when closed, stick to the right edge */}
      <button
        aria-label={open ? "收起任务列表" : "展开任务列表"}
        aria-expanded={open}
        onClick={onToggle}
        className={
          // Floating circular button for clear visual affordance
          "fixed z-50 top-1/2 -translate-y-1/2 transition-all duration-300 ease-in-out inline-flex h-10 w-10 items-center justify-center rounded-full border border-neutral-200 bg-white text-neutral-900 shadow-sm hover:bg-neutral-100 dark:border-neutral-800 dark:bg-neutral-900 dark:text-neutral-100 dark:hover:bg-neutral-800"
        }
        style={{ right: open ? width + 16 : 16 }}
      >
        {open ? <ChevronRight className="h-5 w-5" /> : <ChevronLeft className="h-5 w-5" />}
      </button>

      {/* Sidebar panel */}
      <aside
        className={
          "fixed inset-y-0 right-0 z-40 flex transform transition-transform duration-300 ease-in-out " +
          (open ? "translate-x-0" : "translate-x-full")
        }
        style={{ width }}
      >
        <div className="relative flex h-full w-full flex-col border-l border-neutral-200 bg-white shadow-lg dark:border-neutral-800 dark:bg-neutral-900">
          {/* Resizable handle at the left edge */}
          <div
            onPointerDown={onHandlePointerDown}
            className="absolute left-0 top-0 h-full w-2 cursor-col-resize hover:bg-neutral-200/40 dark:hover:bg-neutral-800/40"
            style={{ touchAction: "none" }}
            aria-label="拖动以调整宽度"
            title="拖动以调整宽度"
          />
          <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-200 dark:border-neutral-800">
            <h2 className="text-base font-medium">任务列表</h2>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                onClick={() => refreshTasks(true)}
                title="刷新任务列表"
                aria-label="刷新任务列表"
              >
                <RefreshCcw className="h-4 w-4" />
              </Button>
              <Button
                variant={onlyMine ? "default" : "outline"}
                onClick={onToggleOnlyMine}
                title="仅显示本人任务（基于 IP）"
                aria-pressed={onlyMine}
                aria-label="仅本人"
              >
                {onlyMine ? <UserCheck className="h-4 w-4" /> : <User className="h-4 w-4" />}
              </Button>
              <Button
                variant="destructive"
                onClick={() => onDeleteTasks()}
                title="删除全部本人任务"
                aria-label="删除全部本人任务"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          </div>
          <div className="flex-1 p-3 overflow-y-auto">
            {/* 状态展示，但不卸载表格容器，避免滚动位置丢失 */}
            <div className="mb-2 text-xs">
              {loading && <span className="text-neutral-500">更新中...</span>}
              {error && <span className="text-red-600">{error}</span>}
              {!error && (
                <span className="ml-2 text-neutral-600 dark:text-neutral-400">
                  共 {total} 条；第 {page} / {Math.max(1, Math.ceil((total || 0) / (pageSize || 1)))} 页
                </span>
              )}
            </div>
            {/* 过滤与分页控件 */}
            <div className="mb-2 flex items-center gap-2">
              <div className="flex items-center gap-2">
                <span className="text-xs text-neutral-600 dark:text-neutral-400">每页</span>
                <Select value={String(pageSize)} onChange={(e) => onPageSizeChange(Number(e.target.value) || 15)}>
                  {[5,10,15,20,50,100].map((n) => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </Select>
                <span className="ml-2 text-xs text-neutral-600 dark:text-neutral-400">跳转</span>
                <Input
                  className="h-8 w-16"
                  type="number"
                  min={1}
                  value={page}
                  onChange={(e) => {
                    const v = Number(e.target.value) || 1;
                    onJumpToPage(v);
                  }}
                  aria-label="跳转页码"
                />
              </div>
              <div className="ml-auto flex items-center gap-2">
                <Button
                  variant="outline"
                  onClick={() => onPageChange(Math.max(1, page - 1))}
                  disabled={page <= 1}
                  title="上一页"
                  aria-label="上一页"
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <Button
                  variant="outline"
                  onClick={() => onPageChange(page + 1)}
                  disabled={page * pageSize >= total}
                  title="下一页"
                  aria-label="下一页"
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
            <div ref={scrollContainerRef} onScroll={handleScroll} className="overflow-x-auto">
              <Table>
                <THead>
                  <TR>
                    <TH>操作</TH>
                    <TH>文件</TH>
                    <TH>配置</TH>
                    <TH>状态</TH>
                    <TH>队列位置</TH>
                    <TH>进度</TH>
                    <TH>阶段</TH>
                    <TH>开始</TH>
                    <TH>结束</TH>
                  </TR>
                </THead>
                <TBody>
                  {tasks.map((t) => {
                    // 显示原始文件名（无 .pdf 后缀），若缺失则回退到 filename 去除后缀
                    const rawName = (t.original_filename || t.filename || "").trim();
                    const displayName = rawName.replace(/\.pdf$/i, "");
                    // 合并语言与图片翻译配置
                    const imgEnabled = (typeof t.translate_images_experimental === "boolean" ? t.translate_images_experimental : (/图片翻译已启用/.test(String(t.message||""))));
                    const overlayEnabled = !!t.image_text_overlay;
                    const configDisplay = `${t.source_lang}→${t.target_lang}${imgEnabled ? ", Img" : ""}${imgEnabled && overlayEnabled ? " + Overlay" : ""}`;
                    // 统一时间格式 yyyy-MM-dd hh:mm:ss（本地时区）
                    const fmt = (s: string | null | undefined) => {
                      if (!s) return "-";
                      const d = new Date(s);
                      if (isNaN(d.getTime())) return s;
                      const pad = (n: number) => String(n).padStart(2, "0");
                      const yyyy = d.getFullYear();
                      const MM = pad(d.getMonth() + 1);
                      const dd = pad(d.getDate());
                      const hh = pad(d.getHours());
                      const mm = pad(d.getMinutes());
                      const ss = pad(d.getSeconds());
                      return `${yyyy}-${MM}-${dd} ${hh}:${mm}:${ss}`;
                    };
                    return (
                    <TR key={t.task_id}>
                      <TD className="w-24">
                        <div className="flex items-center gap-1">
                          {((t.owner_ip && t.owner_ip === clientIp) || !!ownerTokens[t.task_id]) && (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => onDeleteTasks(t.task_id)}
                              title="删除任务"
                              aria-label={`删除任务 ${t.task_id}`}
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          )}
                          {t.status === "completed" && (((t.owner_ip && t.owner_ip === clientIp) || !!ownerTokens[t.task_id])) && (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => onDownloadMono(t.task_id)}
                              title="下载PDF"
                              aria-label={`下载任务 ${t.task_id} 的 PDF`}
                            >
                              <Download className="h-4 w-4" />
                            </Button>
                          )}
                        </div>
                      </TD>
                      <TD className="text-xs">{displayName}</TD>
                      <TD className="text-xs">{configDisplay}</TD>
                      <TD>{t.status}</TD>
                      <TD className="text-xs">{typeof t.queue_position === "number" ? t.queue_position : "-"}</TD>
                      <TD className="min-w-32">
                        <Progress value={t.progress || 0} />
                      </TD>
                      <TD>{t.stage}</TD>
                      <TD className="font-mono text-xs">{fmt(t.start_time)}</TD>
                      <TD className="font-mono text-xs">{fmt(t.end_time)}</TD>
                    </TR>
                  )})}
                </TBody>
              </Table>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}