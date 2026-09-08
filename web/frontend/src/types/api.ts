export type WorkerState = 'unconfigured' | 'idle' | 'executing' | 'paused' | 'error' | 'stopping';
export type ImageMode = 'single' | 'library' | 'latest';
export type ImageCategory = 'library' | 'latest';
export type RunResult = 'no_task' | 'success' | 'partial' | 'failed' | 'fatal';
export type RunTrigger = 'scheduled' | 'manual';
export type LogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL';

export interface Settings {
  configured: boolean;
  version: number;
  has_user_token: boolean;
  user_token_masked: string | null;
  has_serverchan_key: boolean;
  serverchan_key_masked: string | null;
  jitter: number;
  heartbeat_interval: number;
  log_level: LogLevel;
  notification_enabled: boolean;
  task_keywords: string[];
  image_mode: ImageMode;
  selected_image_id: string | null;
  worker_enabled: boolean;
}

export interface SettingsUpdate {
  user_token?: string;
  serverchan_key?: string;
  clear_user_token?: boolean;
  clear_serverchan_key?: boolean;
  jitter?: number;
  heartbeat_interval?: number;
  log_level?: LogLevel;
  notification_enabled?: boolean;
  task_keywords?: string[];
  image_mode?: ImageMode;
  selected_image_id?: string | null;
  worker_enabled?: boolean;
}

export interface Stats7d {
  total: number;
  success: number;
  partial: number;
  failed: number;
  fatal: number;
  no_task: number;
}

export interface RunTaskDetail {
  task_id?: string;
  task_name?: string;
  success?: boolean;
  status?: string;
  message?: string;
  [key: string]: unknown;
}

export interface RunRecord {
  id: number;
  trigger: RunTrigger;
  config_version: number;
  started_at: string;
  finished_at: string | null;
  result: RunResult;
  task_count: number;
  success_count: number;
  failure_count: number;
  summary: string | null;
  details?: RunTaskDetail[] | Record<string, unknown> | null;
}

export interface StatusResponse {
  configured: boolean;
  worker_state: WorkerState;
  last_check_at: string | null;
  next_check_at: string | null;
  last_error: string | null;
  recent_run: RunRecord | null;
  stats_7d: Partial<Stats7d>;
}

export interface ImageRecord {
  id: string;
  category: ImageCategory;
  original_name: string;
  mime_type: string;
  size: number;
  sha256: string;
  created_at: string;
}

export interface PageResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface LogEntry {
  id?: string | number;
  timestamp: string;
  level: LogLevel | string;
  logger?: string;
  message: string;
}

export interface LogsResponse {
  entries: LogEntry[];
  next_cursor: string | number | null;
  reset: boolean;
}

export interface ActionResponse {
  state: WorkerState;
  message: string;
}

export interface ApiErrorDetail {
  code?: string;
  message?: string;
  fields?: Record<string, string>;
}