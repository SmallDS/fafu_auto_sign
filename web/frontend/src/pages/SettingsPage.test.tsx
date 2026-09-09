import { render, screen } from '@testing-library/react';
import { App as AntApp, ConfigProvider } from 'antd';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import { SettingsPage } from './SettingsPage';

vi.mock('../api/client', () => ({
  api: { getSettings: vi.fn(), updateSettings: vi.fn(), testWechatNotification: vi.fn() },
  getErrorMessage: (error: unknown) => error instanceof Error ? error.message : '错误',
}));

const mockedApi = vi.mocked(api);

describe('SettingsPage WeChat test account', () => {
  beforeEach(() => {
    mockedApi.getSettings.mockResolvedValue({
      configured: false, version: 1, has_user_token: false, user_token_masked: null,
      jitter: 0.00005,
      heartbeat_interval: 900, log_level: 'INFO',
      wechat_test_enabled: false, wechat_test_app_id: null, wechat_test_template_id: null,
      has_wechat_test_app_secret: false, wechat_test_app_secret_masked: null,
      has_wechat_test_openid: false, wechat_test_openid_masked: null,
      task_keywords: ['晚归'], image_mode: 'single', selected_image_id: null, worker_enabled: true,
    });
  });

  it('展示固定模板及独立测试号配置区', async () => {
    render(<ConfigProvider><AntApp><SettingsPage /></AntApp></ConfigProvider>);
    expect(await screen.findByText('微信公众号接口测试号')).toBeInTheDocument();
    expect(screen.getByText(/任务：\{\{keyword1\.DATA\}\}/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /复制模板内容/ })).toBeInTheDocument();
  });
});