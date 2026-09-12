export type WorkerState = 'unconfigured' | 'idle' | 'queued' | 'executing' | 'paused' | 'error' | 'stopping';
export type ImageMode = 'single' | 'library' | 'latest';
export type ImageCategory = 'library' | 'latest';
export type RunResult = 'no_task' | 'success' | 'partial' | 'failed' | 'fatal';
export type RunTrigger = 'scheduled' | 'manual';
export type LogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL';
export type UserRole = 'admin' | 'user';
export type UserStatus = 'profile_pending' | 'pending' | 'active' | 'rejected' | 'disabled';

export interface BootstrapStatus {
  setup_state: 'uninitialized' | 'system_configured' | 'admin_binding' | 'initialized';
  initialized: boolean;
  system_configured: boolean;
  admin_binding: boolean;
  requires_system_configuration: boolean;
}

export interface BootstrapSystemInput {
  wechat_app_id: string;
  wechat_app_secret: string;
  wechat_template_id: string;
  public_base_url: string;
  menu_name: string;
  amap_enabled: boolean;
  amap_js_key?: string;
  amap_security_js_code?: string;
  log_level: LogLevel;
}

export interface Pairing {
  id: string;
  kind: 'admin' | 'login';
  status: string;
  auth_url: string | null;
  expires_at: string;
  user_status: string | null;
}

export interface AuthUser {
  id: string;
  nickname: string | null;
  avatar_url: string | null;
  role: UserRole;
  status: UserStatus;
  rejection_reason: string | null;
  csrf_token: string | null;
}

export interface UserSession {
  id: string;
  device_type: string;
  user_agent: string;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  current: boolean;
}

export interface Settings {
  configured: boolean;
  version: number;
  has_user_token: boolean;
  user_token_masked: string | null;
  jitter: number;
  heartbeat_interval: number;
  task_keywords: string[];
  image_mode: ImageMode;
  selected_image_id: string | null;
  worker_enabled: boolean;
  notification_enabled: boolean;
}

export interface SettingsUpdate {
  user_token?: string;
  clear_user_token?: boolean;
  jitter?: number;
  heartbeat_interval?: number;
  task_keywords?: string[];
  image_mode?: ImageMode;
  selected_image_id?: string | null;
  worker_enabled?: boolean;
  notification_enabled?: boolean;
}

export interface SystemSettings {
  setup_state: string;
  public_base_url: string | null;
  menu_name: string;
  wechat_app_id: string | null;
  wechat_template_id: string | null;
  wechat_enabled: boolean;
  has_wechat_app_secret: boolean;
  wechat_app_secret_masked: string | null;
  amap_enabled: boolean;
  amap_js_key: string | null;
  has_amap_security_js_code: boolean;
  amap_security_js_code_masked: string | null;
  log_level: LogLevel;
  menu_synced_at: string | null;
}

export type SystemSettingsUpdate = Partial<{
  public_base_url: string;
  menu_name: string;
  wechat_app_id: string;
  wechat_app_secret: string;
  clear_wechat_app_secret: boolean;
  wechat_template_id: string;
  wechat_enabled: boolean;
  amap_enabled: boolean;
  amap_js_key: string;
  amap_security_js_code: string;
  clear_amap_security_js_code: boolean;
  log_level: LogLevel;
}>;

export interface AdminUser {
  id: string;
  openid: string;
  unionid: string | null;
  nickname: string | null;
  avatar_url: string | null;
  role: UserRole;
  status: UserStatus;
  rejection_reason: string | null;
  configured: boolean;
  worker_enabled: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface AuditLog {
  id: number;
  actor_user_id: string | null;
  target_user_id: string | null;
  action: string;
  result: string;
  detail: string | null;
  created_at: string;
}

export interface Stats7d {
  total: number; success: number; partial: number; failed: number; fatal: number; no_task: number;
}
export interface RunTaskDetail {
  task_id?: string; task_name?: string; success?: boolean; status?: string; message?: string;
  [key: string]: unknown;
}
export interface RunRecord {
  id: number; trigger: RunTrigger; config_version: number; started_at: string;
  finished_at: string | null; result: RunResult; task_count: number;
  success_count: number; failure_count: number; summary: string | null;
  details?: RunTaskDetail[] | Record<string, unknown> | null;
}
export interface StatusResponse {
  configured: boolean; worker_state: WorkerState; last_check_at: string | null;
  next_check_at: string | null; last_error: string | null;
  recent_run: RunRecord | null; stats_7d: Partial<Stats7d>;
}
export interface ImageRecord {
  id: string; category: ImageCategory; original_name: string; mime_type: string;
  size: number; sha256: string; created_at: string;
}
export interface PageResponse<T> {
  items: T[]; total: number; page: number; page_size: number;
}
export interface SignTask {
  id: string; name: string; begin_time: number; end_time: number;
}
export interface SignTaskPage {
  items: SignTask[]; total: number | null; page: number; page_size: number; has_more: boolean;
}
export interface MapConfig {
  enabled: boolean; js_key: string | null; jitter: number; service_host: string;
}
export interface SignTaskDetails {
  task_id: number; position_id: number; base_lng: number; base_lat: number; position_name: string;
}
export interface LogEntry {
  id?: string | number; timestamp: string; level: LogLevel | string; logger?: string; message: string;
}
export interface LogsResponse {
  entries: LogEntry[]; next_cursor: string | number | null; reset: boolean;
}
export interface ActionResponse {
  state: WorkerState; message: string; job_id?: string | null;
}
export interface ApiErrorDetail {
  code?: string; message?: string; fields?: Record<string, string>;
}