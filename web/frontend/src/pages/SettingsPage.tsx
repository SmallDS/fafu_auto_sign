import { DeleteOutlined, ExperimentOutlined, SaveOutlined } from '@ant-design/icons';
import {
  Alert,
  App as AntApp,
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Radio,
  Row,
  Select,
  Space,
  Switch,
  Typography,
} from 'antd';
import { useEffect, useState, type ReactNode } from 'react';
import { api, getErrorMessage } from '../api/client';
import { AsyncState } from '../components/AsyncState';
import { PageHeading } from '../components/PageHeading';
import type { ImageMode, LogLevel, Settings, SettingsUpdate } from '../types/api';

interface SettingsForm {
  user_token?: string;
  serverchan_key?: string;
  jitter: number;
  heartbeat_interval: number;
  log_level: LogLevel;
  notification_enabled: boolean;
  task_keywords: string[];
  image_mode: ImageMode;
}

export function SettingsPage(): ReactNode {
  const { message, modal } = AntApp.useApp();
  const [form] = Form.useForm<SettingsForm>();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const notificationsEnabled = Form.useWatch('notification_enabled', form);
  const imageMode = Form.useWatch('image_mode', form);

  const load = async (): Promise<void> => {
    try {
      const value = await api.getSettings();
      setSettings(value);
      form.setFieldsValue({
        jitter: value.jitter,
        heartbeat_interval: value.heartbeat_interval,
        log_level: value.log_level,
        notification_enabled: value.notification_enabled,
        task_keywords: value.task_keywords,
        image_mode: value.image_mode,
        user_token: '',
        serverchan_key: '',
      });
      setError(null);
    } catch (nextError) {
      setError(nextError);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const save = async (values: SettingsForm): Promise<void> => {
    const payload: SettingsUpdate = {
      jitter: values.jitter,
      heartbeat_interval: values.heartbeat_interval,
      log_level: values.log_level,
      notification_enabled: values.notification_enabled,
      task_keywords: values.task_keywords.map((item) => item.trim()).filter(Boolean),
      image_mode: values.image_mode,
    };
    if (values.user_token?.trim()) payload.user_token = values.user_token.trim();
    if (values.serverchan_key?.trim()) payload.serverchan_key = values.serverchan_key.trim();

    setSaving(true);
    try {
      const next = await api.updateSettings(payload);
      setSettings(next);
      form.setFieldsValue({ user_token: '', serverchan_key: '' });
      message.success('设置已保存，后台任务将自动加载新配置');
    } catch (nextError) {
      message.error(getErrorMessage(nextError));
    } finally {
      setSaving(false);
    }
  };

  const clearSecret = (kind: 'user_token' | 'serverchan_key'): void => {
    const isToken = kind === 'user_token';
    modal.confirm({
      title: `确认清除${isToken ? '用户 Token' : '通知 SendKey'}？`,
      content: isToken ? '清除后后台签到会进入待配置状态。' : '清除后将无法发送微信通知。',
      okText: '清除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          const next = await api.updateSettings(
            isToken
              ? { clear_user_token: true }
              : { clear_serverchan_key: true, notification_enabled: false },
          );
          setSettings(next);
          if (!isToken) form.setFieldValue('notification_enabled', false);
          message.success('密钥已清除');
        } catch (nextError) {
          message.error(getErrorMessage(nextError));
        }
      },
    });
  };

  const testNotification = async (): Promise<void> => {
    try {
      const result = await api.testNotification();
      message.success(result.message);
    } catch (nextError) {
      message.error(getErrorMessage(nextError));
    }
  };

  return (
    <div className="page-container narrow-page">
      <PageHeading title="系统设置" description="配置签到参数。密码框留空将保留数据库中的现有值。" />
      <AsyncState loading={loading} error={error}>
        <Form form={form} layout="vertical" requiredMark="optional" onFinish={(values) => void save(values)}>
          <Space direction="vertical" size={16} className="full-width">
            <Card title="账号凭据" className="content-card">
              <Alert type="warning" showIcon message="敏感信息以明文保存在 SQLite 中，请只在可信局域网使用管理台。" className="section-alert" />
              <Form.Item
                name="user_token"
                label="用户 Token"
                extra={settings?.has_user_token ? `已保存：${settings.user_token_masked ?? '******'}；留空不修改` : '从数字 FAFU App 请求中获取，必须以 2_ 开头'}
                rules={[{ validator: async (_, value?: string) => { if (value?.trim() && !value.trim().startsWith('2_')) throw new Error('Token 必须以 2_ 开头'); } }]}
              >
                <Input.Password autoComplete="new-password" placeholder={settings?.has_user_token ? '留空以保留现有 Token' : '请输入 2_ 开头的 Token'} />
              </Form.Item>
              {settings?.has_user_token && (
                <Button danger type="text" icon={<DeleteOutlined />} onClick={() => clearSecret('user_token')}>清除 Token</Button>
              )}
            </Card>

            <Card title="签到策略" className="content-card">
              <Row gutter={[16, 0]}>
                <Col xs={24} md={12}>
                  <Form.Item name="jitter" label="GPS 随机偏移" rules={[{ required: true, message: '请输入偏移量' }]} extra="建议 0.00005，约 5 米">
                    <InputNumber min={0} max={0.001} step={0.00001} precision={5} className="full-width" />
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <Form.Item name="heartbeat_interval" label="检查间隔（秒）" rules={[{ required: true, message: '请输入检查间隔' }]} extra="建议至少 60 秒">
                    <InputNumber min={30} max={86400} step={30} className="full-width" />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item name="task_keywords" label="任务关键词" rules={[{ required: true, message: '至少添加一个关键词' }]} extra="输入关键词后按回车添加">
                <Select mode="tags" tokenSeparators={[',', '，']} placeholder="例如：晚归" open={false} />
              </Form.Item>
              <Form.Item name="image_mode" label="图片策略" rules={[{ required: true }]}>
                <Radio.Group className="responsive-radio-group">
                  <Radio.Button value="single">固定图片</Radio.Button>
                  <Radio.Button value="library">图库随机</Radio.Button>
                  <Radio.Button value="latest">最新队列</Radio.Button>
                </Radio.Group>
              </Form.Item>
              {imageMode === 'single' && (
                <Alert
                  type={settings?.selected_image_id ? 'info' : 'warning'}
                  showIcon
                  message={settings?.selected_image_id ? '已选择固定图片' : '尚未选择固定图片'}
                  description="固定图片需要在“图片”页选择。"
                  action={<Button href="/images" size="small">管理图片</Button>}
                />
              )}
            </Card>

            <Card title="日志与通知" className="content-card">
              <Form.Item name="log_level" label="日志级别" rules={[{ required: true }]}>
                <Select options={['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'].map((value) => ({ value, label: value }))} />
              </Form.Item>
              <Form.Item name="notification_enabled" label="Server酱通知" valuePropName="checked">
                <Switch checkedChildren="已启用" unCheckedChildren="已关闭" />
              </Form.Item>
              {notificationsEnabled && (
                <>
                  <Form.Item
                    name="serverchan_key"
                    label="SendKey"
                    extra={settings?.has_serverchan_key ? `已保存：${settings.serverchan_key_masked ?? '******'}；留空不修改` : '请输入 Server酱 SendKey'}
                  >
                    <Input.Password autoComplete="new-password" placeholder={settings?.has_serverchan_key ? '留空以保留现有 SendKey' : 'SCT...'} />
                  </Form.Item>
                  <Space wrap>
                    <Button icon={<ExperimentOutlined />} disabled={!settings?.has_serverchan_key} onClick={() => void testNotification()}>发送测试通知</Button>
                    {settings?.has_serverchan_key && (
                      <Button danger type="text" icon={<DeleteOutlined />} onClick={() => clearSecret('serverchan_key')}>清除 SendKey</Button>
                    )}
                  </Space>
                </>
              )}
            </Card>

            <div className="sticky-save-bar">
              <Typography.Text type="secondary">配置版本 {settings?.version ?? '—'}</Typography.Text>
              <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={saving}>保存设置</Button>
            </div>
          </Space>
        </Form>
      </AsyncState>
    </div>
  );
}
