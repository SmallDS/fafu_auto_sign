import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App as AntApp, ConfigProvider } from 'antd';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type { SystemSettings } from '../types/api';
import { AdminSystemPage } from './AdminSystemPage';

vi.mock('../api/client', () => ({
  api: {
    getAdminSystem: vi.fn(),
    updateAdminSystem: vi.fn(),
    syncMenu: vi.fn(),
  },
  getErrorMessage: (error: unknown) => error instanceof Error ? error.message : '错误',
}));

const mockedApi = vi.mocked(api);
const settings: SystemSettings = {
  setup_state: 'initialized',
  public_base_url: 'https://sign.example.com',
  menu_name: '签到管理',
  wechat_app_id: 'wx-app-id',
  wechat_template_id: 'template-id',
  wechat_enabled: true,
  has_wechat_app_secret: true,
  wechat_app_secret_masked: 'se***et',
  amap_enabled: false,
  amap_js_key: null,
  has_amap_security_js_code: false,
  amap_security_js_code_masked: null,
  log_level: 'INFO',
  menu_synced_at: null,
};

afterEach(() => cleanup());

describe('AdminSystemPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.getAdminSystem.mockResolvedValue(settings);
    mockedApi.updateAdminSystem.mockResolvedValue(settings);
    mockedApi.syncMenu.mockResolvedValue({ state: 'idle', message: 'ok' });
  });

  it('同步菜单前先保存当前表单配置', async () => {
    render(
      <ConfigProvider><AntApp><AdminSystemPage /></AntApp></ConfigProvider>,
    );

    const synchronize = await screen.findByRole('button', { name: '同步公众号菜单' });
    await waitFor(() => expect(synchronize).toBeEnabled());
    fireEvent.click(synchronize);
    fireEvent.click(await screen.findByRole('button', { name: '保存并同步' }));

    await waitFor(() => expect(mockedApi.syncMenu).toHaveBeenCalledOnce());
    expect(mockedApi.updateAdminSystem).toHaveBeenCalledWith(
      expect.objectContaining({
        public_base_url: 'https://sign.example.com',
        menu_name: '签到管理',
      }),
    );
    expect(mockedApi.updateAdminSystem.mock.invocationCallOrder[0])
      .toBeLessThan(mockedApi.syncMenu.mock.invocationCallOrder[0]);
  });
});