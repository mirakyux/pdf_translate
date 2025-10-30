"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import TaskSidebar from "@/components/TaskSidebar";
import TaskStatusPanel from "@/components/TaskStatusPanel";
import { API_BASE_URL, deleteTasks, getTaskStatus, listTasks, startTranslation, uploadFile, getClientIP, createDownloadToken, type TaskItem, type TasksResponse } from "@/lib/api";

const LANG_OPTIONS = [
  { label: "English", value: "en" },
  { label: "中文", value: "zh" },
  { label: "日本語", value: "ja" },
  { label: "한국어", value: "ko" },
  { label: "Deutsch", value: "de" },
  { label: "Français", value: "fr" },
];

export default function Home() {
  // 右侧任务栏展开状态
  const [sidebarOpen, setSidebarOpen] = useState(false);
  // 毛玻璃雾化开关与交互阻断设置
  const [blurEnabled, setBlurEnabled] = useState(true);
  const [overlayBlockInteractions, setOverlayBlockInteractions] = useState(true);
  // 上传
  const [file, setFile] = useState<File | null>(null);
  const [fileId, setFileId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  // 状态面板：当前任务 ID（非空则显示面板）
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);

  // 翻译配置
  const [langIn, setLangIn] = useState("en");
  const [langOut, setLangOut] = useState("zh");
  const [qps, setQps] = useState(10);
  const [debug, setDebug] = useState(false);
  const [translateImages, setTranslateImages] = useState(true); // 实验性：翻译图片（默认勾选）
  const [model, setModel] = useState("gpt-4o-mini");

  // 任务
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [loadingTasks, setLoadingTasks] = useState(false);
  const [errorTasks, setErrorTasks] = useState<string | null>(null);
  const [totalTasks, setTotalTasks] = useState<number>(0);
  const [page, setPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(() => {
    // 允许的分页尺寸，避免出现非选项值导致下拉显示不一致
    const allowed = new Set([5, 10, 15, 20, 50, 100]);
    const normalize = (n: number | undefined | null): number | undefined => {
      if (typeof n !== "number" || Number.isNaN(n) || n <= 0) return undefined;
      return allowed.has(n) ? n : undefined;
    };
    // 优先读取用户偏好；否则读取环境变量；最后回退到 15
    try {
      const saved = localStorage.getItem("tasksPageSize");
      if (saved != null) {
        const n = Number(saved);
        const ok = normalize(n);
        if (ok) return ok;
      }
    } catch {}
    const envDefault = (process.env.NEXT_PUBLIC_TASKS_PAGE_SIZE_DEFAULT as string | undefined);
    if (envDefault) {
      const n = Number(envDefault);
      const ok = normalize(n);
      if (ok) return ok;
    }
    return 15;
  });
  // “仅本人”默认值做成配置项，并记忆用户偏好
  const [onlyMine, setOnlyMine] = useState<boolean>(() => {
    // 1) 用户偏好（localStorage）
    try {
      const saved = localStorage.getItem("onlyMine");
      if (saved === "true") return true;
      if (saved === "false") return false;
    } catch {}
    // 2) 环境变量
    const envDefault = (process.env.NEXT_PUBLIC_ONLY_MINE_DEFAULT as string | undefined);
    if (envDefault === "true") return true;
    if (envDefault === "false") return false;
    // 3) 回退：默认开启
    return true;
  });
  // 下载
  const [downloadMsg, setDownloadMsg] = useState<string | null>(null);
  // 客户端 IP
  const [clientIp, setClientIp] = useState<string>("");
  // 上传者令牌（持久化在 localStorage）
  const [ownerTokens, setOwnerTokens] = useState<Record<string, string>>({});

  const apiBase = useMemo(() => API_BASE_URL, []);

  // 避免并发刷新和不必要的重新渲染
  const refreshingRef = useRef(false);
  const refreshTasks = useCallback(async (showLoading?: boolean, overrides?: { page?: number; page_size?: number; only_mine?: boolean }) => {
    if (refreshingRef.current) return;
    refreshingRef.current = true;
    try {
      if (showLoading) setLoadingTasks(true);
      const targetPage = overrides?.page ?? page;
      const targetPageSize = overrides?.page_size ?? pageSize;
      const targetOnlyMine = overrides?.only_mine ?? onlyMine;
      const res: TasksResponse = await listTasks({ page: targetPage, page_size: targetPageSize, only_mine: targetOnlyMine });
      setTasks((prev) => {
        try {
          const a = JSON.stringify(prev);
          const b = JSON.stringify(res.tasks);
          if (a === b) return prev;
        } catch {}
        return res.tasks as TaskItem[];
      });
      setTotalTasks(res?.total ?? 0);
      setPage(res?.page ?? targetPage);
      setPageSize(res?.page_size ?? targetPageSize);
      setErrorTasks(null);
    } catch (e: any) {
      setErrorTasks(e?.message || String(e));
    } finally {
      if (showLoading) setLoadingTasks(false);
      refreshingRef.current = false;
    }
  }, [page, pageSize, onlyMine]);

  // 动态轮询策略：
  // - 当任务列表处于关闭/折叠状态时，停止自动调用 /api/tasks
  // - 当列表中不包含“当前用户未完成任务”时，降低轮询频率（默认 >=30s，可通过 NEXT_PUBLIC_TASKS_IDLE_POLL_MS 配置）
  // - 当包含“当前用户未完成任务”时，采用较高频率（默认 3s）
  const IDLE_POLL_MS = useMemo(() => {
    const env = Number(process.env.NEXT_PUBLIC_TASKS_IDLE_POLL_MS || 30000);
    // 保底 30s，避免过于频繁
    return Math.max(30000, Number.isFinite(env) ? env : 30000);
  }, []);

  const ACTIVE_POLL_MS = 3000; // 有本人未完成任务时的刷新频率

  // 首次加载：仅在侧边栏展开时获取一次（避免在关闭状态下产生不必要请求）
  useEffect(() => {
    if (sidebarOpen) {
      refreshTasks(false);
    }
  }, [sidebarOpen, refreshTasks]);

  // 条件轮询（根据侧边栏展开状态与是否存在本人未完成任务动态调整）
  useEffect(() => {
    // 侧边栏关闭则不轮询
    if (!sidebarOpen) return;

    // 判定是否包含“当前用户未完成任务”
    const hasOwnUnfinished = tasks.some((t) => {
      const isMineByIp = !!(t.owner_ip && t.owner_ip === clientIp);
      const isMineByToken = !!ownerTokens[t.task_id];
      const isMine = isMineByIp || isMineByToken;
      const isUnfinished = (t.status === "queued" || t.status === "running");
      return isMine && isUnfinished;
    });

    const intervalMs = hasOwnUnfinished ? ACTIVE_POLL_MS : IDLE_POLL_MS;
    const timer = setInterval(() => {
      // 后台刷新，不显示加载遮挡、不打断滚动
      try { refreshTasks(false); } catch {}
    }, intervalMs);
    return () => clearInterval(timer);
  }, [sidebarOpen, tasks, clientIp, ownerTokens, refreshTasks, IDLE_POLL_MS]);

  // 获取客户端 IP，用于前端隐藏非本人上传的下载按钮
  useEffect(() => {
    (async () => {
      try {
        const { ip } = await getClientIP();
        setClientIp(ip || "");
      } catch (e) {
        // 获取失败不影响主流程，仅不做前端隐藏，后端仍有权限校验
      }
    })();
  }, []);

  // 加载本地已保存的上传者令牌
  useEffect(() => {
    try {
      const raw = localStorage.getItem("ownerTokens");
      if (raw) {
        const obj = JSON.parse(raw);
        if (obj && typeof obj === "object") {
          setOwnerTokens(obj);
        }
      }
    } catch {}
  }, []);

  // 轮询运行中任务状态（仅在右侧任务列表展开时进行）
  useEffect(() => {
    // 侧边栏关闭时不进行状态轮询，避免不必要的 /status 请求
    if (!sidebarOpen) return;

    // 仅轮询“本人”的运行中任务，降低无关请求：基于 IP 或 ownerToken
    const runningIds = tasks
      .filter((t) => {
        const isMineByIp = !!(t.owner_ip && t.owner_ip === clientIp);
        const isMineByToken = !!ownerTokens[t.task_id];
        const isMine = isMineByIp || isMineByToken;
        return isMine && t.status === "running";
      })
      .map((t) => t.task_id);
    if (runningIds.length === 0) return;

    const timer = setInterval(async () => {
      try {
        const updates = await Promise.all(runningIds.map((id) => getTaskStatus(id)));
        setTasks((prev) =>
          prev.map((t) => {
            const u = updates.find((x) => x.task_id === t.task_id);
            return u
              ? {
                  ...t,
                  status: u.status,
                  progress: u.progress,
                  stage: u.stage,
                  // 后端 status 接口的 message/error 字段是可选（可能为 undefined），
                  // 前端 TaskItem 约定为 string | null，因此需要兜底为 null。
                  message: (u.message ?? t.message ?? null),
                  error: (u.error ?? t.error ?? null),
                  start_time: u.start_time ?? t.start_time,
                  end_time: u.end_time ?? t.end_time,
                }
              : t;
          })
        );

        // 兜底：若发现某些任务进度已到 100 或状态从 running 结束，则立即刷新任务列表，避免因缺失 finish 事件导致前端停留在 running
        const anyFinishedOrFull = updates.some((u) => (u.status === "completed") || (u.progress ?? 0) >= 100);
        const newRunningCount = updates.filter((u) => u.status === "running").length;
        if (anyFinishedOrFull || (runningIds.length > 0 && newRunningCount === 0)) {
          // 立即触发一次任务列表刷新以获取持久化状态（后台刷新，不显示加载遮挡）
          try { await refreshTasks(false); } catch {}
        }
      } catch (e) {
        // 忽略状态轮询错误
      }
    }, 5000);

    return () => clearInterval(timer);
  }, [tasks, sidebarOpen, clientIp, ownerTokens]);

  const onUploadAndStart = async () => {
    if (!file) return;
    try {
      setUploading(true);
      setUploadError(null);
      // 1) 上传文件
      const res = await uploadFile(file);
      setFileId(res.file_id);
      // 2) 立刻按当前配置启动翻译
      const startRes = await startTranslation({ file_id: res.file_id, lang_in: langIn, lang_out: langOut, qps, debug, model, translate_images_experimental: translateImages });
      // 保存 owner_token（与 task_id 关联），用于下载校验
      if (startRes?.task_id && startRes?.owner_token) {
        setOwnerTokens((prev) => {
          const next = { ...prev, [startRes.task_id]: startRes.owner_token! };
          try { localStorage.setItem("ownerTokens", JSON.stringify(next)); } catch {}
          return next;
        });
      }
      // 3) 刷新任务列表
      await refreshTasks(false);
      // 4) 切换到任务执行状态面板
      if (startRes?.task_id) {
        setActiveTaskId(startRes.task_id);
      }
      // 5) 提交完成后清空文件选择区域并恢复初始显示
      setSubmitted(true);
      setFile(null);
      try { if (fileInputRef.current) fileInputRef.current.value = ""; } catch {}
      setIsDragging(false);
      setTimeout(() => setSubmitted(false), 1200);
    } catch (e: any) {
      setUploadError(e?.message || String(e));
      alert(e?.message || String(e));
    } finally {
      setUploading(false);
    }
  };

  // 已合并为“上传即启动”，保留占位以备未来扩展
  // const onStartTranslate = async () => {};

  const doDirectDownloadMono = async (task_id: string) => {
    setDownloadMsg(null);
    try {
      const ownerToken = ownerTokens?.[task_id];
      // 优先尝试创建下载令牌（严格模式下需要上传者令牌；默认模式按 IP 或令牌校验）
      try {
        const { token, expires_at } = await createDownloadToken(task_id, "mono", ownerToken);
        const url = `${API_BASE_URL}/tasks/${encodeURIComponent(task_id)}/download?file_type=mono&token=${encodeURIComponent(token)}`;
        window.open(url, "_blank");
      } catch (e) {
        // 令牌创建失败则回退到旧逻辑：带 owner_token 或不带参数（后端仍会按配置校验）
        const fallbackUrl = ownerToken
          ? `${API_BASE_URL}/tasks/${encodeURIComponent(task_id)}/download?file_type=mono&owner_token=${encodeURIComponent(ownerToken)}`
          : `${API_BASE_URL}/tasks/${encodeURIComponent(task_id)}/download?file_type=mono`;
        window.open(fallbackUrl, "_blank");
      }
    } catch (e: any) {
      setDownloadMsg(e?.message || String(e));
    }
  };

  const onDeleteTasks = async (task_id?: string) => {
    try {
      // 仅删除“本人任务”：拥有令牌或 IP 匹配
      const canOperate = (tid: string) => {
        const t = tasks.find((x) => x.task_id === tid);
        if (!t) return false;
        if (ownerTokens?.[tid]) return true;
        return !!(t.owner_ip && t.owner_ip === clientIp);
      };
      const targets = task_id ? [task_id] : tasks.map((t) => t.task_id).filter((id) => canOperate(id));
      for (const tid of targets) {
        const token = ownerTokens?.[tid];
        await deleteTasks([tid], token);
      }
      await refreshTasks(false);
    } catch (e: any) {
      alert(e?.message || String(e));
    }
  };

  return (
    <div className="min-h-screen w-full bg-neutral-50 text-neutral-900 dark:bg-black dark:text-neutral-100">
      {/* 主内容区域 */}
      <main className="mx-auto max-w-5xl px-6 py-8">
        <header className="mb-8">
          <h1 className="text-2xl font-semibold">PDF 翻译控制台</h1>
          <p className="text-sm text-neutral-600 dark:text-neutral-400">后端接口：{apiBase}</p>
        </header>

        {/* 上传并配置翻译（独立主内容区） */}
        <section className="relative rounded-lg border border-neutral-200 bg-white p-6 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <Label htmlFor="file">选择 PDF 文件</Label>
              {/* 拖拽 + 点击选择区域 */}
              <input
                ref={fileInputRef}
                id="file"
                type="file"
                accept="application/pdf"
                className="sr-only"
                onChange={(e) => {
                  const f = e.target.files?.[0] || null;
                  setFile(f);
                }}
              />
              <div
                className={
                  "mt-2 flex cursor-pointer flex-col items-center justify-center rounded-md border-2 border-dashed p-6 text-center text-sm transition " +
                  (isDragging
                    ? "border-blue-500 bg-blue-50/60 dark:bg-blue-950/40"
                    : "border-neutral-300 hover:bg-neutral-50 dark:border-neutral-700 dark:hover:bg-neutral-800/50")
                }
                onClick={() => fileInputRef.current?.click()}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") fileInputRef.current?.click();
                }}
                role="button"
                tabIndex={0}
                onDragEnter={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setIsDragging(true);
                }}
                onDragOver={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setIsDragging(true);
                }}
                onDragLeave={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setIsDragging(false);
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setIsDragging(false);
                  const f = e.dataTransfer?.files?.[0] || null;
                  if (f) setFile(f);
                }}
              >
                {!file && (
                  <>
                    <p className="text-neutral-600 dark:text-neutral-400">拖拽 PDF 到此处，或点击选择文件</p>
                    <p className="mt-1 text-xs text-neutral-500">仅支持 application/pdf</p>
                  </>
                )}
                {file && (
                  <div className="w-full">
                    <p className="text-neutral-700 dark:text-neutral-200">已选择：{file.name}</p>
                    <p className="mt-1 text-xs text-neutral-500">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                  </div>
                )}
              </div>
            </div>
            <div>
              <Label htmlFor="langIn">源语言</Label>
              <Select id="langIn" value={langIn} onChange={(e) => setLangIn(e.target.value)}>
                {LANG_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label htmlFor="langOut">目标语言</Label>
              <Select id="langOut" value={langOut} onChange={(e) => setLangOut(e.target.value)}>
                {LANG_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label htmlFor="qps">QPS</Label>
              <Input id="qps" type="number" min={1} value={qps} onChange={(e) => setQps(Number(e.target.value) || 1)} />
            </div>
            <div>
              <Label htmlFor="model">模型</Label>
              <Input id="model" value={model} onChange={(e) => setModel(e.target.value)} />
            </div>
          </div>
          <div className="mt-4 flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <input id="debug" type="checkbox" checked={debug} onChange={(e) => setDebug(e.target.checked)} />
              <Label htmlFor="debug">调试模式</Label>
            </div>
            <div className="flex items-center gap-2">
              <input id="translateImages" type="checkbox" checked={translateImages} onChange={(e) => setTranslateImages(e.target.checked)} />
              <Label htmlFor="translateImages">翻译图片</Label>
              <span className="ml-1 inline-flex items-center rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">实验性</span>
            </div>
          </div>
          {/* 底部提交按钮（保持在面板底部） */}
          <div className="mt-6 flex justify-end">
            <Button disabled={!file || uploading} onClick={onUploadAndStart}>
              {uploading ? "提交中..." : submitted ? "提交完成" : "提交"}
            </Button>
          </div>
          {uploadError && <p className="mt-2 text-sm text-red-600">{uploadError}</p>}

          {/* 任务执行状态面板：启动后以覆盖方式显示，Back 返回上传面板（保留状态） */}
          {activeTaskId && (
            <TaskStatusPanel
              taskId={activeTaskId}
              onBack={() => setActiveTaskId(null)}
              onCompleted={() => {
                // 任务完成：关闭状态面板并打开右侧任务列表，同时刷新一次任务列表
                setActiveTaskId(null);
                setSidebarOpen(true);
                try { refreshTasks(false); } catch {}
              }}
            />
          )}
        </section>
      </main>

      {/* 右侧收缩侧边栏：任务列表（覆盖式）*/}
      <TaskSidebar
        open={sidebarOpen}
        onToggle={() => setSidebarOpen((v) => !v)}
        tasks={tasks as any}
        loading={loadingTasks}
        error={errorTasks}
        refreshTasks={refreshTasks}
        onDeleteTasks={onDeleteTasks}
        onDownloadMono={doDirectDownloadMono}
        clientIp={clientIp}
        ownerTokens={ownerTokens}
        blurEnabled={blurEnabled}
        overlayBlockInteractions={overlayBlockInteractions}
        total={totalTasks}
        page={page}
        pageSize={pageSize}
        onPageChange={(p) => { setPage(p); try { refreshTasks(true, { page: p }); } catch {} }}
        onlyMine={onlyMine}
        onToggleOnlyMine={() => {
          setOnlyMine((v) => {
            const next = !v;
            try { localStorage.setItem("onlyMine", String(next)); } catch {}
            setPage(1);
            try { refreshTasks(true, { only_mine: next, page: 1 }); } catch {}
            return next;
          });
        }}
        onPageSizeChange={(size) => {
          const s = Number(size) || 15;
          setPageSize(s);
          try { localStorage.setItem("tasksPageSize", String(s)); } catch {}
          setPage(1);
          try { refreshTasks(true, { page_size: s, page: 1 }); } catch {}
        }}
        onJumpToPage={(p) => {
          const requested = Math.max(1, Number(p) || 1);
          const maxPage = Math.max(1, Math.ceil((totalTasks || 0) / (pageSize || 1)));
          const np = Math.min(requested, maxPage);
          setPage(np);
          try { refreshTasks(true, { page: np }); } catch {}
        }}
      />
    </div>
  );
}
