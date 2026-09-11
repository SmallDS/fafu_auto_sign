import type {
  ActionResponse,
  ApiErrorDetail,
  ImageCategory,
  ImageRecord,
  LogsResponse,
  MapConfig,
  PageResponse,
  RunRecord,
  RunResult,
  RunTrigger,
  Settings,
  SettingsUpdate,
  SignTaskDetails,
  SignTaskPage,
  StatusResponse,
} from '../types/api';

const API_BASE = '/api';

type QueryValue = string | number | boolean | null | undefined;

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly fields?: Record<string, string>;

  constructor(status: number, message: string, detail?: ApiErrorDetail) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = detail?.code;
    this.fields = detail?.fields;
  }
}

function buildQuery(params: Record<string, QueryValue>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value));
    }
  });
  const value = search.toString();
  return value ? `?${value}` : '';
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  headers.set('Accept', 'application/json');

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch (error) {
    throw new ApiError(0, error instanceof Error ? error.message : '无法连接到服务');
  }

  if (!response.ok) {
    let detail: ApiErrorDetail | undefined;
    try {
      const payload = (await response.json()) as { detail?: ApiErrorDetail | string };
      detail = typeof payload.detail === 'string' ? { message: payload.detail } : payload.detail;
    } catch {
      detail = undefined;
    }
    throw new ApiError(response.status, detail?.message ?? `请求失败（${response.status}）`, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '发生未知错误';
}

export const api = {
  getSettings: (): Promise<Settings> => request('/settings'),
  updateSettings: (settings: SettingsUpdate): Promise<Settings> =>
    request('/settings', { method: 'PUT', body: JSON.stringify(settings) }),
  getStatus: (): Promise<StatusResponse> => request('/status'),
  getMapConfig: (): Promise<MapConfig> => request('/map/config'),
  pauseWorker: (): Promise<ActionResponse> => request('/worker/pause', { method: 'POST' }),
  resumeWorker: (): Promise<ActionResponse> => request('/worker/resume', { method: 'POST' }),
  runNow: (): Promise<ActionResponse> => request('/worker/run-now', { method: 'POST' }),
  listSignTasks: (page = 1, pageSize = 20): Promise<SignTaskPage> =>
    request(`/sign-tasks${buildQuery({ page, page_size: pageSize })}`),
  getSignTask: (id: string): Promise<SignTaskDetails> =>
    request(`/sign-tasks/${encodeURIComponent(id)}`),
  submitSignTask: (id: string, sourcePage: number, pageSize: number): Promise<RunRecord> =>
    request(`/sign-tasks/${encodeURIComponent(id)}/submit`, {
      method: 'POST',
      body: JSON.stringify({ source_page: sourcePage, page_size: pageSize }),
    }),  listImages: (page = 1, pageSize = 24, category?: ImageCategory): Promise<PageResponse<ImageRecord>> =>
    request(`/images${buildQuery({ page, page_size: pageSize, category })}`),
  uploadImages: (files: File[], category: ImageCategory): Promise<PageResponse<ImageRecord> | ImageRecord[]> => {
    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));
    formData.append('category', category);
    return request('/images', { method: 'POST', body: formData });
  },
  imageUrl: (id: string): string => `${API_BASE}/images/${encodeURIComponent(id)}`,
  deleteImage: (id: string): Promise<void> => request(`/images/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  listRuns: (
    page = 1,
    pageSize = 20,
    result?: RunResult,
    trigger?: RunTrigger,
  ): Promise<PageResponse<RunRecord>> =>
    request(`/runs${buildQuery({ page, page_size: pageSize, result, trigger })}`),
  getRun: (id: number): Promise<RunRecord> => request(`/runs/${id}`),
  getLogs: (cursor?: string | number | null, limit = 200, level?: string): Promise<LogsResponse> =>
    request(`/logs${buildQuery({ cursor, limit, level })}`),
  testWechatNotification: (): Promise<ActionResponse> =>
    request('/notifications/wechat-test/test', { method: 'POST' }),
};