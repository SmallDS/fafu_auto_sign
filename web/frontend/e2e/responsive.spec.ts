import { expect, test, type Page } from '@playwright/test';

const settings = {
  configured: true,
  version: 3,
  has_user_token: true,
  user_token_masked: '2_t********oken',
  jitter: 0.00005,
  heartbeat_interval: 900,
  log_level: 'INFO',
  amap_enabled: false,
  amap_js_key: null,
  has_amap_security_js_code: false,
  amap_security_js_code_masked: null,
  amap_source_coordinate_system: 'gcj02',
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

async function mockApi(page: Page): Promise<void> {
  await page.route(/^https?:\/\/[^/]+\/api(?:\/|$)/, async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown;
    if (path === '/api/settings') {
      body = settings;
    } else if (path === '/api/map/config') {
      body = {
        enabled: true,
        js_key: 'browser-visible-key',
        source_coordinate_system: 'gcj02',
        jitter: 0.00005,
        service_host: '/_AMapService',
      };
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
    } else if (path === '/api/sign-tasks') {
      const now = Date.now();
      body = {
        items: [{ id: '123', name: '课堂签到', begin_time: now - 60_000, end_time: now + 60_000 }],
        total: null,
        page: 1,
        page_size: 20,
        has_more: false,
      };
    } else if (path === '/api/sign-tasks/123') {
      body = { task_id: 123, position_id: 456, base_lng: 118.1, base_lat: 25.1, position_name: '宿舍楼' };
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
      ['/sign-tasks', '签到任务'],
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

test('移动端任务详情地图无溢出且定位不可用时优雅降级', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => {
    class MapMock {
      add(): void {}
      remove(): void {}
      destroy(): void {}
      resize(): void {}
      setFitView(): void {}
    }
    class OverlayMock {}
    class GeocoderMock {
      getAddress(
        _coordinate: [number, number],
        callback: (status: string, result: unknown) => void,
      ): void {
        callback('complete', {
          info: 'OK',
          regeocode: {
            formattedAddress: '福建省福州市仓山区',
            pois: [{ name: '福建农林大学' }],
          },
        });
      }
    }
    const amap = {
      Map: MapMock,
      Marker: OverlayMock,
      Polygon: OverlayMock,
      Circle: OverlayMock,
      Geocoder: GeocoderMock,
      convertFrom(
        coordinate: [number, number],
        _type: string,
        callback: (status: string, result: unknown) => void,
      ): void {
        callback('complete', { info: 'ok', locations: [coordinate] });
      },
    };
    (window as unknown as { AMap: typeof amap }).AMap = amap;
    Object.defineProperty(navigator, 'geolocation', {
      configurable: true,
      value: undefined,
    });
  });
  await mockApi(page);

  await page.goto('/sign-tasks');
  await page.getByRole('button', { name: /详情/ }).click();

  await expect(page.getByLabel('签到位置地图')).toBeVisible();
  await expect(page.getByText(/福建省福州市仓山区/)).toBeVisible();
  await expect(page.getByText(/请通过 HTTPS 或 localhost/)).toBeVisible();
  await expect(page.getByRole('link', { name: /导航/ })).toHaveCount(0);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
});