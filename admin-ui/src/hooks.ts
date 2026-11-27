import { useEffect, useState } from "react";
import { apiGet, TASK_TERMINAL, Task } from "./api";

export function useApi<T = any>(
  path: string | null,
  deps: unknown[] = [],
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!path) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 15000);
    setLoading(true);
    setError(null);
    apiGet<T>(path, controller.signal)
      .then((payload) => {
        if (!cancelled) setData(payload);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(
          err.name === "AbortError" ? "读取超时，请重试" : err.message,
        );
      })
      .finally(() => {
        window.clearTimeout(timer);
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, tick, ...deps]);

  return {
    data,
    error,
    loading,
    reload: () => setTick((value) => value + 1),
  };
}

export function useTaskPolling(taskId: string | undefined) {
  const [task, setTask] = useState<Task | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!taskId) return;
    let cancelled = false;
    let timer: number | undefined;
    let failures = 0;
    const startedAt = Date.now();

    const poll = async () => {
      try {
        const next = await apiGet<Task>(`/tasks/${encodeURIComponent(taskId)}`);
        if (cancelled) return;
        setTask(next);
        setError(null);
        failures = 0;
        if (!TASK_TERMINAL.has(next.status)) {
          const delay = Date.now() - startedAt > 30000 ? 5000 : 1500;
          timer = window.setTimeout(poll, delay);
        }
      } catch (err: any) {
        if (cancelled) return;
        failures += 1;
        if (failures >= 3) {
          setError("状态未知：连续轮询失败");
        } else {
          const delay = Date.now() - startedAt > 30000 ? 5000 : 1500;
          timer = window.setTimeout(poll, delay);
        }
      }
    };

    poll();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [taskId, tick]);

  return { task, error, reload: () => setTick((value) => value + 1) };
}
