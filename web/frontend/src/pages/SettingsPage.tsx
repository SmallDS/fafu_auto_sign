import { CopyOutlined, DeleteOutlined, ExperimentOutlined, SaveOutlined } from '@ant-design/icons';
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
import type {
  AmapCoordinateSystem,
  ImageMode,
  LogLevel,
  Settings,
  SettingsUpdate,
} from '../types/api';

const USER_TOKEN_INPUT_ERROR = '请输入 2_ 开头的 Token 或完整 Base64 Authorization';

export function isSupportedUserTokenInput(value?: string): boolean {
  const candidate = value?.trim() ?? '';
  if (!candidate || candidate.startsWith('2_')) return true;
  try {
    const decoded = window.atob(candidate);
    const parts = decoded.split(':');
    return (
      window.btoa(decoded) === candidate
      && parts.length === 4
      && /^\d+$/.test(parts[0])
      && /^[A-Za-z0-9]{16}$/.test(parts[1])
      && /^[0-9a-f]{32}$/i.test(parts[2])
      && parts[3].startsWith('2_')
      && parts[3].length > 2
    );
  } catch {
    return false;
  }
}

interface SettingsForm {
  user_token?: string;
  wechat_test_enabled: boolean;
  wechat_test_app_id?: string;
  wechat_test_app_secret?: string;
  wechat_test_template_id?: string;
  wechat_test_openid?: string;
  jitter: number;
  heartbeat_interval: number;
  log_level: LogLevel;
  amap_enabled: boolean;
  amap_js_key?: string;
  amap_security_js_code?: string;
  amap_source_coordinate_system: AmapCoordinateSystem;
  task_keywords?: string[];
  image_mode: ImageMode;
}

export function SettingsPage(): ReactNode {
  const { message, modal } = AntApp.useApp();
  const [form] = Form.useForm<SettingsForm>();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const imageMode = Form.useWatch('image_mode', form);
  const amapEnabled = Form.useWatch('amap_enabled', form);
  const wechatTestEnabled = Form.useWatch('wechat_test_enabled', form);

  const load = async (): Promise<void> => {
    try {
      const value = await api.getSettings();
      setSettings(value);
      form.setFieldsValue({
        jitter: value.jitter,
        heartbeat_interval: value.heartbeat_interval,
        log_level: value.log_level,
        amap_enabled: value.amap_enabled,
        amap_js_key: value.amap_js_key ?? '',
        amap_security_js_code: '',
        amap_source_coordinate_system: value.amap_source_coordinate_system,
        wechat_test_enabled: value.wechat_test_enabled,
        wechat_test_app_id: value.wechat_test_app_id ?? '',
        wechat_test_template_id: value.wechat_test_template_id ?? '',
        wechat_test_app_secret: '',
        wechat_test_openid: '',
        task_keywords: value.task_keywords,
        image_mode: value.image_mode,
        user_token: '',
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
      amap_enabled: values.amap_enabled,
      amap_js_key: values.amap_js_key?.trim() ?? '',
      amap_source_coordinate_system: values.amap_source_coordinate_system,
      wechat_test_enabled: values.wechat_test_enabled,
      wechat_test_app_id: values.wechat_test_app_id?.trim(),
      wechat_test_template_id: values.wechat_test_template_id?.trim(),
      task_keywords: (values.task_keywords ?? []).map((item) => item.trim()).filter(Boolean),
      image_mode: values.image_mode,
    };
    if (values.user_token?.trim()) payload.user_token = values.user_token.trim();
    if (values.amap_security_js_code?.trim()) {
      payload.amap_security_js_code = values.amap_security_js_code.trim();
    }
    if (values.wechat_test_app_secret?.trim()) payload.wechat_test_app_secret = values.wechat_test_app_secret.trim();
    if (values.wechat_test_openid?.trim()) payload.wechat_test_openid = values.wechat_test_openid.trim();

    setSaving(true);
    try {
      const next = await api.updateSettings(payload);
      setSettings(next);
      form.setFieldsValue({
        user_token: '',
        amap_security_js_code: '',
        wechat_test_app_secret: '',
        wechat_test_openid: '',
      });
      message.success('设置已保存，后台任务将自动加载新配置');
    } catch (nextError) {
      message.error(getErrorMessage(nextError));
    } finally {
      setSaving(false);
    }
  };

  const clearUserToken = (): void => {
    modal.confirm({
      title: '确认清除用户 Token？',
      content: '清除后后台签到会进入待配置状态。',
      okText: '清除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          const next = await api.updateSettings({ clear_user_token: true });
          setSettings(next);
          message.success('Token 已清除');
        } catch (nextError) {
          message.error(getErrorMessage(nextError));
        }
      },
    });
  };
  const clearAmapSecurityCode = (): void => {
    modal.confirm({
      title: '确认清除高德 Security JS Code？',
      content: '清除后高德地图会自动关闭，签到功能不受影响。',
      okText: '清除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          const next = await api.updateSettings({ clear_amap_security_js_code: true });
          setSettings(next);
          form.setFieldsValue({ amap_enabled: false, amap_security_js_code: '' });
          message.success('高德 Security JS Code 已清除');
        } catch (nextError) {
          message.error(getErrorMessage(nextError));
        }
      },
    });
  };

  const clearWechatSecret = (kind: 'app_secret' | 'openid'): void => {
    const label = kind === 'app_secret' ? 'AppSecret' : 'OpenID';
    modal.confirm({
      title: `确认清除 ${label}？`,
      content: '清除后微信公众号接口测试号通知会自动关闭。',
      okText: '清除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          const next = await api.updateSettings(kind === 'app_secret'
            ? { clear_wechat_test_app_secret: true }
            : { clear_wechat_test_openid: true });
          setSettings(next);
          form.setFieldValue('wechat_test_enabled', false);
          message.success(`${label} 已清除`);
        } catch (nextError) {
          message.error(getErrorMessage(nextError));
        }
      },
    });
  };

  const testWechatNotification = async (): Promise<void> => {
    try {
      const result = await api.testWechatNotification();
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
              <Form.Item
                name="user_token"
                label="用户 Token / Authorization"
                extra={settings?.has_user_token ? '已保存：' + (settings.user_token_masked ?? '******') + '；留空不修改' : '可填写 2_ 开头的 Token，或直接粘贴完整 Base64 Authorization'}
                rules={[{ validator: async (_, value?: string) => { if (!isSupportedUserTokenInput(value)) throw new Error(USER_TOKEN_INPUT_ERROR); } }]}
              >
                <Input.Password autoComplete="new-password" placeholder={settings?.has_user_token ? '留空以保留现有 Token' : '2_ Token 或完整 Base64 Authorization'} />
              </Form.Item>
              {settings?.has_user_token && (
                <Button danger type="text" icon={<DeleteOutlined />} onClick={clearUserToken}>清除 Token</Button>
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
              <Form.Item name="task_keywords" label="任务关键词" extra="可留空；空列表表示自动签到不匹配任何任务。输入关键词后按回车添加">
                <Select mode="tags" tokenSeparators={[',', '，']} placeholder="可留空，例如：晚归" open={false} />
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

            <Card title="高德地图" className="content-card">
              <Alert
                type="info"
                showIcon
                className="section-alert"
                message="地图仅用于展示和距离计算"
                description="JS Key 会提供给浏览器，请在高德控制台限制可用域名；Security JS Code 仅由后端代理使用。地图不会改变 FAFU 签到坐标。"
              />
              <Form.Item name="amap_enabled" label="高德地图" valuePropName="checked">
                <Switch checkedChildren="已启用" unCheckedChildren="已关闭" />
              </Form.Item>
              {amapEnabled && (
                <>
                  <Form.Item
                    name="amap_js_key"
                    label="Web 端 JS API Key"
                    rules={[{ required: true, whitespace: true, message: '请输入高德 JS Key' }]}
                    extra="Key 会在浏览器中使用，请为部署域名或 IP 配置白名单。"
                  >
                    <Input autoComplete="off" placeholder="高德 Web 端（JS API）Key" />
                  </Form.Item>
                  <Form.Item
                    name="amap_security_js_code"
                    label="Security JS Code"
                    rules={[{
                      required: !settings?.has_amap_security_js_code,
                      whitespace: true,
                      message: '请输入 Security JS Code',
                    }]}
                    extra={settings?.has_amap_security_js_code
                      ? '已保存：' + (settings.amap_security_js_code_masked ?? '******') + '；留空不修改'
                      : '安全密钥将保存在 SQLite，并由 FastAPI 代理注入'}
                  >
                    <Input.Password
                      autoComplete="new-password"
                      placeholder={settings?.has_amap_security_js_code
                        ? '留空以保留现有 Security JS Code'
                        : 'Security JS Code'}
                    />
                  </Form.Item>
                  <Form.Item
                    name="amap_source_coordinate_system"
                    label="FAFU 源坐标系"
                    rules={[{ required: true }]}
                    extra="只影响地图显示、地址解析和距离计算；签到仍提交 FAFU 原始坐标。"
                  >
                    <Radio.Group className="responsive-radio-group">
                      <Radio.Button value="gcj02">GCJ-02（默认）</Radio.Button>
                      <Radio.Button value="wgs84">WGS-84</Radio.Button>
                    </Radio.Group>
                  </Form.Item>
                  {settings?.has_amap_security_js_code && (
                    <Button danger type="text" icon={<DeleteOutlined />} onClick={clearAmapSecurityCode}>
                      清除 Security JS Code
                    </Button>
                  )}
                </>
              )}
            </Card>

            <Card title="日志" className="content-card">
              <Form.Item name="log_level" label="日志级别" rules={[{ required: true }]}>
                <Select options={['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'].map((value) => ({ value, label: value }))} />
              </Form.Item>
            </Card>
            <Card title="微信公众号接口测试号" className="content-card">
              <Alert
                type="info"
                showIcon
                className="section-alert"
                message="请先在微信公众平台测试号后台创建完全匹配的模板"
                description={
                  <Space direction="vertical" className="full-width" size={8}>
                    <Typography.Paragraph code className="wechat-template-preview">
                      {'{{first.DATA}}\n任务：{{keyword1.DATA}}\n状态：{{keyword2.DATA}}\n时间：{{keyword3.DATA}}\n{{remark.DATA}}'}
                    </Typography.Paragraph>
                    <Button
                      size="small"
                      icon={<CopyOutlined />}
                      onClick={() => {
                        void navigator.clipboard.writeText('{{first.DATA}}\n任务：{{keyword1.DATA}}\n状态：{{keyword2.DATA}}\n时间：{{keyword3.DATA}}\n{{remark.DATA}}');
                        message.success('模板内容已复制');
                      }}
                    >
                      复制模板内容
                    </Button>
                  </Space>
                }
              />
              <Form.Item name="wechat_test_enabled" label="测试号通知" valuePropName="checked">
                <Switch checkedChildren="已启用" unCheckedChildren="已关闭" />
              </Form.Item>
              {wechatTestEnabled && (
                <>
                  <Row gutter={[16, 0]}>
                    <Col xs={24} md={12}>
                      <Form.Item name="wechat_test_app_id" label="AppID" rules={[{ required: true, message: '请输入 AppID' }]}>
                        <Input autoComplete="off" placeholder="测试号 AppID" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} md={12}>
                      <Form.Item name="wechat_test_template_id" label="模板 ID" rules={[{ required: true, message: '请输入模板 ID' }]}>
                        <Input autoComplete="off" placeholder="模板 ID" />
                      </Form.Item>
                    </Col>
                  </Row>
                  <Form.Item
                    name="wechat_test_app_secret"
                    label="AppSecret"
                    extra={settings?.has_wechat_test_app_secret ? `已保存：${settings.wechat_test_app_secret_masked ?? '******'}；留空不修改` : '请输入测试号 AppSecret'}
                  >
                    <Input.Password autoComplete="new-password" placeholder={settings?.has_wechat_test_app_secret ? '留空以保留现有 AppSecret' : 'AppSecret'} />
                  </Form.Item>
                  <Form.Item
                    name="wechat_test_openid"
                    label="接收人 OpenID"
                    extra={settings?.has_wechat_test_openid ? `已保存：${settings.wechat_test_openid_masked ?? '******'}；留空不修改` : '请输入关注测试号用户的 OpenID'}
                  >
                    <Input.Password autoComplete="new-password" placeholder={settings?.has_wechat_test_openid ? '留空以保留现有 OpenID' : 'OpenID'} />
                  </Form.Item>
                  <Space wrap>
                    <Button
                      icon={<ExperimentOutlined />}
                      disabled={!settings?.wechat_test_enabled}
                      onClick={() => void testWechatNotification()}
                    >
                      发送测试号通知
                    </Button>
                    {settings?.has_wechat_test_app_secret && (
                      <Button danger type="text" icon={<DeleteOutlined />} onClick={() => clearWechatSecret('app_secret')}>清除 AppSecret</Button>
                    )}
                    {settings?.has_wechat_test_openid && (
                      <Button danger type="text" icon={<DeleteOutlined />} onClick={() => clearWechatSecret('openid')}>清除 OpenID</Button>
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
