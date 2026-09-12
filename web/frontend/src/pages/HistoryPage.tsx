import { EyeOutlined, ReloadOutlined } from '@ant-design/icons';
import {
  App as AntApp,
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Grid,
  List,
  Pagination,
  Select,
  Space,
  Table,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { useEffect, useState, type ReactNode } from 'react';
import { api, getErrorMessage } from '../api/client';
import { PageHeading } from '../components/PageHeading';
import { PageSkeleton } from '../components/PageSkeleton';
import { RunResultTag } from '../components/StatusTag';
import type { RunRecord, RunResult, RunTaskDetail, RunTrigger } from '../types/api';

const PAGE_SIZE = 20;

function formatTime(value: string | null): string {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '—';
}

function detailsArray(details: RunRecord['details']): RunTaskDetail[] {
  return Array.isArray(details) ? details : [];
}

export function HistoryPage(): ReactNode {
  const { message } = AntApp.useApp();
  const screens = Grid.useBreakpoint();
  const mobile = !screens.md;
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<RunResult | undefined>();
  const [trigger, setTrigger] = useState<RunTrigger | undefined>();
  const [loading, setLoading] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selected, setSelected] = useState<RunRecord | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const load = async (): Promise<void> => {
    setLoading(true);
    try {
      const response = await api.listRuns(page, PAGE_SIZE, result, trigger);
      setRuns(response.items);
      setTotal(response.total);
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [page, result, trigger]);

  const openDetail = async (record: RunRecord): Promise<void> => {
    setSelected(record);
    setDrawerOpen(true);
    setDetailLoading(true);
    try {
      setSelected(await api.getRun(record.id));
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setDetailLoading(false);
    }
  };

  const columns: ColumnsType<RunRecord> = [
    { title: '开始时间', dataIndex: 'started_at', width: 170, render: formatTime },
    { title: '触发方式', dataIndex: 'trigger', width: 100, render: (value: RunTrigger) => value === 'manual' ? '手动' : '定时' },
    { title: '结果', dataIndex: 'result', width: 110, render: (value: RunResult) => <RunResultTag result={value} /> },
    { title: '任务', dataIndex: 'task_count', width: 80 },
    { title: '成功 / 失败', width: 120, render: (_, record) => `${record.success_count} / ${record.failure_count}` },
    { title: '摘要', dataIndex: 'summary', ellipsis: true, render: (value: string | null) => value || '—' },
    { title: '', key: 'action', fixed: 'right', width: 70, render: (_, record) => <Button type="text" icon={<EyeOutlined />} aria-label={`查看记录 ${record.id}`} onClick={() => void openDetail(record)} /> },
  ];

  if (loading && runs.length === 0) return <div className="page-container"><PageSkeleton variant="list" /></div>;

  return (
    <div className="page-container">
      <PageHeading
        title="运行历史"
        description="查看定时与手动检查的执行结果"
        extra={<Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>刷新</Button>}
      />
      <Card className="content-card">
        <Space wrap className="filter-row">
          <Select
            allowClear
            placeholder="全部结果"
            value={result}
            onChange={(value) => { setResult(value); setPage(1); }}
            options={[
              { value: 'success', label: '成功' },
              { value: 'partial', label: '部分成功' },
              { value: 'failed', label: '失败' },
              { value: 'fatal', label: '致命错误' },
              { value: 'no_task', label: '无任务' },
            ]}
          />
          <Select
            allowClear
            placeholder="全部触发方式"
            value={trigger}
            onChange={(value) => { setTrigger(value); setPage(1); }}
            options={[{ value: 'scheduled', label: '定时' }, { value: 'manual', label: '手动' }]}
          />
        </Space>

        {mobile ? (
          <List
            loading={loading}
            dataSource={runs}
            locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无运行记录" /> }}
            renderItem={(item) => (
              <List.Item className="history-mobile-item" onClick={() => void openDetail(item)}>
                <div className="history-mobile-main">
                  <Space wrap><RunResultTag result={item.result} /><Typography.Text type="secondary">{item.trigger === 'manual' ? '手动' : '定时'}</Typography.Text></Space>
                  <Typography.Text strong>{formatTime(item.started_at)}</Typography.Text>
                  <Typography.Text type="secondary" ellipsis>{item.summary || `任务 ${item.task_count} 个`}</Typography.Text>
                </div>
                <EyeOutlined />
              </List.Item>
            )}
          />
        ) : (
          <Table<RunRecord>
            rowKey="id"
            columns={columns}
            dataSource={runs}
            loading={loading}
            pagination={false}
            scroll={{ x: 900 }}
            locale={{ emptyText: '暂无运行记录' }}
          />
        )}
        {total > PAGE_SIZE && (
          <Pagination className="center-pagination" current={page} pageSize={PAGE_SIZE} total={total} showSizeChanger={false} onChange={setPage} />
        )}
      </Card>

      <Drawer
        title={selected ? `运行记录 #${selected.id}` : '运行详情'}
        open={drawerOpen}
        loading={detailLoading}
        width={mobile ? '100%' : 560}
        onClose={() => setDrawerOpen(false)}
      >
        {selected && (
          <Space direction="vertical" size={20} className="full-width">
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="结果"><RunResultTag result={selected.result} /></Descriptions.Item>
              <Descriptions.Item label="触发方式">{selected.trigger === 'manual' ? '手动' : '定时'}</Descriptions.Item>
              <Descriptions.Item label="配置版本">{selected.config_version}</Descriptions.Item>
              <Descriptions.Item label="开始时间">{formatTime(selected.started_at)}</Descriptions.Item>
              <Descriptions.Item label="结束时间">{formatTime(selected.finished_at)}</Descriptions.Item>
              <Descriptions.Item label="任务统计">共 {selected.task_count}，成功 {selected.success_count}，失败 {selected.failure_count}</Descriptions.Item>
              <Descriptions.Item label="摘要">{selected.summary || '—'}</Descriptions.Item>
            </Descriptions>
            <Typography.Title level={5}>任务明细</Typography.Title>
            {detailsArray(selected.details).length ? (
              <List
                dataSource={detailsArray(selected.details)}
                renderItem={(item, index) => (
                  <List.Item>
                    <List.Item.Meta
                      title={item.task_name || item.task_id || `任务 ${index + 1}`}
                      description={item.message || item.status || (item.success ? '成功' : '失败')}
                    />
                  </List.Item>
                )}
              />
            ) : selected.details ? (
              <pre className="json-detail">{JSON.stringify(selected.details, null, 2)}</pre>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有任务明细" />
            )}
          </Space>
        )}
      </Drawer>
    </div>
  );
}