import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App as AntApp, ConfigProvider } from 'antd';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type { Settings } from '../types/api';
import { ProfilePage } from './ProfilePage';

vi.mock('../api/client', () => ({
  api: {
    getSessions: vi.fn(),
    getSettings: vi.fn(),
    updateSettings: vi.fn(),
    pauseWorker: vi.fn(),
    resumeWorker: vi.fn(),
    revokeSession: vi.fn(),
    logout: vi.fn(),
  },
  getErrorMessage: (error: unknown) => error instanceof Error ? error.message : '错误',
}));

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({
    user: { nickname: '测试用户', role: 'user', avatar_url: null },
    clearUser: vi.fn(),
  }),
}));

const mockedApi = vi.mocked(api);
const settings: Settings = {
  configured: true,
  version: 1,
  has_user_token: true,
  user_token_masked: '2_ab****yz',
  jitter: 0.00005,
  heartbeat_interval: 900,
  task_keywords: [],
  image_mode: 'single',
  selected_image_id: 'image-1',
  worker_enabled: true,
  notification_enabled: true,
};

describe('ProfilePage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.getSettings.mockResolvedValue(settings);
    mockedApi.getSessions.mockResolvedValue([{
      id: 'session-1',
      device_type: 'mobile',
      user_agent: 'Mozilla/5.0 (iPhone) MicroMessenger/8.0.50 very-long-user-agent-detail',
      created_at: '2026-09-01T08:00:00Z',
      last_seen_at: '2026-09-12T08:30:00Z',
      expires_at: '2026-10-01T08:00:00Z',
      current: true,
    }]);
    mockedApi.updateSettings.mockResolvedValue(settings);
    mockedApi.pauseWorker.mockResolvedValue({ state: 'paused', message: '已暂停' });
    mockedApi.resumeWorker.mockResolvedValue({ state: 'idle', message: '已恢复' });
  });

  afterEach(() => cleanup());

  it('并行加载账号设置与简化后的设备信息', async () => {
    render(<ConfigProvider><AntApp><ProfilePage /></AntApp></ConfigProvider>);

    expect(screen.getByLabelText('页面加载中')).toBeInTheDocument();
    expect(await screen.findByText('FAFU 账号')).toBeInTheDocument();
    expect(mockedApi.getSettings).toHaveBeenCalledOnce();
    expect(mockedApi.getSessions).toHaveBeenCalledOnce();
    expect(screen.getByText('iOS · 微信')).toBeInTheDocument();
    expect(screen.queryByText(/very-long-user-agent-detail/)).not.toBeInTheDocument();
  });

  it('保存 Token，并通过专用接口暂停自动检查', async () => {
    render(<ConfigProvider><AntApp><ProfilePage /></AntApp></ConfigProvider>);
    await screen.findByText('FAFU 账号');

    fireEvent.change(screen.getByLabelText('更新 Token'), { target: { value: '2_new-token' } });
    fireEvent.click(screen.getByRole('button', { name: '保存 Token' }));
    await waitFor(() => expect(mockedApi.updateSettings).toHaveBeenCalledWith({ user_token: '2_new-token' }));

    fireEvent.click(screen.getAllByRole('switch')[0]);
    await waitFor(() => expect(mockedApi.pauseWorker).toHaveBeenCalledOnce());
  });

  it('微信通知开关只更新当前用户通知偏好', async () => {
    render(<ConfigProvider><AntApp><ProfilePage /></AntApp></ConfigProvider>);
    await screen.findByText('运行偏好');

    fireEvent.click(screen.getAllByRole('switch')[1]);
    await waitFor(() => expect(mockedApi.updateSettings).toHaveBeenCalledWith({ notification_enabled: false }));
  });
});
