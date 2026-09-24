import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App as AntApp, ConfigProvider } from 'antd';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type { Settings } from '../types/api';
import { SettingsPage } from './SettingsPage';

vi.mock('../api/client', () => ({
  api: {
    getSettings: vi.fn(),
    updateSettings: vi.fn(),
    listImages: vi.fn(),
  },
  getErrorMessage: (error: unknown) => error instanceof Error ? error.message : '错误',
}));

const mockedApi = vi.mocked(api);
afterEach(() => cleanup());

const settings: Settings = {
  configured: false,
  version: 1,
  has_user_token: false,
  user_token_masked: null,
  fafu_auth_mode: null,
  fafu_auth_status: 'unconfigured',
  fafu_username_masked: null,
  fafu_last_refresh_at: null,
  fafu_last_error: null,
  jitter: 0.00005,
  heartbeat_interval: 900,
  task_keywords: [],
  image_mode: 'single',
  selected_image_id: null,
  worker_enabled: true,
  notification_enabled: true,
};

describe('SettingsPage multi-user settings', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.getSettings.mockResolvedValue(settings);
    mockedApi.listImages.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100 });
    mockedApi.updateSettings.mockResolvedValue(settings);
  });

  it('首次加载时显示页面骨架', () => {
    mockedApi.getSettings.mockReturnValue(new Promise(() => undefined));
    render(<ConfigProvider><AntApp><SettingsPage /></AntApp></ConfigProvider>);
    expect(screen.getByLabelText('页面加载中')).toHaveAttribute('aria-busy', 'true');
  });

  it('只展示自动签到规则，不再展示账号与运行偏好', async () => {
    render(<ConfigProvider><AntApp><SettingsPage /></AntApp></ConfigProvider>);
    expect(await screen.findByRole('heading', { name: '规则签到' })).toBeInTheDocument();
    expect(screen.getByText('自动签到规则')).toBeInTheDocument();
    expect(screen.queryByText('FAFU 账号')).not.toBeInTheDocument();
    expect(screen.queryByText('自动检查')).not.toBeInTheDocument();
    expect(screen.queryByText('微信结果通知')).not.toBeInTheDocument();
  });

  it('允许留空任务关键词并保存空列表', async () => {
    render(<ConfigProvider><AntApp><SettingsPage /></AntApp></ConfigProvider>);
    await screen.findByText('自动签到规则');
    fireEvent.click(screen.getByRole('button', { name: '保存规则' }));
    await waitFor(() => {
      expect(mockedApi.updateSettings).toHaveBeenCalledWith(
        expect.objectContaining({ task_keywords: [] }),
      );
    });
  });
});
