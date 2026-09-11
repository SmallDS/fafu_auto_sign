import { EyeOutlined, LoginOutlined, ReloadOutlined } from '@ant-design/icons';
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
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { useEffect, useState, type ReactNode } from 'react';
import { api, getErrorMessage } from '../api/client';
import { AmapTaskMap } from '../components/AmapTaskMap';
import { PageHeading } from '../components/PageHeading';
import type { MapConfig, SignTask, SignTaskDetails } from '../types/api';

const PAGE_SIZE = 20;
const DISABLED_MAP_CONFIG: MapConfig = {
  enabled: false,
  js_key: null,
  source_coordinate_system: 'gcj02',
  jitter: 0,
  service_host: '/_AMapService',
};

function formatTime(value: number): string {
  return dayjs(value).format('YYYY-MM-DD HH:mm:ss');
}

function isActive(task: SignTask): boolean {
  const now = Date.now();
  return task.begin_time <= now && now <= task.end_time;
}

export function SignTasksPage(): ReactNode {
  const { message, modal } = AntApp.useApp();
  const screens = Grid.useBreakpoint();
  const mobile = !screens.md;
  const [tasks, setTasks] = useState<SignTask[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState<number | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [details, setDetails] = useState<SignTaskDetails | null>(null);
  const [mapConfig, setMapConfig] = useState<MapConfig | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [submittingId, setSubmittingId] = useState<string | null>(null);

  const load = async (): Promise<void> => {
    setLoading(true);
    try {
      const response = await api.listSignTasks(page, PAGE_SIZE);
      setTasks(response.items);
      setTotal(response.total);
      setHasMore(response.has_more);
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [page]);

  const openDetails = async (task: SignTask): Promise<void> => {
    setDetailOpen(true);
    setDetails(null);
    setMapConfig(null);
    setDetailLoading(true);
    try {
      const nextDetails = await api.getSignTask(task.id);
      setDetails(nextDetails);
      try {
        setMapConfig(await api.getMapConfig());
      } catch {
        setMapConfig(DISABLED_MAP_CONFIG);
      }
    } catch (error) {
      message.error(getErrorMessage(error));
      setDetailOpen(false);
    } finally {
      setDetailLoading(false);
    }
  };

  const submit = (task: SignTask): void => {
    modal.confirm({
      title: `确认提交“${task.name || `任务 ${task.id}`}”吗？`,
      content: '将按当前图片策略上传图片，并立即向 FAFU 提交签到。',
      okText: '确认签到',
      cancelText: '取消',
      async onOk() {
        setSubmittingId(task.id);
        try {
          const result = await api.submitSignTask(task.id, page, PAGE_SIZE);
          if (result.result === 'success') {
            message.success('签到提交成功');
          } else {
            message.error(result.summary || '签到提交失败');
          }
          await load();
        } catch (error) {
          message.error(getErrorMessage(error));
          throw error;
        } finally {
          setSubmittingId(null);
        }
      },
    });
  };

  const actions = (task: SignTask): ReactNode => (
    <Space wrap>
      <Button icon={<EyeOutlined />} onClick={() => void openDetails(task)}>详情</Button>
      <Button
        type="primary"
        icon={<LoginOutlined />}
        disabled={!isActive(task)}
        loading={submittingId === task.id}
        onClick={() => submit(task)}
      >
        签到
      </Button>
    </Space>
  );

  const columns: ColumnsType<SignTask> = [
    { title: '任务名称', dataIndex: 'name', ellipsis: true, render: (value: string, task) => value || `任务 ${task.id}` },
    { title: '开始时间', dataIndex: 'begin_time', width: 170, render: formatTime },
    { title: '结束时间', dataIndex: 'end_time', width: 170, render: formatTime },
    { title: '状态', width: 90, render: (_, task) => isActive(task) ? <Tag color="green">进行中</Tag> : <Tag>未开放</Tag> },
    { title: '操作', width: 180, fixed: 'right', render: (_, task) => actions(task) },
  ];

  return (
    <div className="page-container">
      <PageHeading
        title="签到任务"
        description="浏览 FAFU 未签到任务，查看位置详情并手动提交"
        extra={<Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>刷新</Button>}
      />
      <Card className="content-card sign-task-card">
        {mobile ? (
          <List
            loading={loading}
            dataSource={tasks}
            locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无未签到任务" /> }}
            renderItem={(task) => (
              <List.Item className="sign-task-mobile-item">
                <Space direction="vertical" size={10} className="full-width">
                  <Space wrap>
                    <Typography.Text strong>{task.name || `任务 ${task.id}`}</Typography.Text>
                    {isActive(task) ? <Tag color="green">进行中</Tag> : <Tag>未开放</Tag>}
                  </Space>
                  <Typography.Text type="secondary">{formatTime(task.begin_time)} 至 {formatTime(task.end_time)}</Typography.Text>
                  <div className="sign-task-actions">{actions(task)}</div>
                </Space>
              </List.Item>
            )}
          />
        ) : (
          <Table<SignTask>
            rowKey="id"
            columns={columns}
            dataSource={tasks}
            loading={loading}
            pagination={false}
            scroll={{ x: 860 }}
            locale={{ emptyText: '暂无未签到任务' }}
          />
        )}
        {total !== null ? (
          total > PAGE_SIZE && (
            <Pagination
              className="center-pagination"
              current={page}
              pageSize={PAGE_SIZE}
              total={total}
              showSizeChanger={false}
              onChange={setPage}
            />
          )
        ) : (
          <Space className="unknown-total-pagination">
            <Button disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>上一页</Button>
            <Typography.Text>第 {page} 页</Typography.Text>
            <Button disabled={!hasMore} onClick={() => setPage((value) => value + 1)}>下一页</Button>
          </Space>
        )}
      </Card>

      <Drawer
        title="签到任务详情"
        open={detailOpen}
        loading={detailLoading}
        width={mobile ? '100%' : 680}
        onClose={() => setDetailOpen(false)}
      >
        {details && (
          <Space direction="vertical" size={16} className="full-width">
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="任务 ID">{details.task_id}</Descriptions.Item>
              <Descriptions.Item label="签到位置">{details.position_name || '—'}</Descriptions.Item>
              <Descriptions.Item label="位置 ID">{details.position_id}</Descriptions.Item>
              <Descriptions.Item label="经度">{details.base_lng}</Descriptions.Item>
              <Descriptions.Item label="纬度">{details.base_lat}</Descriptions.Item>
            </Descriptions>
            {mapConfig && <AmapTaskMap details={details} config={mapConfig} />}
          </Space>
        )}
      </Drawer>
    </div>
  );
}