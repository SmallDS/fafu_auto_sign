import { EnvironmentOutlined } from '@ant-design/icons';
import { Alert, Button, Space, Spin, Typography } from 'antd';
import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import type { MapConfig, SignTaskDetails } from '../types/api';

export type Coordinate = [number, number];

interface AmapLocation {
  getLng?: () => number;
  getLat?: () => number;
  lng?: number;
  lat?: number;
}

interface AmapConvertResult {
  info?: string;
  locations?: Array<AmapLocation | Coordinate>;
}

interface AmapGeocoderResult {
  info?: string;
  regeocode?: {
    formattedAddress?: string;
    pois?: Array<{ name?: string }>;
  };
}

interface AmapOverlay {}

interface AmapMap {
  add: (overlays: AmapOverlay | AmapOverlay[]) => void;
  remove: (overlays: AmapOverlay | AmapOverlay[]) => void;
  destroy: () => void;
  resize?: () => void;
  setFitView?: (
    overlays?: AmapOverlay[],
    immediately?: boolean,
    avoid?: [number, number, number, number],
    maxZoom?: number,
  ) => void;
}

export interface AmapNamespace {
  Map: new (container: HTMLElement, options: Record<string, unknown>) => AmapMap;
  Marker: new (options: Record<string, unknown>) => AmapOverlay;
  Polygon: new (options: Record<string, unknown>) => AmapOverlay;
  Circle: new (options: Record<string, unknown>) => AmapOverlay;
  Geocoder: new (options?: Record<string, unknown>) => {
    getAddress: (
      coordinate: Coordinate,
      callback: (status: string, result: AmapGeocoderResult) => void,
    ) => void;
  };
  convertFrom: (
    coordinate: Coordinate,
    type: 'gps',
    callback: (status: string, result: AmapConvertResult) => void,
  ) => void;
}

declare global {
  interface Window {
    AMap?: AmapNamespace;
    _AMapSecurityConfig?: {
      serviceHost: string;
    };
  }
}

let loaderPromise: Promise<AmapNamespace> | null = null;
let loaderKey: string | null = null;

export function resetAmapLoaderForTests(): void {
  loaderPromise = null;
  loaderKey = null;
}

export function loadAmap(config: MapConfig): Promise<AmapNamespace> {
  if (window.AMap) {
    if (loaderKey && loaderKey !== config.js_key) {
      return Promise.reject(new Error('高德地图 Key 已变更，请刷新页面后重试'));
    }
    return Promise.resolve(window.AMap);
  }
  if (!config.enabled || !config.js_key) {
    return Promise.reject(new Error('高德地图尚未启用'));
  }
  if (loaderPromise) {
    if (loaderKey !== config.js_key) {
      return Promise.reject(new Error('高德地图 Key 已变更，请刷新页面后重试'));
    }
    return loaderPromise;
  }

  loaderKey = config.js_key;
  window._AMapSecurityConfig = {
    serviceHost: new URL(config.service_host, window.location.origin).toString().replace(/\/$/, ''),
  };
  loaderPromise = new Promise<AmapNamespace>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://webapi.amap.com/maps?v=2.0&key='
      + encodeURIComponent(config.js_key ?? '')
      + '&plugin=AMap.Geocoder';
    script.async = true;
    script.dataset.amapLoader = 'true';
    script.onload = () => {
      if (window.AMap) {
        resolve(window.AMap);
      } else {
        loaderPromise = null;
        loaderKey = null;
        reject(new Error('高德地图 SDK 加载失败'));
      }
    };
    script.onerror = () => {
      script.remove();
      loaderPromise = null;
      loaderKey = null;
      reject(new Error('无法加载高德地图，请检查网络和 Key 配置'));
    };
    document.head.appendChild(script);
  });
  return loaderPromise;
}

function toCoordinate(value: AmapLocation | Coordinate | undefined): Coordinate | null {
  if (!value) return null;
  if (Array.isArray(value)) {
    return Number.isFinite(value[0]) && Number.isFinite(value[1])
      ? [value[0], value[1]]
      : null;
  }
  const lng = typeof value.getLng === 'function' ? value.getLng() : value.lng;
  const lat = typeof value.getLat === 'function' ? value.getLat() : value.lat;
  return typeof lng === 'number' && typeof lat === 'number'
    && Number.isFinite(lng) && Number.isFinite(lat)
    ? [lng, lat]
    : null;
}

export function convertGpsCoordinate(
  amap: AmapNamespace,
  coordinate: Coordinate,
): Promise<Coordinate> {
  return new Promise((resolve, reject) => {
    amap.convertFrom(coordinate, 'gps', (status, result) => {
      const converted = toCoordinate(result.locations?.[0]);
      if (status === 'complete' && result.info?.toLowerCase() === 'ok' && converted) {
        resolve(converted);
      } else {
        reject(new Error('坐标转换失败，已保留 FAFU 原始坐标'));
      }
    });
  });
}

export function haversineDistance(from: Coordinate, to: Coordinate): number {
  const radians = (value: number): number => value * Math.PI / 180;
  const earthRadius = 6_371_000;
  const deltaLat = radians(to[1] - from[1]);
  const deltaLng = radians(to[0] - from[0]);
  const fromLat = radians(from[1]);
  const toLat = radians(to[1]);
  const value = Math.sin(deltaLat / 2) ** 2
    + Math.cos(fromLat) * Math.cos(toLat) * Math.sin(deltaLng / 2) ** 2;
  return earthRadius * 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value));
}

export function formatDistance(distance: number): string {
  return distance < 1000
    ? Math.round(distance) + ' 米'
    : (distance / 1000).toFixed(1) + ' 公里';
}

export function isGeolocationContextAllowed(
  isSecureContext: boolean,
  hostname: string,
  hasGeolocationApi: boolean,
): boolean {
  const localhost = ['localhost', '127.0.0.1', '::1'].includes(hostname);
  return (isSecureContext || localhost) && hasGeolocationApi;
}

export function canUseBrowserGeolocation(): boolean {
  return isGeolocationContextAllowed(
    Boolean(window.isSecureContext),
    window.location.hostname,
    Boolean(navigator.geolocation),
  );
}

function geolocationErrorMessage(error: GeolocationPositionError): string {
  if (error.code === error.PERMISSION_DENIED) return '定位权限被拒绝，请在浏览器设置中允许定位';
  if (error.code === error.TIMEOUT) return '获取当前位置超时，请稍后重试';
  return '暂时无法获取当前位置';
}

interface AmapTaskMapProps {
  details: SignTaskDetails;
  config: MapConfig;
}

export function AmapTaskMap({ details, config }: AmapTaskMapProps): ReactNode {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<AmapMap | null>(null);
  const amapRef = useRef<AmapNamespace | null>(null);
  const taskCoordinateRef = useRef<Coordinate | null>(null);
  const taskMarkerRef = useRef<AmapOverlay | null>(null);
  const userOverlaysRef = useRef<AmapOverlay[]>([]);
  const [ready, setReady] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);
  const [address, setAddress] = useState<string | null>(null);
  const [addressUnavailable, setAddressUnavailable] = useState(false);
  const [locating, setLocating] = useState(false);
  const [locationError, setLocationError] = useState<string | null>(null);
  const [distance, setDistance] = useState<number | null>(null);

  useEffect(() => {
    if (!config.enabled || !config.js_key || !containerRef.current) return;
    let cancelled = false;
    let map: AmapMap | null = null;
    let resizeTimer: number | null = null;
    setReady(false);
    setMapError(null);
    setAddress(null);
    setAddressUnavailable(false);
    setLocationError(null);
    setDistance(null);

    const initialize = async (): Promise<void> => {
      try {
        const amap = await loadAmap(config);
        const rawTask: Coordinate = [details.base_lng, details.base_lat];
        const rawBounds: Coordinate[] = config.jitter > 0
          ? [
              [details.base_lng - config.jitter, details.base_lat - config.jitter],
              [details.base_lng + config.jitter, details.base_lat - config.jitter],
              [details.base_lng + config.jitter, details.base_lat + config.jitter],
              [details.base_lng - config.jitter, details.base_lat + config.jitter],
            ]
          : [];
        const taskCoordinate = rawTask;
        const displayBounds = rawBounds;
        if (cancelled || !containerRef.current) return;

        map = new amap.Map(containerRef.current, {
          center: taskCoordinate,
          zoom: 17,
          viewMode: '2D',
          resizeEnable: true,
        });
        const taskMarker = new amap.Marker({
          position: taskCoordinate,
          title: details.position_name || '任务 ' + details.task_id,
        });
        const overlays: AmapOverlay[] = [taskMarker];
        if (displayBounds.length > 0) {
          overlays.push(new amap.Polygon({
            path: displayBounds,
            strokeColor: '#d97706',
            strokeWeight: 2,
            strokeOpacity: 0.9,
            fillColor: '#f59e0b',
            fillOpacity: 0.18,
            bubble: false,
          }));
        }
        map.add(overlays);
        amapRef.current = amap;
        mapRef.current = map;
        taskCoordinateRef.current = taskCoordinate;
        taskMarkerRef.current = taskMarker;
        setReady(true);

        const geocoder = new amap.Geocoder({ radius: 200, extensions: 'all' });
        geocoder.getAddress(taskCoordinate, (status, result) => {
          if (cancelled) return;
          const formatted = result.regeocode?.formattedAddress?.trim();
          const nearestPoi = result.regeocode?.pois?.[0]?.name?.trim();
          if (status === 'complete' && result.info === 'OK' && formatted) {
            setAddress(nearestPoi ? formatted + '（附近：' + nearestPoi + '）' : formatted);
          } else {
            setAddressUnavailable(true);
          }
        });
        resizeTimer = window.setTimeout(() => map?.resize?.(), 120);
      } catch (error) {
        if (!cancelled) {
          setMapError(error instanceof Error ? error.message : '高德地图加载失败');
        }
      }
    };

    void initialize();
    return () => {
      cancelled = true;
      if (resizeTimer !== null) window.clearTimeout(resizeTimer);
      userOverlaysRef.current = [];
      taskMarkerRef.current = null;
      taskCoordinateRef.current = null;
      amapRef.current = null;
      mapRef.current = null;
      map?.destroy();
    };
  }, [
    config.enabled,
    config.jitter,
    config.js_key,
    config.service_host,
    details.base_lat,
    details.base_lng,
    details.position_name,
    details.task_id,
  ]);

  const locate = (): void => {
    if (!canUseBrowserGeolocation()) {
      setLocationError('当前位置距离需要 HTTPS 或 localhost，并且浏览器必须支持定位');
      return;
    }
    setLocating(true);
    setLocationError(null);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        void (async () => {
          try {
            const amap = amapRef.current;
            const map = mapRef.current;
            const taskCoordinate = taskCoordinateRef.current;
            if (!amap || !map || !taskCoordinate) throw new Error('地图尚未准备完成');
            const rawCurrent: Coordinate = [
              position.coords.longitude,
              position.coords.latitude,
            ];
            const current = await convertGpsCoordinate(amap, rawCurrent);
            if (userOverlaysRef.current.length > 0) {
              map.remove(userOverlaysRef.current);
            }
            const marker = new amap.Marker({
              position: current,
              title: '我的当前位置',
              content: '<div class="amap-current-location-dot" aria-label="我的当前位置"></div>',
              anchor: 'center',
            });
            const accuracy = new amap.Circle({
              center: current,
              radius: Math.max(position.coords.accuracy, 1),
              strokeColor: '#1677ff',
              strokeOpacity: 0.65,
              strokeWeight: 1,
              fillColor: '#1677ff',
              fillOpacity: 0.12,
            });
            userOverlaysRef.current = [accuracy, marker];
            map.add(userOverlaysRef.current);
            if (taskMarkerRef.current && map.setFitView) {
              map.setFitView([taskMarkerRef.current, marker], false, [48, 48, 48, 48], 18);
            }
            setDistance(haversineDistance(taskCoordinate, current));
          } catch (error) {
            setLocationError(error instanceof Error ? error.message : '当前位置处理失败');
          } finally {
            setLocating(false);
          }
        })();
      },
      (error) => {
        setLocationError(geolocationErrorMessage(error));
        setLocating(false);
      },
      { enableHighAccuracy: true, timeout: 10_000, maximumAge: 30_000 },
    );
  };

  if (!config.enabled || !config.js_key) {
    return (
      <Alert
        type="info"
        showIcon
        message="高德地图未启用"
        description="可在系统设置中配置 JS Key 和 Security JS Code 后启用。"
      />
    );
  }

  return (
    <Space direction="vertical" size={12} className="full-width amap-task-map">
      {mapError ? (
        <Alert type="warning" showIcon message="地图暂不可用" description={mapError} />
      ) : (
        <div className="amap-map-frame">
          <div ref={containerRef} className="amap-map-container" aria-label="签到位置地图" />
          {!ready && <div className="amap-map-loading"><Spin tip="正在加载地图" /></div>}
        </div>
      )}
      {address && (
        <Typography.Text>
          <Typography.Text strong>地址：</Typography.Text>
          {address}
        </Typography.Text>
      )}
      {addressUnavailable && !mapError && (
        <Typography.Text type="secondary">地址解析暂不可用，地图坐标仍可正常查看。</Typography.Text>
      )}
      <Space wrap className="amap-location-row">
        <Button
          icon={<EnvironmentOutlined />}
          loading={locating}
          disabled={!ready}
          onClick={locate}
        >
          获取当前位置
        </Button>
        {distance !== null && (
          <Typography.Text strong>距签到点约 {formatDistance(distance)}</Typography.Text>
        )}
      </Space>
      {!canUseBrowserGeolocation() && (
        <Typography.Text type="secondary">
          当前页面无法使用浏览器定位；请通过 HTTPS 或 localhost 访问后获取距离。
        </Typography.Text>
      )}
      {locationError && <Alert type="warning" showIcon message={locationError} />}
      {config.jitter > 0 && !mapError && (
        <Typography.Text type="secondary">
          橙色区域为当前 GPS 随机偏移范围，仅用于展示，不会改变 FAFU 返回的基准位置。
        </Typography.Text>
      )}
    </Space>
  );
}