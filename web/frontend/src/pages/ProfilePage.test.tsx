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
    startFafuAuth: vi.fn(),
    completeFafuAuth: vi.fn(),
    reconnectFafuAuth: vi.fn(),
    cancelFafuAuth: vi.fn(),
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
  fafu_auth_mode: 'manual',
  fafu_auth_status: 'manual',
  fafu_username_masked: null,
  fafu_last_refresh_at: null,
  fafu_last_error: null,
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
    mockedApi.startFafuAuth.mockResolvedValue({ attempt_id: 'attempt-1', expires_at: '2026-09-24T13:00:00Z' });
    mockedApi.reconnectFafuAuth.mockResolvedValue({ attempt_id: 'attempt-2', expires_at: '2026-09-24T13:00:00Z' });
    mockedApi.completeFafuAuth.mockResolvedValue({ ...settings, fafu_auth_mode: 'auto', fafu_auth_status: 'connected', fafu_username_masked: '20****01' });
    mockedApi.cancelFafuAuth.mockResolvedValue();
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

    fireEvent.change(screen.getByLabelText('FAFU Token'), { target: { value: '2_new-token' } });
    fireEvent.click(screen.getByRole('button', { name: '保存 Token' }));
    await waitFor(() => expect(mockedApi.updateSettings).toHaveBeenCalledWith({ user_token: '2_new-token' }));

    fireEvent.click(screen.getAllByRole('switch')[0]);
    await waitFor(() => expect(mockedApi.pauseWorker).toHaveBeenCalledOnce());
  });

  it('账号登录使用已绑定设备 ID，短信完成后展示自动续期状态', async () => {
    render(<ConfigProvider><AntApp><ProfilePage /></AntApp></ConfigProvider>);
    await screen.findByText('FAFU 账号');

    fireEvent.click(screen.getByRole('radio', { name: '账号登录·自动续期' }));
    expect(screen.getByText(/已绑定设备的 Android ID 完全一致/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('学号'), { target: { value: '20260001' } });
    fireEvent.change(screen.getByLabelText('CAS 密码'), { target: { value: 'test-password' } });
    fireEvent.change(screen.getByLabelText('已绑定设备 ID（deviceId）'), { target: { value: 'bound-device-id' } });
    fireEvent.click(screen.getByRole('button', { name: '登录并发送短信验证码' }));

    await waitFor(() => expect(mockedApi.startFafuAuth).toHaveBeenCalledWith({
      username: '20260001', password: 'test-password', device_id: 'bound-device-id',
    }));
    fireEvent.change(await screen.findByLabelText('短信验证码'), { target: { value: '123456' } });
    fireEvent.click(screen.getByRole('button', { name: '完成连接' }));
    await waitFor(() => expect(mockedApi.completeFafuAuth).toHaveBeenCalledWith('attempt-1', '123456'));
    expect(await screen.findByText('自动续期已连接')).toBeInTheDocument();
    expect(screen.getByText('学号 20****01')).toBeInTheDocument();
  });

  it('续期失败时提示重新连接，并可取消本次短信会话', async () => {
    mockedApi.getSettings.mockResolvedValue({
      ...settings,
      fafu_auth_mode: 'auto',
      fafu_auth_status: 'reconnect_required',
      fafu_username_masked: '20****01',
      fafu_last_refresh_at: '2026-09-20T08:30:00Z',
      fafu_last_error: '刷新令牌已失效',
    });
    render(<ConfigProvider><AntApp><ProfilePage /></AntApp></ConfigProvider>);
    expect(await screen.findByText('需要重新连接')).toBeInTheDocument();
    expect(screen.getByText('刷新令牌已失效')).toBeInTheDocument();
    expect(screen.queryByDisplayValue('test-password')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '重新连接' }));
    await waitFor(() => expect(mockedApi.reconnectFafuAuth).toHaveBeenCalledOnce());
    fireEvent.click(await screen.findByRole('button', { name: '取消本次连接' }));
    await waitFor(() => expect(mockedApi.cancelFafuAuth).toHaveBeenCalledWith('attempt-2'));
    expect(screen.getByRole('button', { name: '重新连接' })).toBeInTheDocument();
  });

  it('微信通知开关只更新当前用户通知偏好', async () => {
    render(<ConfigProvider><AntApp><ProfilePage /></AntApp></ConfigProvider>);
    await screen.findByText('运行偏好');

    fireEvent.click(screen.getAllByRole('switch')[1]);
    await waitFor(() => expect(mockedApi.updateSettings).toHaveBeenCalledWith({ notification_enabled: false }));
  });
});
