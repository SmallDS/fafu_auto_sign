import { EyeOutlined, LoginOutlined, ReloadOutlined } from '@ant-design/icons';
import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Grid,
  InputNumber,
  List,
  Pagination,
  Radio,
  Row,

  Skeleton,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs from 'dayjs';
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { api, getErrorMessage } from '../api/client';
import { AmapTaskMap, type Coordinate } from '../components/AmapTaskMap';
import { PageHeading } from '../components/PageHeading';
import { PageSkeleton } from '../components/PageSkeleton';
import type { ManualSignOptions, MapConfig, SignTask, SignTaskDetails } from '../types/api';

const PAGE_SIZE = 20;
const DISABLED_MAP_CONFIG: MapConfig = {
  enabled: false,
  js_key: null,
  jitter: 0,
  service_host: '/_AMapService',
};

type DetailIntent = 'view' | 'sign';
type LocationMode = ManualSignOptions['location_mode'];

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
  const [detailIntent, setDetailIntent] = useState<DetailIntent>('view');
  const [submittingId, setSubmittingId] = useState<string | null>(null);
  const [locationMode, setLocationMode] = useState<LocationMode>('rule_jitter');
  const [manualJitter, setManualJitter] = useState<number | null>(0);
  const [manualLng, setManualLng] = useState<number | null>(null);
  const [manualLat, setManualLat] = useState<number | null>(null);

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

  const resetOneTimeOptions = (): void => {
    setLocationMode('rule_jitter');
    setManualJitter(0);
    setManualLng(null);
    setManualLat(null);
  };

  const openDetails = async (task: SignTask, intent: DetailIntent): Promise<void> => {
    setDetailOpen(true);
    setDetailIntent(intent);
    setDetails(null);
    setMapConfig(null);
    resetOneTimeOptions();
    setDetailLoading(true);
    try {
      const [nextDetails, nextMapConfig] = await Promise.all([
        api.getSignTask(task.id),
        api.getMapConfig().catch(() => DISABLED_MAP_CONFIG),
      ]);
      setDetails(nextDetails);
      setMapConfig(nextMapConfig);
      setManualJitter(nextMapConfig.jitter);
    } catch (error) {
      message.error(getErrorMessage(error));
      setDetailOpen(false);
    } finally {
      setDetailLoading(false);
    }
  };

  const closeDetails = (): void => {
    if (submittingId) return;
    setDetailOpen(false);
    setDetails(null);
    setMapConfig(null);
    resetOneTimeOptions();
  };

  const selectCoordinate = useCallback((coordinate: Coordinate): void => {
    setManualLng(Number(coordinate[0].toFixed(6)));
    setManualLat(Number(coordinate[1].toFixed(6)));
  }, []);

  const submit = (): void => {
    if (!details) return;
    let options: ManualSignOptions;
    let summary: string;
    if (locationMode === 'manual_point') {
      if (manualLng === null || manualLat === null) {
        message.warning('请先在地图上选点，或填写完整经纬度');
        return;
      }
      options = {
        location_mode: 'manual_point',
        longitude: manualLng,
        latitude: manualLat,
      };
      summary = `使用手动选点 ${manualLng.toFixed(6)}, ${manualLat.toFixed(6)}`;
    } else {
      if (manualJitter === null || manualJitter < 0 || manualJitter > 0.001) {
        message.warning('本次 GPS 偏移必须在 0 到 0.001 之间');
        return;
      }
      options = { location_mode: 'rule_jitter', jitter: manualJitter };
      summary = manualJitter > 0 ? `使用任务位置并随机偏移 ±${manualJitter}` : '使用任务原始位置，不添加偏移';
    }

    modal.confirm({
      title: `确认提交“${details.position_name || `任务 ${details.task_id}`}”吗？`,
      content: `${summary}。这些参数只对本次签到生效。`,
      okText: '确认签到',
      cancelText: '取消',
      onOk: async () => {
        const id = String(details.task_id);
        setSubmittingId(id);
        try {
          const result = await api.submitSignTask(id, page, PAGE_SIZE, options);
          if (result.result === 'success') {
            message.success('签到提交成功');
            setDetailOpen(false);
            setDetails(null);
            resetOneTimeOptions();
            await load();
          } else {
            message.error(result.summary || '签到提交失败');
          }
        } catch (error) {
          message.error(getErrorMessage(error));
        } finally {
          setSubmittingId(null);
        }
      },
    });
  };

  const actions = (task: SignTask): ReactNode => (
    <Space wrap>
      <Button icon={<EyeOutlined />} onClick={() => void openDetails(task, 'view')}>详情</Button>
      <Button
        type="primary"
        icon={<LoginOutlined />}
        disabled={!isActive(task)}
        loading={submittingId === task.id}
        onClick={() => void openDetails(task, 'sign')}
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

  const selectedCoordinate: Coordinate | null = manualLng !== null && manualLat !== null
    ? [manualLng, manualLat]
    : null;

  if (loading && tasks.length === 0) return <div className="page-container"><PageSkeleton variant="list" /></div>;

  return (
    <div className="page-container">
      <PageHeading
        title="签到任务"
        description="浏览未签到任务，并为每次手动签到单独设置位置参数"
        extra={<Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>刷新</Button>}
      />
      <Card className="content-card sign-task-card">
        {mobile ? (
          <List
            dataSource={tasks}
            locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无未签到任务" /> }}
            renderItem={(task) => (
              <List.Item className="sign-task-mobile-item">
                <Space orientation="vertical" size={10} className="full-width">
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
            loading={loading && tasks.length > 0}
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
        ) : !loading && (
          <Space className="unknown-total-pagination">
            <Button disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>上一页</Button>
            <Typography.Text>第 {page} 页</Typography.Text>
            <Button disabled={!hasMore} onClick={() => setPage((value) => value + 1)}>下一页</Button>
          </Space>
        )}
      </Card>

      <Drawer
        title={detailIntent === 'sign' ? '手动签到' : '签到任务详情'}
        open={detailOpen}
        width={mobile ? '100%' : 720}
        onClose={closeDetails}
        closable={!submittingId}
        maskClosable={!submittingId}
      >
        {detailLoading ? (
          <div aria-label="签到详情加载中" aria-busy="true"><Skeleton active paragraph={{ rows: 9 }} /></div>
        ) : details && mapConfig ? (
          <Space orientation="vertical" size={16} className="full-width">
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="任务 ID">{details.task_id}</Descriptions.Item>
              <Descriptions.Item label="签到位置">{details.position_name || '—'}</Descriptions.Item>
              <Descriptions.Item label="位置 ID">{details.position_id}</Descriptions.Item>
              <Descriptions.Item label="经度">{details.base_lng}</Descriptions.Item>
              <Descriptions.Item label="纬度">{details.base_lat}</Descriptions.Item>
            </Descriptions>

            {detailIntent === 'sign' && (
              <Card title="本次签到参数" size="small" className="manual-sign-options">
                <Radio.Group
                  className="responsive-radio-group"
                  optionType="button"
                  buttonStyle="solid"
                  value={locationMode}
                  onChange={(event) => setLocationMode(event.target.value as LocationMode)}
                  options={[
                    { value: 'rule_jitter', label: '任务位置与偏移' },
                    { value: 'manual_point', label: '手动选点' },
                  ]}
                />
                {locationMode === 'rule_jitter' ? (
                  <div className="manual-sign-fields">
                    <Typography.Text strong>本次 GPS 随机偏移</Typography.Text>
                    <InputNumber
                      aria-label="本次 GPS 随机偏移"
                      className="full-width"
                      min={0}
                      max={0.001}
                      step={0.00001}
                      value={manualJitter}
                      onChange={setManualJitter}
                    />
                    <Typography.Text type="secondary">默认读取规则设置，修改后仅本次生效。</Typography.Text>
                  </div>
                ) : (
                  <div className="manual-sign-fields">
                    <Typography.Text strong>GCJ-02 手动坐标</Typography.Text>
                    <Row gutter={[12, 12]}>
                      <Col xs={24} sm={12}>
                        <InputNumber
                          aria-label="手动经度"
                          className="full-width"
                          min={-180}
                          max={180}
                          precision={6}
                          placeholder="经度"
                          value={manualLng}
                          onChange={setManualLng}
                        />
                      </Col>
                      <Col xs={24} sm={12}>
                        <InputNumber
                          aria-label="手动纬度"
                          className="full-width"
                          min={-90}
                          max={90}
                          precision={6}
                          placeholder="纬度"
                          value={manualLat}
                          onChange={setManualLat}
                        />
                      </Col>
                    </Row>
                    <Typography.Text type="secondary">点击下方地图选点，或直接填写经纬度。</Typography.Text>
                  </div>
                )}
              </Card>
            )}

            <AmapTaskMap
              details={details}
              config={mapConfig}
              jitterOverride={detailIntent === 'sign' && locationMode === 'rule_jitter' ? manualJitter ?? 0 : 0}
              selectionEnabled={detailIntent === 'sign' && locationMode === 'manual_point'}
              onSelectCoordinate={selectCoordinate}
            />

            {detailIntent === 'sign' && locationMode === 'manual_point' && (
              selectedCoordinate ? (
                <Alert type="success" showIcon title="已选择本次签到点" description={`${manualLng?.toFixed(6)}, ${manualLat?.toFixed(6)}`} />
              ) : (
                <Alert type="info" showIcon title="尚未选择位置" description="请点击地图或填写完整的 GCJ-02 经纬度。" />
              )
            )}

            {detailIntent === 'sign' && (
              <div className="manual-sign-footer">
                <Button onClick={closeDetails} disabled={Boolean(submittingId)}>取消</Button>
                <Button type="primary" icon={<LoginOutlined />} loading={Boolean(submittingId)} onClick={submit}>
                  提交本次签到
                </Button>
              </div>
            )}
          </Space>
        ) : null}
      </Drawer>
    </div>
  );
}
