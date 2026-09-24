import { cleanup, render, waitFor } from '@testing-library/react';
import { App as AntApp, ConfigProvider } from 'antd';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type { Pairing } from '../types/api';
import { SetupPage } from './SetupPage';

vi.mock('../api/client', () => ({
  api: {
    createAdminPairing: vi.fn(),
    getAdminPairing: vi.fn(),
    exchangeAdminPairing: vi.fn(),
    configureBootstrap: vi.fn(),
  },
  getErrorMessage: (error: unknown) => error instanceof Error ? error.message : '错误',
}));

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({
    bootstrap: { requires_system_configuration: false },
    refresh: vi.fn(),
    acceptUser: vi.fn(),
  }),
}));

const mockedApi = vi.mocked(api);
const pairing: Pairing = {
  id: 'admin-pairing-1',
  kind: 'admin',
  status: 'pending',
  auth_url: 'https://public.example.com/auth/wechat/start?pairing_id=admin-pairing-1&claim=test',
  expires_at: new Date(Date.now() + 300_000).toISOString(),
  user_status: null,
};

afterEach(() => cleanup());

describe('SetupPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.createAdminPairing.mockResolvedValue(pairing);
    mockedApi.getAdminPairing.mockResolvedValue({ ...pairing, auth_url: null });
  });

  it('局域网入口与微信 OAuth 域名不同时仍展示管理员二维码并轮询', async () => {
    const { container } = render(
      <ConfigProvider><AntApp><SetupPage /></AntApp></ConfigProvider>,
    );

    await waitFor(() => expect(container.querySelector('svg[height="220"]')).toBeInTheDocument());
    await waitFor(() => expect(mockedApi.getAdminPairing).toHaveBeenCalled(), { timeout: 3000 });
    expect(container.textContent).not.toContain('请从公网 HTTPS 地址继续初始化');
  });
});
