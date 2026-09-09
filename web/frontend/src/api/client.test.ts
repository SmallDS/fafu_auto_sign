import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from './client';

describe('api client', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('发送设置请求并保留留空密钥语义', async () => {
    const response = {
      configured: true,
      version: 2,
      has_user_token: true,
      user_token_masked: '2_****',
      jitter: 0.00005,
      heartbeat_interval: 900,
      log_level: 'INFO',
      wechat_test_enabled: false,
      wechat_test_app_id: null,
      wechat_test_template_id: null,
      has_wechat_test_app_secret: false,
      wechat_test_app_secret_masked: null,
      has_wechat_test_openid: false,
      wechat_test_openid_masked: null,
      task_keywords: ['晚归'],
      image_mode: 'library',
      selected_image_id: null,
      worker_enabled: true,
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(response), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await api.updateSettings({
      jitter: 0.00005,
      task_keywords: ['晚归'],
      wechat_test_enabled: true,
      wechat_test_app_secret: 'secret',
      wechat_test_openid: 'openid',
    });

    expect(fetchMock).toHaveBeenCalledWith('/api/settings', expect.objectContaining({
      method: 'PUT',
      body: JSON.stringify({
        jitter: 0.00005,
        task_keywords: ['晚归'],
        wechat_test_enabled: true,
        wechat_test_app_secret: 'secret',
        wechat_test_openid: 'openid',
      }),
    }));
  });

  it('解析统一错误结构', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: { code: 'VALIDATION_ERROR', message: '配置校验失败', fields: { user_token: '格式错误' } },
    }), { status: 422, headers: { 'Content-Type': 'application/json' } })));

    await expect(api.getSettings()).rejects.toMatchObject({
      status: 422,
      code: 'VALIDATION_ERROR',
      message: '配置校验失败',
      fields: { user_token: '格式错误' },
    });
  });

  it('以 multipart 形式批量上传图片', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify([]), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);
    const files = [new File(['a'], 'a.jpg', { type: 'image/jpeg' }), new File(['b'], 'b.png', { type: 'image/png' })];

    await api.uploadImages(files, 'latest');

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const form = init.body as FormData;
    expect(form.getAll('files')).toHaveLength(2);
    expect(form.get('category')).toBe('latest');
    expect(new Headers(init.headers).get('Content-Type')).toBeNull();
  });
  it('提交微信公众号测试号的独立测试请求', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      state: 'idle', message: '测试号通知已提交',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
    await api.testWechatNotification();
    expect(fetchMock).toHaveBeenCalledWith('/api/notifications/wechat-test/test', expect.objectContaining({ method: 'POST' }));
  });
});