import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  ExclamationCircleOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import { Alert, App as AntApp, Button, Card, Col, Descriptions, Row, Space, Statistic, Typography } from 'antd';
import dayjs from 'dayjs';
import type { ReactNode } from 'react';
import { api, getErrorMessage } from '../api/client';
import { AsyncState } from '../components/AsyncState';
import { PageHeading } from '../components/PageHeading';
import { RunResultTag, WorkerStatusTag } from '../components/StatusTag';
import { usePolling } from '../hooks/usePolling';
import type { StatusResponse } from '../types/api';

function formatTime(value: string | null): string {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '—';
}

export function DashboardPage(): ReactNode {
  const { message } = AntApp.useApp();
  const status = usePolling<StatusResponse>(api.getStatus, 10_000);

  const runAction = async (action: 'pause' | 'resume' | 'run'): Promise<void> => {
    try {
      const result = action === 'pause' ? await api.pauseWorker() : action === 'resume' ? await api.resumeWorker() : await api.runNow();
      message.success(result.message);
      await status.refresh();
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  const current = status.data;
  const state = current?.worker_state;
  const stats = current?.stats_7d ?? {};

  return (
    <div className="page-container">
      <PageHeading
        title="运行概览"
        description="查看自动签到状态与最近七天执行结果"
        extra={
          <>
            {state === 'paused' ? (
              <Button icon={<PlayCircleOutlined />} onClick={() => void runAction('resume')}>继续运行</Button>
            ) : (
              <Button icon={<PauseCircleOutlined />} disabled={!current?.configured || state === 'executing'} onClick={() => void runAction('pause')}>暂停</Button>
            )}
            <Button type="primary" icon={<ReloadOutlined />} loading={state === 'executing'} disabled={!current?.configured} onClick={() => void runAction('run')}>立即检查</Button>
          </>
        }
      />

      <AsyncState loading={status.loading} error={status.error}>
        {current && (
          <Space direction="vertical" size={20} className="full-width">
            {!current.configured && (
              <Alert
                type="warning"
                showIcon
                message="尚未完成配置"
                description="请先在设置页填写 Token 并上传签到图片，后台任务不会在配置完成前发起请求。"
                action={<Button href="/settings" size="small">前往设置</Button>}
              />
            )}
            {current.last_error && (
              <Alert type="error" showIcon closable message="最近发生错误" description={current.last_error} />
            )}

            <Row gutter={[16, 16]}>
              <Col xs={24} sm={12} xl={6}>
                <Card className="metric-card">
                  <Statistic title="服务状态" valueRender={() => state ? <WorkerStatusTag state={state} /> : '—'} prefix={<ClockCircleOutlined />} />
                </Card>
              </Col>
              <Col xs={12} sm={12} xl={6}>
                <Card className="metric-card">
                  <Statistic title="7 天成功" value={stats.success ?? 0} prefix={<CheckCircleOutlined />} valueStyle={{ color: '#0f766e' }} />
                </Card>
              </Col>
              <Col xs={12} sm={12} xl={6}>
                <Card className="metric-card">
                  <Statistic title="7 天失败" value={(stats.failed ?? 0) + (stats.fatal ?? 0)} prefix={<ExclamationCircleOutlined />} valueStyle={{ color: '#b42318' }} />
                </Card>
              </Col>
              <Col xs={24} sm={12} xl={6}>
                <Card className="metric-card">
                  <Statistic title="7 天检查" value={stats.total ?? 0} prefix={<ReloadOutlined />} />
                </Card>
              </Col>
            </Row>

            <Row gutter={[16, 16]}>
              <Col xs={24} lg={12}>
                <Card title="调度信息" className="content-card">
                  <Descriptions column={1} size="small">
                    <Descriptions.Item label="上次检查">{formatTime(current.last_check_at)}</Descriptions.Item>
                    <Descriptions.Item label="下次检查">{formatTime(current.next_check_at)}</Descriptions.Item>
                    <Descriptions.Item label="配置状态">{current.configured ? '已完成' : '待完善'}</Descriptions.Item>
                  </Descriptions>
                </Card>
              </Col>
              <Col xs={24} lg={12}>
                <Card title="最近一次执行" className="content-card">
                  {current.recent_run ? (
                    <Descriptions column={1} size="small">
                      <Descriptions.Item label="结果"><RunResultTag result={current.recent_run.result} /></Descriptions.Item>
                      <Descriptions.Item label="开始时间">{formatTime(current.recent_run.started_at)}</Descriptions.Item>
                      <Descriptions.Item label="任务数量">{current.recent_run.task_count}</Descriptions.Item>
                      <Descriptions.Item label="摘要">{current.recent_run.summary || '—'}</Descriptions.Item>
                    </Descriptions>
                  ) : (
                    <Typography.Text type="secondary">还没有执行记录</Typography.Text>
                  )}
                </Card>
              </Col>
            </Row>
          </Space>
        )}
      </AsyncState>
    </div>
  );
}