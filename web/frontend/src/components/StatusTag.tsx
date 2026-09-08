import { Tag } from 'antd';
import type { ReactNode } from 'react';
import type { RunResult, WorkerState } from '../types/api';

const workerLabels: Record<WorkerState, string> = {
  unconfigured: '待配置',
  idle: '运行中',
  executing: '正在检查',
  paused: '已暂停',
  error: '异常',
  stopping: '正在停止',
};

const resultLabels: Record<RunResult, string> = {
  no_task: '无任务',
  success: '成功',
  partial: '部分成功',
  failed: '失败',
  fatal: '致命错误',
};

export function WorkerStatusTag({ state }: { state: WorkerState }): ReactNode {
  const color = state === 'idle' ? 'success' : state === 'executing' ? 'processing' : state === 'paused' ? 'warning' : state === 'unconfigured' ? 'default' : 'error';
  return <Tag color={color}>{workerLabels[state]}</Tag>;
}

export function RunResultTag({ result }: { result: RunResult }): ReactNode {
  const color = result === 'success' ? 'success' : result === 'partial' ? 'warning' : result === 'no_task' ? 'default' : 'error';
  return <Tag color={color}>{resultLabels[result]}</Tag>;
}

export function runResultLabel(result: RunResult): string {
  return resultLabels[result];
}