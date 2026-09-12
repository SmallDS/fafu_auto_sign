import { App, Button, Card, Col, Form, Input, InputNumber, Radio, Row, Switch, Typography } from 'antd';
import { useEffect, useState, type ReactNode } from 'react';
import { api, getErrorMessage } from '../api/client';
import { PageHeading } from '../components/PageHeading';
import type { ImageRecord, Settings, SettingsUpdate } from '../types/api';

interface FormValues {
  user_token?: string;
  clear_user_token?: boolean;
  jitter: number;
  heartbeat_interval: number;
  task_keywords_text: string;
  image_mode: 'single' | 'library' | 'latest';
  selected_image_id?: string;
  worker_enabled: boolean;
  notification_enabled: boolean;
}

export function SettingsPage(): ReactNode {
  const { message } = App.useApp();
  const [form] = Form.useForm<FormValues>();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [images, setImages] = useState<ImageRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [current, library] = await Promise.all([
        api.getSettings(),
        api.listImages(1, 100, 'library'),
      ]);
      setSettings(current);
      setImages(library.items);
      form.setFieldsValue({
        jitter: current.jitter,
        heartbeat_interval: current.heartbeat_interval,
        task_keywords_text: current.task_keywords.join('\n'),
        image_mode: current.image_mode,
        selected_image_id: current.selected_image_id ?? undefined,
        worker_enabled: current.worker_enabled,
        notification_enabled: current.notification_enabled,
      });
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { void load(); }, []);

  const save = async (values: FormValues) => {
    const payload: SettingsUpdate = {
      jitter: values.jitter,
      heartbeat_interval: values.heartbeat_interval,
      task_keywords: values.task_keywords_text.split('\n').map((item) => item.trim()).filter(Boolean),
      image_mode: values.image_mode,
      selected_image_id: values.selected_image_id ?? null,
      worker_enabled: values.worker_enabled,
      notification_enabled: values.notification_enabled,
      clear_user_token: values.clear_user_token,
    };
    if (values.user_token?.trim()) payload.user_token = values.user_token.trim();
    setSaving(true);
    try {
      const saved = await api.updateSettings(payload);
      setSettings(saved);
      form.setFieldsValue({ user_token: '', clear_user_token: false });
      message.success('设置已保存');
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const tokenLabel = settings?.user_token_masked
    ? 'Token（已保存 ' + settings.user_token_masked + '）'
    : 'Token';

  return (
    <div className="page-container narrow-page">
      <PageHeading title="签到设置" description="每位用户拥有独立的 FAFU 配置、图片和运行计划。" />
      <Form form={form} layout="vertical" onFinish={save} disabled={loading}>
        <Card title="FAFU 账号" className="content-card section-card">
          <Form.Item label={tokenLabel} name="user_token">
            <Input.Password placeholder="以 2_ 开头，或粘贴完整 Base64 Authorization" autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="clear_user_token" label="清除已保存 Token" valuePropName="checked">
            <Switch checkedChildren="清除" unCheckedChildren="保留" />
          </Form.Item>
        </Card>
        <Card title="签到规则" className="content-card section-card">
          <Form.Item name="task_keywords_text" label="任务关键词">
            <Input.TextArea rows={4} placeholder="每行一个；留空表示不过滤关键词" />
          </Form.Item>
          <Row gutter={[16, 0]}>
            <Col xs={24} sm={12}>
              <Form.Item name="jitter" label="GPS 随机偏移">
                <InputNumber className="full-width" min={0} max={0.001} step={0.00001} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12}>
              <Form.Item name="heartbeat_interval" label="检查间隔（秒）">
                <InputNumber className="full-width" min={10} max={86400} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={[16, 0]}>
            <Col xs={24} sm={12}>
              <Form.Item name="worker_enabled" label="自动检查" valuePropName="checked"><Switch /></Form.Item>
            </Col>
            <Col xs={24} sm={12}>
              <Form.Item name="notification_enabled" label="微信结果通知" valuePropName="checked"><Switch /></Form.Item>
            </Col>
          </Row>
        </Card>
        <Card title="签到图片" className="content-card section-card">
          <Form.Item name="image_mode" label="图片策略">
            <Radio.Group
              className="responsive-radio-group"
              optionType="button"
              buttonStyle="solid"
              options={[
                { value: 'single', label: '固定单图' },
                { value: 'library', label: '图库随机' },
                { value: 'latest', label: '最新队列' },
              ]}
            />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(a, b) => a.image_mode !== b.image_mode}>
            {({ getFieldValue }) => getFieldValue('image_mode') === 'single' ? (
              <Form.Item name="selected_image_id" label="选择固定图片">
                <Radio.Group className="image-radio-grid">
                  {images.map((image) => (
                    <Radio.Button key={image.id} value={image.id}>{image.original_name}</Radio.Button>
                  ))}
                </Radio.Group>
              </Form.Item>
            ) : null}
          </Form.Item>
        </Card>
        <div className="sticky-save-bar">
          <Typography.Text type="secondary">保存后后台任务会自动加载新配置</Typography.Text>
          <Button type="primary" htmlType="submit" size="large" loading={saving}>保存设置</Button>
        </div>
      </Form>
    </div>
  );
}
