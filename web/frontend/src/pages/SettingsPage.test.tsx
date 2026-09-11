import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App as AntApp, ConfigProvider } from 'antd';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type { Settings } from '../types/api';
import { isSupportedUserTokenInput, SettingsPage } from './SettingsPage';

vi.mock('../api/client', () => ({
  api: { getSettings: vi.fn(), updateSettings: vi.fn(), testWechatNotification: vi.fn() },
  getErrorMessage: (error: unknown) => error instanceof Error ? error.message : '错误',
}));

const mockedApi = vi.mocked(api);

afterEach(() => cleanup());

const emptyKeywordSettings: Settings = {
  configured: false,
  version: 1,
  has_user_token: false,
  user_token_masked: null,
  jitter: 0.00005,
  heartbeat_interval: 900,
  log_level: 'INFO',
  amap_enabled: false,
  amap_js_key: null,
  has_amap_security_js_code: false,
  amap_security_js_code_masked: null,
  wechat_test_enabled: false,
  wechat_test_app_id: null,
  wechat_test_template_id: null,
  has_wechat_test_app_secret: false,
  wechat_test_app_secret_masked: null,
  has_wechat_test_openid: false,
  wechat_test_openid_masked: null,
  task_keywords: [],
  image_mode: 'single',
  selected_image_id: null,
  worker_enabled: true,
};

describe('SettingsPage WeChat test account', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.getSettings.mockResolvedValue(emptyKeywordSettings);
    mockedApi.updateSettings.mockResolvedValue(emptyKeywordSettings);
  });

  it('展示固定模板及独立测试号配置区', async () => {
    render(<ConfigProvider><AntApp><SettingsPage /></AntApp></ConfigProvider>);
    expect(await screen.findByText('微信公众号接口测试号')).toBeInTheDocument();
    expect(screen.getByText(/任务：\{\{keyword1\.DATA\}\}/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /复制模板内容/ })).toBeInTheDocument();
  });

  it('展示高德配置并保留已保存的安全密钥', async () => {
    mockedApi.getSettings.mockResolvedValue({
      ...emptyKeywordSettings,
      amap_enabled: true,
      amap_js_key: 'browser-visible-key',
      has_amap_security_js_code: true,
      amap_security_js_code_masked: 'priv********code',
    });
    mockedApi.updateSettings.mockResolvedValue({
      ...emptyKeywordSettings,
      amap_enabled: true,
      amap_js_key: 'browser-visible-key',
      has_amap_security_js_code: true,
      amap_security_js_code_masked: 'priv********code',
    });

    render(<ConfigProvider><AntApp><SettingsPage /></AntApp></ConfigProvider>);
    expect(await screen.findByText('地图仅用于展示和距离计算')).toBeInTheDocument();
    expect(await screen.findByDisplayValue('browser-visible-key')).toBeInTheDocument();
    expect(screen.getByText(/Security JS Code 仅由后端代理使用/)).toBeInTheDocument();
    expect(screen.queryByText('FAFU 源坐标系')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /保存设置/ }));
    await waitFor(() => {
      expect(mockedApi.updateSettings).toHaveBeenCalledWith(expect.objectContaining({
        amap_enabled: true,
        amap_js_key: 'browser-visible-key',
      }));
    });
    const payload = mockedApi.updateSettings.mock.calls[0][0];
    expect(payload).not.toHaveProperty('amap_security_js_code');
  });

  it('允许原始 Token 与完整 Base64 Authorization', () => {
    const authorization = window.btoa(
      '1773238142:nonceForWebTest1:' + 'a'.repeat(32) + ':2_from_authorization',
    );
    expect(isSupportedUserTokenInput('2_raw_token')).toBe(true);
    expect(isSupportedUserTokenInput(authorization)).toBe(true);
    expect(isSupportedUserTokenInput(window.btoa('bad:authorization'))).toBe(false);
    expect(isSupportedUserTokenInput('not-base64')).toBe(false);
  });

  it('允许留空任务关键词并保存空列表', async () => {
    render(<ConfigProvider><AntApp><SettingsPage /></AntApp></ConfigProvider>);
    expect(await screen.findByText(/空列表表示自动签到不匹配任何任务/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /保存设置/ }));

    await waitFor(() => {
      expect(mockedApi.updateSettings).toHaveBeenCalledWith(
        expect.objectContaining({ task_keywords: [] }),
      );
    });
    expect(screen.queryByText('至少添加一个关键词')).not.toBeInTheDocument();
  });
});
