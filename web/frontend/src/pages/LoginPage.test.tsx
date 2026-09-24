import { cleanup, render, waitFor } from '@testing-library/react';
import { App as AntApp, ConfigProvider } from 'antd';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type { Pairing } from '../types/api';
import { LoginPage } from './LoginPage';

vi.mock('../api/client', () => ({
  api: {
    createLoginPairing: vi.fn(),
    getLoginPairing: vi.fn(),
    exchangeLoginPairing: vi.fn(),
  },
  getErrorMessage: (error: unknown) => error instanceof Error ? error.message : '错误',
}));

const acceptUser = vi.fn();
vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ acceptUser }),
}));

const mockedApi = vi.mocked(api);
const initialPairing: Pairing = {
  id: 'pairing-1',
  kind: 'login',
  status: 'pending',
  auth_url: `${window.location.origin}/auth/wechat/start?pairing_id=pairing-1&claim=test`,
  expires_at: new Date(Date.now() + 60_000).toISOString(),
  user_status: null,
};

afterEach(() => cleanup());

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.createLoginPairing.mockResolvedValue(initialPairing);
    mockedApi.getLoginPairing.mockResolvedValue({ ...initialPairing, auth_url: null });
  });

  it('轮询响应省略登录地址时仍保留二维码', async () => {
    const { container } = render(
      <ConfigProvider><AntApp><LoginPage /></AntApp></ConfigProvider>,
    );

    await waitFor(() => expect(container.querySelector('svg[height="220"]')).toBeInTheDocument());
    await waitFor(() => expect(mockedApi.getLoginPairing).toHaveBeenCalled(), { timeout: 2500 });
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(container.querySelector('svg[height="220"]')).toBeInTheDocument();
  });

  it('当前页面与微信 OAuth 域名不同时仍显示二维码并轮询', async () => {
    mockedApi.createLoginPairing.mockResolvedValue({
      ...initialPairing,
      auth_url: 'https://public.example.com/auth/wechat/start?pairing_id=pairing-1&claim=test',
    });
    const { container } = render(
      <ConfigProvider><AntApp><LoginPage /></AntApp></ConfigProvider>,
    );

    await waitFor(() => expect(container.querySelector('svg[height="220"]')).toBeInTheDocument());
    await waitFor(() => expect(mockedApi.getLoginPairing).toHaveBeenCalled(), { timeout: 2500 });
    expect(container.textContent).not.toContain('Session Cookie 只会在系统配置的公网 HTTPS 地址生效');
  });
});
