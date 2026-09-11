import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ConfigProvider } from 'antd';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { MapConfig, SignTaskDetails } from '../types/api';
import {
  AmapTaskMap,
  convertGpsCoordinate,
  formatDistance,
  haversineDistance,
  isGeolocationContextAllowed,
  resetAmapLoaderForTests,
  type AmapNamespace,
  type Coordinate,
} from './AmapTaskMap';

const details: SignTaskDetails = {
  task_id: 123,
  position_id: 456,
  base_lng: 118.1,
  base_lat: 25.1,
  position_name: '宿舍楼',
};

const enabledConfig: MapConfig = {
  enabled: true,
  js_key: 'browser-key',
  source_coordinate_system: 'gcj02',
  jitter: 0.00005,
  service_host: '/_AMapService',
};

interface OverlayOptions {
  [key: string]: unknown;
}

function installAmapMock() {
  const added: unknown[] = [];
  const polygonOptions: OverlayOptions[] = [];
  const mapDestroy = vi.fn();
  const mapRemove = vi.fn();

  class MapMock {
    constructor(_container: HTMLElement, _options: Record<string, unknown>) {}
    add(overlays: unknown): void { added.push(overlays); }
    remove(overlays: unknown): void { mapRemove(overlays); }
    destroy(): void { mapDestroy(); }
    resize(): void {}
    setFitView(): void {}
  }
  class MarkerMock {
    constructor(public options: OverlayOptions) {}
  }
  class PolygonMock {
    constructor(public options: OverlayOptions) { polygonOptions.push(options); }
  }
  class CircleMock {
    constructor(public options: OverlayOptions) {}
  }
  class GeocoderMock {
    constructor(_options?: Record<string, unknown>) {}
    getAddress(
      _coordinate: Coordinate,
      callback: (
        status: string,
        result: {
          info: string;
          regeocode: { formattedAddress: string; pois: Array<{ name: string }> };
        },
      ) => void,
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

  const convertFrom = vi.fn((
    coordinate: Coordinate,
    _type: 'gps',
    callback: (
      status: string,
      result: { info: string; locations: Coordinate[] },
    ) => void,
  ) => callback('complete', {
    info: 'ok',
    locations: [[coordinate[0] + 0.01, coordinate[1] + 0.01]],
  }));

  const amap = {
    Map: MapMock,
    Marker: MarkerMock,
    Polygon: PolygonMock,
    Circle: CircleMock,
    Geocoder: GeocoderMock,
    convertFrom,
  } as unknown as AmapNamespace;
  window.AMap = amap;
  return { amap, added, polygonOptions, convertFrom, mapDestroy, mapRemove };
}

afterEach(() => {
  cleanup();
  delete window.AMap;
  delete window._AMapSecurityConfig;
  document.querySelectorAll('script[data-amap-loader]').forEach((node) => node.remove());
  resetAmapLoaderForTests();
  Object.defineProperty(navigator, 'geolocation', {
    configurable: true,
    value: undefined,
  });
  Object.defineProperty(window, 'isSecureContext', {
    configurable: true,
    value: false,
  });
  vi.restoreAllMocks();
});

describe('AmapTaskMap helpers', () => {
  it('计算并格式化直线距离', () => {
    expect(haversineDistance([118, 25], [118, 25])).toBe(0);
    expect(formatDistance(126.4)).toBe('126 米');
    expect(formatDistance(1250)).toBe('1.3 公里');
  });

  it('只在安全上下文或 localhost 且定位 API 可用时允许定位', () => {
    expect(isGeolocationContextAllowed(false, '10.10.11.128', true)).toBe(false);
    expect(isGeolocationContextAllowed(true, '10.10.11.128', true)).toBe(true);
    expect(isGeolocationContextAllowed(false, 'localhost', true)).toBe(true);
    expect(isGeolocationContextAllowed(true, 'example.test', false)).toBe(false);
  });

  it('严格处理 WGS-84 转换成功和失败', async () => {
    const { amap } = installAmapMock();
    const converted = await convertGpsCoordinate(amap, [118.1, 25.1]);
    expect(converted[0]).toBeCloseTo(118.11, 8);
    expect(converted[1]).toBeCloseTo(25.11, 8);

    const failed = {
      ...amap,
      convertFrom: (
        _coordinate: Coordinate,
        _type: 'gps',
        callback: (status: string, result: { info: string; locations: Coordinate[] }) => void,
      ) => callback('error', { info: 'failed', locations: [] }),
    };
    await expect(convertGpsCoordinate(failed, [118.1, 25.1])).rejects.toThrow('坐标转换失败');
  });
});

describe('AmapTaskMap component', () => {
  it('地图关闭时不加载 SDK', () => {
    render(
      <ConfigProvider>
        <AmapTaskMap
          details={details}
          config={{ ...enabledConfig, enabled: false, js_key: null }}
        />
      </ConfigProvider>,
    );
    expect(screen.getByText('高德地图未启用')).toBeInTheDocument();
    expect(document.querySelector('script[data-amap-loader]')).toBeNull();
  });

  it('展示签到点、逆地理地址和精确偏移矩形', async () => {
    const { polygonOptions, mapDestroy } = installAmapMock();
    const { unmount } = render(
      <ConfigProvider><AmapTaskMap details={details} config={enabledConfig} /></ConfigProvider>,
    );

    expect(await screen.findByText(/福建省福州市仓山区/)).toBeInTheDocument();
    expect(screen.getByText(/橙色区域为当前 GPS 随机偏移范围/)).toBeInTheDocument();
    expect(polygonOptions).toHaveLength(1);
    const path = polygonOptions[0].path as Coordinate[];
    const expected: Coordinate[] = [
      [118.09995, 25.09995],
      [118.10005, 25.09995],
      [118.10005, 25.10005],
      [118.09995, 25.10005],
    ];
    path.forEach((coordinate, index) => {
      expect(coordinate[0]).toBeCloseTo(expected[index][0], 8);
      expect(coordinate[1]).toBeCloseTo(expected[index][1], 8);
    });

    unmount();
    expect(mapDestroy).toHaveBeenCalledOnce();
  });

  it('用户点击后才获取当前位置并显示距离', async () => {
    const { convertFrom } = installAmapMock();
    const getCurrentPosition = vi.fn((
      success: PositionCallback,
      _error?: PositionErrorCallback | null,
    ) => success({
      coords: {
        longitude: 118.1001,
        latitude: 25.1001,
        accuracy: 12,
        altitude: null,
        altitudeAccuracy: null,
        heading: null,
        speed: null,
        toJSON: () => ({}),
      },
      timestamp: Date.now(),
      toJSON: () => ({}),
    } as GeolocationPosition));
    Object.defineProperty(navigator, 'geolocation', {
      configurable: true,
      value: { getCurrentPosition },
    });
    Object.defineProperty(window, 'isSecureContext', {
      configurable: true,
      value: true,
    });

    render(
      <ConfigProvider><AmapTaskMap details={details} config={enabledConfig} /></ConfigProvider>,
    );
    const button = await screen.findByRole('button', { name: /获取当前位置/ });
    await waitFor(() => expect(button).toBeEnabled());
    expect(getCurrentPosition).not.toHaveBeenCalled();

    fireEvent.click(button);

    await waitFor(() => expect(getCurrentPosition).toHaveBeenCalledOnce());
    expect(await screen.findByText(/距签到点约/)).toBeInTheDocument();
    expect(convertFrom).toHaveBeenCalledWith(
      [118.1001, 25.1001],
      'gps',
      expect.any(Function),
    );
  });

  it('SDK 加载失败时保留可理解错误', async () => {
    render(
      <ConfigProvider><AmapTaskMap details={details} config={enabledConfig} /></ConfigProvider>,
    );
    const script = document.querySelector('script[data-amap-loader]');
    expect(script).not.toBeNull();
    fireEvent.error(script as HTMLScriptElement);
    expect(await screen.findByText('地图暂不可用')).toBeInTheDocument();
    expect(screen.getByText(/无法加载高德地图/)).toBeInTheDocument();
  });
});