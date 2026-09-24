import type {
  ActionResponse, AdminUser, AuditLog, AuthUser, BootstrapStatus, BootstrapSystemInput,
  ApiErrorDetail, FafuAuthAttempt, FafuAuthStartInput, ImageCategory, ImageRecord, LogsResponse, MapConfig, PageResponse,
  ManualSignOptions, Pairing, RunRecord, RunResult, RunTrigger, Settings, SettingsUpdate, SignTaskDetails,
  SignTaskPage, StatusResponse, SystemSettings, SystemSettingsUpdate, UserSession,
  UserStatus,
} from '../types/api';

const API_BASE = '/api';
let csrfToken: string | null = null;
type QueryValue = string | number | boolean | null | undefined;

export function setCsrfToken(value: string | null): void {
  csrfToken = value;
}

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
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value));
  });
  const result = search.toString();
  return result ? `?${result}` : '';
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  headers.set('Accept', 'application/json');
  const method = (init.method ?? 'GET').toUpperCase();
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && csrfToken) {
    headers.set('X-CSRF-Token', csrfToken);
  }
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers, credentials: 'same-origin' });
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
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '发生未知错误';
}

export const api = {
  getBootstrapStatus: (): Promise<BootstrapStatus> => request('/bootstrap/status'),
  configureBootstrap: (input: BootstrapSystemInput): Promise<BootstrapStatus> =>
    request('/bootstrap/system', { method: 'PUT', body: JSON.stringify(input) }),
  createAdminPairing: (): Promise<Pairing> =>
    request('/bootstrap/admin-pairings', { method: 'POST' }),
  getAdminPairing: (id: string): Promise<Pairing> =>
    request(`/bootstrap/admin-pairings/${encodeURIComponent(id)}`),
  exchangeAdminPairing: (id: string): Promise<AuthUser> =>
    request(`/bootstrap/admin-pairings/${encodeURIComponent(id)}/exchange`, { method: 'POST' }),
  createLoginPairing: (): Promise<Pairing> => request('/auth/pairings', { method: 'POST' }),
  getLoginPairing: (id: string): Promise<Pairing> =>
    request(`/auth/pairings/${encodeURIComponent(id)}`),
  exchangeLoginPairing: (id: string): Promise<AuthUser> =>
    request(`/auth/pairings/${encodeURIComponent(id)}/exchange`, { method: 'POST' }),
  getMe: (): Promise<AuthUser> => request('/auth/me'),
  logout: (): Promise<void> => request('/auth/logout', { method: 'POST' }),
  getSessions: (): Promise<UserSession[]> => request('/auth/sessions'),
  revokeSession: (id: string): Promise<void> =>
    request(`/auth/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  completeProfile: (nickname: string, avatar?: File): Promise<AuthUser> => {
    const form = new FormData();
    form.append('nickname', nickname);
    if (avatar) form.append('avatar', avatar);
    return request('/onboarding/profile', { method: 'PUT', body: form });
  },
  getOnboardingStatus: (): Promise<AuthUser> => request('/onboarding/status'),

  getSettings: (): Promise<Settings> => request('/settings'),
  updateSettings: (settings: SettingsUpdate): Promise<Settings> =>
    request('/settings', { method: 'PUT', body: JSON.stringify(settings) }),
  startFafuAuth: (input: FafuAuthStartInput): Promise<FafuAuthAttempt> =>
    request('/fafu-auth/start', { method: 'POST', body: JSON.stringify(input) }),
  completeFafuAuth: (attemptId: string, code: string): Promise<Settings> =>
    request('/fafu-auth/complete', { method: 'POST', body: JSON.stringify({ attempt_id: attemptId, code }) }),
  reconnectFafuAuth: (): Promise<FafuAuthAttempt> =>
    request('/fafu-auth/reconnect', { method: 'POST' }),
  cancelFafuAuth: (attemptId: string): Promise<void> =>
    request('/fafu-auth/cancel', { method: 'POST', body: JSON.stringify({ attempt_id: attemptId }) }),
  getStatus: (): Promise<StatusResponse> => request('/status'),
  getMapConfig: (): Promise<MapConfig> => request('/map/config'),
  pauseWorker: (): Promise<ActionResponse> => request('/worker/pause', { method: 'POST' }),
  resumeWorker: (): Promise<ActionResponse> => request('/worker/resume', { method: 'POST' }),
  runNow: (): Promise<ActionResponse> => request('/worker/run-now', { method: 'POST' }),
  listSignTasks: (page = 1, pageSize = 20): Promise<SignTaskPage> =>
    request(`/sign-tasks${buildQuery({ page, page_size: pageSize })}`),
  getSignTask: (id: string): Promise<SignTaskDetails> =>
    request(`/sign-tasks/${encodeURIComponent(id)}`),
  submitSignTask: (
    id: string,
    sourcePage: number,
    pageSize: number,
    options: ManualSignOptions = { location_mode: 'rule_jitter' },
  ): Promise<RunRecord> =>
    request(`/sign-tasks/${encodeURIComponent(id)}/submit`, {
      method: 'POST',
      body: JSON.stringify({ source_page: sourcePage, page_size: pageSize, ...options }),
    }),
  listImages: (page = 1, pageSize = 24, category?: ImageCategory): Promise<PageResponse<ImageRecord>> =>
    request(`/images${buildQuery({ page, page_size: pageSize, category })}`),
  uploadImages: (files: File[], category: ImageCategory): Promise<ImageRecord[]> => {
    const form = new FormData();
    files.forEach((file) => form.append('files', file));
    form.append('category', category);
    return request('/images', { method: 'POST', body: form });
  },
  imageUrl: (id: string): string => `${API_BASE}/images/${encodeURIComponent(id)}`,
  deleteImage: (id: string): Promise<void> =>
    request(`/images/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  listRuns: (page = 1, pageSize = 20, result?: RunResult, trigger?: RunTrigger): Promise<PageResponse<RunRecord>> =>
    request(`/runs${buildQuery({ page, page_size: pageSize, result, trigger })}`),
  getRun: (id: number): Promise<RunRecord> => request(`/runs/${id}`),
  getLogs: (cursor?: string | number | null, limit = 200, level?: string): Promise<LogsResponse> =>
    request(`/logs${buildQuery({ cursor, limit, level })}`),
  testWechatNotification: (): Promise<ActionResponse> =>
    request('/notifications/wechat-test/test', { method: 'POST' }),

  listAdminUsers: (page = 1, pageSize = 20, status?: UserStatus): Promise<PageResponse<AdminUser>> =>
    request(`/admin/users${buildQuery({ page, page_size: pageSize, status })}`),
  getAdminUser: (id: string): Promise<AdminUser> =>
    request(`/admin/users/${encodeURIComponent(id)}`),
  updateAdminUser: (
    id: string,
    input: Partial<{ status: UserStatus; role: 'admin' | 'user'; rejection_reason: string }>,
  ): Promise<AdminUser> =>
    request(`/admin/users/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(input) }),
  deleteAdminUser: (id: string): Promise<void> =>
    request(`/admin/users/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  getAdminUserSettings: (id: string): Promise<Settings> =>
    request(`/admin/users/${encodeURIComponent(id)}/settings`),
  updateAdminUserSettings: (id: string, input: SettingsUpdate): Promise<Settings> =>
    request(`/admin/users/${encodeURIComponent(id)}/settings`, {
      method: 'PUT', body: JSON.stringify(input),
    }),
  revealAdminUserToken: (id: string): Promise<{ user_token: string | null }> =>
    request(`/admin/users/${encodeURIComponent(id)}/token/reveal`, { method: 'POST' }),
  getAdminUserSessions: (id: string): Promise<UserSession[]> =>
    request(`/admin/users/${encodeURIComponent(id)}/sessions`),
  getAdminUserImages: (id: string): Promise<PageResponse<ImageRecord>> =>
    request(`/admin/users/${encodeURIComponent(id)}/images?page=1&page_size=100`),
  adminUserImageUrl: (userId: string, imageId: string): string =>
    `${API_BASE}/admin/users/${encodeURIComponent(userId)}/images/${encodeURIComponent(imageId)}`,
  getAdminUserRuns: (id: string): Promise<PageResponse<RunRecord>> =>
    request(`/admin/users/${encodeURIComponent(id)}/runs?page=1&page_size=20`),
  testAdminUserNotification: (id: string): Promise<ActionResponse> =>
    request(`/admin/users/${encodeURIComponent(id)}/notifications/test`, { method: 'POST' }),
  revokeAdminUserSessions: (id: string): Promise<void> =>
    request(`/admin/users/${encodeURIComponent(id)}/sessions/revoke`, { method: 'POST' }),
  pauseAdminUserWorker: (id: string): Promise<ActionResponse> =>
    request(`/admin/users/${encodeURIComponent(id)}/worker/pause`, { method: 'POST' }),
  resumeAdminUserWorker: (id: string): Promise<ActionResponse> =>
    request(`/admin/users/${encodeURIComponent(id)}/worker/resume`, { method: 'POST' }),
  runAdminUserNow: (id: string): Promise<ActionResponse> =>
    request(`/admin/users/${encodeURIComponent(id)}/worker/run-now`, { method: 'POST' }),
  getAdminSystem: (): Promise<SystemSettings> => request('/admin/system'),
  updateAdminSystem: (input: SystemSettingsUpdate): Promise<SystemSettings> =>
    request('/admin/system', { method: 'PUT', body: JSON.stringify(input) }),
  revealSystemSecrets: (): Promise<{ wechat_app_secret: string | null; amap_security_js_code: string | null }> =>
    request('/admin/system/secret/reveal', { method: 'POST' }),
  syncMenu: (): Promise<ActionResponse> =>
    request('/admin/system/menu/sync', { method: 'POST' }),
  getAdminAudit: (page = 1, pageSize = 30, targetUserId?: string): Promise<PageResponse<AuditLog>> =>
    request(`/admin/audit${buildQuery({ page, page_size: pageSize, target_user_id: targetUserId })}`),
  getAdminStats: (): Promise<{ users: number; pending: number; active: number; queued_jobs: number }> =>
    request('/admin/stats'),
};