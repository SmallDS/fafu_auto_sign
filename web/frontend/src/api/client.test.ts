import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, setCsrfToken } from './client';

describe('api client', () => {
  afterEach(() => {
    setCsrfToken(null);
    vi.unstubAllGlobals();
  });

  it('发送独立用户设置并附加 CSRF', async () => {
    const response = {
      configured: false,
      version: 2,
      has_user_token: true,
      user_token_masked: '2_****',
      jitter: 0.00005,
      heartbeat_interval: 900,
      task_keywords: [],
      image_mode: 'single',
      selected_image_id: null,
      worker_enabled: true,
      notification_enabled: true,
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(response), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);
    setCsrfToken('csrf-value');

    await api.updateSettings({ jitter: 0.00005, task_keywords: [], notification_enabled: true });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(fetchMock.mock.calls[0][0]).toBe('/api/settings');
    expect(init.method).toBe('PUT');
    expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf-value');
  });

  it('解析统一错误结构', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: { code: 'VALIDATION_ERROR', message: '配置校验失败', fields: { user_token: '格式错误' } },
    }), { status: 422, headers: { 'Content-Type': 'application/json' } })));
    await expect(api.getSettings()).rejects.toMatchObject({
      status: 422,
      code: 'VALIDATION_ERROR',
      message: '配置校验失败',
    });
  });

  it('以 multipart 形式批量上传图片', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify([]), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);
    await api.uploadImages([new File(['a'], 'a.jpg', { type: 'image/jpeg' })], 'latest');
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.body as FormData).getAll('files')).toHaveLength(1);
    expect(new Headers(init.headers).get('Content-Type')).toBeNull();
  });
});