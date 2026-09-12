import { Spin } from 'antd';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { ApiError, api, setCsrfToken } from '../api/client';
import type { AuthUser, BootstrapStatus } from '../types/api';

interface AuthState {
  loading: boolean;
  bootstrap: BootstrapStatus | null;
  user: AuthUser | null;
  refresh: () => Promise<void>;
  acceptUser: (user: AuthUser) => void;
  clearUser: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }): ReactNode {
  const [loading, setLoading] = useState(true);
  const [bootstrap, setBootstrap] = useState<BootstrapStatus | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const status = await api.getBootstrapStatus();
      setBootstrap(status);
      if (status.initialized) {
        try {
          const me = await api.getMe();
          setCsrfToken(me.csrf_token);
          setUser(me);
        } catch (error) {
          if (!(error instanceof ApiError) || ![401, 403].includes(error.status)) throw error;
          setCsrfToken(null);
          setUser(null);
        }
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const value = useMemo<AuthState>(() => ({
    loading,
    bootstrap,
    user,
    refresh,
    acceptUser: (next) => {
      setCsrfToken(next.csrf_token);
      setUser(next);
      setBootstrap((current) => current ? { ...current, initialized: true, setup_state: 'initialized' } : current);
    },
    clearUser: () => {
      setCsrfToken(null);
      setUser(null);
    },
  }), [bootstrap, loading, refresh, user]);

  if (loading) {
    return <div className="center-screen"><Spin size="large" /></div>;
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error('AuthProvider is missing');
  return value;
}