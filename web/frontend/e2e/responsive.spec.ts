import { expect, test, type Page } from '@playwright/test';

const settings = {
  configured: true,
  version: 3,
  has_user_token: true,
  user_token_masked: '2_t********oken',
  has_serverchan_key: false,
  serverchan_key_masked: null,
  jitter: 0.00005,
  heartbeat_interval: 900,
  log_level: 'INFO',
  notification_enabled: false,
  task_keywords: ['晚归'],
  image_mode: 'library',
  selected_image_id: null,
  worker_enabled: true,
};

async function mockApi(page: Page): Promise<void> {
  await page.route(/^https?:\/\/[^/]+\/api(?:\/|$)/, async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown;
    if (path === '/api/settings') {
      body = settings;
    } else if (path === '/api/status') {
      body = {
        configured: true,
        worker_state: 'idle',
        last_check_at: null,
        next_check_at: null,
        last_error: null,
        recent_run: null,
        stats_7d: { total: 0, success: 0, partial: 0, failed: 0, fatal: 0, no_task: 0 },
      };
    } else if (path === '/api/images') {
      body = { items: [], total: 0, page: 1, page_size: 24 };
    } else if (path === '/api/runs') {
      body = { items: [], total: 0, page: 1, page_size: 20 };
    } else if (path === '/api/logs') {
      body = { entries: [], next_cursor: 0, reset: false };
    } else if (path.startsWith('/api/worker/')) {
      body = { state: 'idle', message: '操作成功' };
    } else {
      body = { detail: { code: 'NOT_FOUND', message: '接口不存在' } };
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
  });
}

const cases = [
  { name: '360px', width: 360, height: 800 },
  { name: '390px', width: 390, height: 844 },
  { name: '768px', width: 768, height: 900 },
  { name: 'desktop', width: 1440, height: 900 },
];

for (const viewport of cases) {
  test(`${viewport.name} 下核心页面无横向溢出`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await mockApi(page);

    for (const [path, heading] of [
      ['/dashboard', '运行概览'],
      ['/settings', '系统设置'],
      ['/images', '图片管理'],
      ['/history', '运行历史'],
      ['/logs', '运行日志'],
    ] as const) {
      await page.goto(path);
      await expect(page.getByRole('heading', { name: heading })).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);
    }
  });
}
