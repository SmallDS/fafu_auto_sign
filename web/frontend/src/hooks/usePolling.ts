import { useCallback, useEffect, useRef, useState } from 'react';

export interface PollingResult<T> {
  data: T | null;
  loading: boolean;
  error: unknown;
  refresh: () => Promise<void>;
}

export function usePolling<T>(loader: () => Promise<T>, intervalMs: number, enabled = true): PollingResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const mounted = useRef(true);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const refresh = useCallback(async () => {
    try {
      const next = await loaderRef.current();
      if (mounted.current) {
        setData(next);
        setError(null);
      }
    } catch (nextError) {
      if (mounted.current) setError(nextError);
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    if (!enabled) {
      setLoading(false);
      return () => {
        mounted.current = false;
      };
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), intervalMs);
    return () => {
      mounted.current = false;
      window.clearInterval(timer);
    };
  }, [enabled, intervalMs, refresh]);

  return { data, loading, error, refresh };
}