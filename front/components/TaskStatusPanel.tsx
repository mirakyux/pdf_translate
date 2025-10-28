"use client";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { API_BASE_URL } from "@/lib/api";

type ConnectionState = "idle" | "connecting" | "connected" | "reconnecting" | "disconnected";

export interface TaskStatusPanelProps {
  taskId: string;
  onBack: () => void;
  onCompleted?: () => void; // 当任务完成后触发：关闭面板并由父组件打开任务列表
}

function stageColor(stage: string | undefined): string {
  const s = (stage || "").toLowerCase();
  if (s.includes("完成") || s.includes("complete")) return "#10b981"; // emerald-500
  if (s.includes("错误") || s.includes("error")) return "#ef4444"; // red-500
  if (s.includes("取消") || s.includes("cancel")) return "#ef4444"; // red-500
  if (s.includes("排队") || s.includes("queue")) return "#9ca3af"; // gray-400
  if (s.includes("处理") || s.includes("run") || s.includes("translate")) return "#f59e0b"; // amber-500
  return "#3b82f6"; // blue-500 (初始化/其他)
}

export default function TaskStatusPanel({ taskId, onBack, onCompleted }: TaskStatusPanelProps) {
  const [progress, setProgress] = useState<number>(0);
  const [stage, setStage] = useState<string>("初始化");
  const [connState, setConnState] = useState<ConnectionState>("idle");
  const [connError, setConnError] = useState<string | null>(null);
  const [flashStage, setFlashStage] = useState<boolean>(false);
  const reconnectAttemptsRef = useRef<number>(0);
  const closedByUserRef = useRef<boolean>(false);
  const wsRef = useRef<WebSocket | null>(null);
  const completedRef = useRef<boolean>(false);

  const radius = 64;
  const circumference = 2 * Math.PI * radius;
  const pct = Math.max(0, Math.min(100, Math.round(progress)));
  const dashOffset = useMemo(() => circumference * (1 - pct / 100), [circumference, pct]);
  const color = useMemo(() => stageColor(stage), [stage]);
  const stageDisplay = useMemo(() => {
    const t = (stage || "处理中").trim();
    if (t.length <= 8) return t;
    return t.slice(0, 5) + "...";
  }, [stage]);

  const wsUrl = useMemo(() => {
    // 将 http(s):// 替换为 ws(s)://
    const isSecure = API_BASE_URL.startsWith("https");
    const base = API_BASE_URL.replace(/^http(s?):\/\//i, isSecure ? "wss://" : "ws://");
    return `${base}/ws/tasks/${encodeURIComponent(taskId)}`;
  }, [taskId]);

  useEffect(() => {
    closedByUserRef.current = false;
    reconnectAttemptsRef.current = 0;
    let reconnectTimer: number | undefined;

    const triggerCompleted = () => {
      if (completedRef.current) return;
      completedRef.current = true;
      // 轻微延迟以保证 100% 进度与“完成”文案可见
      try { closedByUserRef.current = true; wsRef.current?.close(); } catch {}
      setTimeout(() => {
        try { onCompleted?.(); } catch {}
      }, 200);
    };

    const connect = () => {
      try {
        setConnState(reconnectAttemptsRef.current > 0 ? "reconnecting" : "connecting");
        setConnError(null);
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          setConnState("connected");
          setConnError(null);
          reconnectAttemptsRef.current = 0;
        };

        ws.onmessage = (ev) => {
          try {
            const data = JSON.parse(ev.data || "{}");
            if (data?.type === "progress_update") {
              const newStage = data.stage || stage;
              const newProgress = Math.round(Number(data.overall_progress || 0));

              // 阶段变更闪烁反馈（<=300ms）
              if (newStage !== stage) {
                setFlashStage(true);
                setTimeout(() => setFlashStage(false), 250);
              }
              setStage(newStage);
              setProgress(newProgress);
              // 若进度到达 100，也触发完成（防止极端场景缺少 finish 事件）
              if (newProgress >= 100 || /完成|complete/i.test(newStage || "")) {
                triggerCompleted();
              }
            } else if (data?.type === "finish") {
              setStage("完成");
              setProgress(100);
               triggerCompleted();
            } else if (data?.type === "error") {
              setStage("错误");
              setConnError(String(data?.error || "未知错误"));
            }
          } catch (e) {
            // 忽略解析错误
          }
        };

        ws.onerror = () => {
          // 连接异常：尝试重连
          ws.close();
        };

        ws.onclose = () => {
          if (closedByUserRef.current) return;
          if (reconnectAttemptsRef.current < 5) {
            setConnState("reconnecting");
            setConnError("网络中断，正在重连...");
            reconnectAttemptsRef.current += 1;
            const delay = Math.min(500 + reconnectAttemptsRef.current * 500, 3000);
            reconnectTimer = window.setTimeout(connect, delay) as unknown as number;
          } else {
            setConnState("disconnected");
            setConnError("连接已断开，请点击重试");
          }
        };
      } catch (e: any) {
        setConnError(e?.message || String(e));
        setConnState("disconnected");
      }
    };

    connect();

    return () => {
      closedByUserRef.current = true;
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      try { wsRef.current?.close(); } catch {}
      wsRef.current = null;
    };
  }, [wsUrl]);

  const handleBack = () => {
    closedByUserRef.current = true;
    try { wsRef.current?.close(); } catch {}
    onBack?.();
  };

  const handleRetry = () => {
    if (connState === "disconnected") {
      reconnectAttemptsRef.current = 0;
      setConnError(null);
      setConnState("idle");
      // 触发 useEffect 重新连接：更换 wsUrl 的 query 参数作为伪变化避免 debounce
      try { wsRef.current?.close(); } catch {}
      // 无需额外处理，父 effect 会在 wsUrl 未变时保持当前；这里直接手动调用连接逻辑不可达。让 onBack 再进入也可。
      // 简化：触发一次立即连接
      const connectNow = () => {
        try {
          const ws = new WebSocket(wsUrl);
          wsRef.current = ws;
          setConnState("connecting");
          ws.onopen = () => setConnState("connected");
          ws.onmessage = (ev) => {
            try {
              const data = JSON.parse(ev.data || "{}");
              if (data?.type === "progress_update") {
                const newStage = data.stage || stage;
                const newProgress = Math.round(Number(data.overall_progress || 0));
                if (newStage !== stage) {
                  setFlashStage(true);
                  setTimeout(() => setFlashStage(false), 250);
                }
                setStage(newStage);
                setProgress(newProgress);
              }
            } catch {}
          };
          ws.onerror = () => ws.close();
          ws.onclose = () => setConnState("disconnected");
        } catch {}
      };
      connectNow();
    }
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-white/80 backdrop-blur-sm dark:bg-black/80 transition-opacity duration-300 ease-in-out">
      {/* 返回按钮（左上角固定） */}
      <div className="absolute left-6 top-6">
        <Button variant="outline" onClick={handleBack} aria-label="返回" title="返回" className="transition-all duration-200 ease-in-out">
          返回
        </Button>
      </div>

      {/* 面板主体 */}
      <div className="w-[360px] max-w-[90vw] rounded-xl border border-neutral-200 bg-white p-6 shadow-lg dark:border-neutral-800 dark:bg-neutral-900 transition-transform duration-300 ease-in-out">
        {/* 连接提示 */}
        {connState !== "connected" && (
          <div className="mb-4 text-sm text-neutral-600 dark:text-neutral-400">
            {connState === "connecting" && <span>正在连接任务状态...</span>}
            {connState === "reconnecting" && <span>网络中断，正在重连...</span>}
            {connState === "disconnected" && (
              <div className="flex items-center justify-between gap-2">
                <span>连接已断开</span>
                <Button size="sm" onClick={handleRetry}>重试</Button>
              </div>
            )}
            {connError && <div className="mt-2 text-red-600">{connError}</div>}
          </div>
        )}

        <div className="mx-auto flex flex-col items-center justify-center">
          {/* 圆形进度条 */}
          <svg width={180} height={180} className="block">
            <g transform="translate(90,90)">
              {/* 轨道 */}
              <circle r={radius} fill="none" stroke="#e5e7eb" strokeWidth={10} />
              {/* 进度 */}
              <circle
                r={radius}
                fill="none"
                stroke={color}
                strokeWidth={10}
                strokeDasharray={circumference}
                strokeDashoffset={dashOffset}
                strokeLinecap="round"
                style={{ transition: "stroke-dashoffset 250ms ease-out, stroke 200ms ease-in-out" }}
                transform="rotate(-90)"
              />
            </g>
          </svg>
          {/* 中心文字 */}
          <div className="-mt-40 flex h-40 w-40 flex-col items-center justify-center text-center">
            <div className={`text-3xl font-semibold transition-colors duration-200`} style={{ color }}>
              {pct}%
            </div>
            <div className={`mt-1 text-sm ${flashStage ? "animate-pulse" : ""}`}>{stageDisplay}</div>
          </div>
        </div>
      </div>
    </div>
  );
}