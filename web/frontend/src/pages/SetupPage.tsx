import { Alert, App, Button, Card, Form, Input, Select, Steps, Switch, Typography } from 'antd';
import { QRCodeSVG } from 'qrcode.react';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { api, getErrorMessage } from '../api/client';
import { useAuth } from '../context/AuthContext';
import type { BootstrapSystemInput, Pairing } from '../types/api';

const adminPairingStatus: Record<string, string> = {
  pending: '等待管理员扫码',
  scanning: '已扫码，正在完成微信授权',
  profile_pending: '已扫码，请在手机上完善昵称和头像',
  ready: '绑定完成，正在登录…',
  expired: '二维码已过期，请刷新',
  consumed: '二维码已经使用',
};

export function SetupPage(): ReactNode {
  const { message } = App.useApp();
  const { bootstrap, refresh, acceptUser } = useAuth();
  const [saving, setSaving] = useState(false);
  const [pairing, setPairing] = useState<Pairing | null>(null);
  const [pairingError, setPairingError] = useState<string | null>(null);
  const [form] = Form.useForm<BootstrapSystemInput>();
  const configured = !(bootstrap?.requires_system_configuration ?? true);
  const expectedOrigin = useMemo(() => {
    if (!pairing?.auth_url) return null;
    try {
      return new URL(pairing.auth_url).origin;
    } catch {
      return null;
    }
  }, [pairing?.auth_url]);
  const originMismatch = Boolean(expectedOrigin && expectedOrigin !== window.location.origin);

  const createPairing = async () => {
    try {
      setPairingError(null);
      setPairing(await api.createAdminPairing());
    } catch (error) {
      setPairingError(getErrorMessage(error));
    }
  };

  useEffect(() => {
    if (configured && !pairing) void createPairing();
  }, [configured]);

  useEffect(() => {
    if (!pairing || originMismatch || ['consumed', 'expired'].includes(pairing.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const current = await api.getAdminPairing(pairing.id);
        setPairing((previous) => ({ ...current, auth_url: current.auth_url ?? previous?.auth_url ?? null }));
        if (current.status === 'ready') {
          const user = await api.exchangeAdminPairing(current.id);
          acceptUser(user);
          window.location.assign('/admin');
        }
      } catch (error) {
        setPairingError(getErrorMessage(error));
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [acceptUser, originMismatch, pairing?.id, pairing?.status]);

  const submit = async (values: BootstrapSystemInput) => {
    setSaving(true);
    try {
      await api.configureBootstrap(values);
      message.success('测试号配置验证成功');
      await refresh();
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <main className="auth-page">
      <Card className="auth-card">
        <Typography.Title level={2}>初始化 FAFU 签到</Typography.Title>
        <Steps
          current={configured ? 1 : 0}
          items={[{ title: '测试号设置' }, { title: '管理员扫码' }, { title: '完成' }]}
        />
        {!configured ? (
          <Form
            form={form}
            layout="vertical"
            initialValues={{ menu_name: '签到管理', log_level: 'INFO', amap_enabled: false }}
            onFinish={submit}
            className="setup-form"
          >
            <Form.Item name="wechat_app_id" label="测试号 AppID" rules={[{ required: true }]}>
              <Input autoComplete="off" />
            </Form.Item>
            <Form.Item name="wechat_app_secret" label="AppSecret" rules={[{ required: true }]}>
              <Input.Password autoComplete="new-password" />
            </Form.Item>
            <Form.Item name="wechat_template_id" label="模板 ID" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item
              name="public_base_url"
              label="公网 HTTPS 地址"
              extra="这里只填写网站来源，例如 https://sign.example.com；测试号后台的网页授权域名只填写 sign.example.com。"
              rules={[
                { required: true },
                { pattern: /^https:\/\/[^/:?#]+\/?$/, message: '请输入不含路径和端口的 HTTPS 域名' },
              ]}
            >
              <Input placeholder="https://sign.example.com" />
            </Form.Item>
            <Form.Item
              name="menu_name"
              label="公众号菜单名称"
              extra="一级菜单最多 4 个汉字或 8 个英文字符。"
              rules={[
                { required: true },
                {
                  validator: (_, value: string) => {
                    const length = Array.from(value ?? '').reduce((total, character) => total + (/^[\x00-\x7F]$/.test(character) ? 1 : 2), 0);
                    return length <= 8 ? Promise.resolve() : Promise.reject(new Error('一级菜单最多 4 个汉字或 8 个英文字符'));
                  },
                },
              ]}
            >
              <Input maxLength={8} />
            </Form.Item>
            <Form.Item name="log_level" label="系统日志级别">
              <Select options={['DEBUG', 'INFO', 'WARNING', 'ERROR'].map((value) => ({ value, label: value }))} />
            </Form.Item>
            <Form.Item name="amap_enabled" label="启用高德地图" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item noStyle shouldUpdate={(a, b) => a.amap_enabled !== b.amap_enabled}>
              {({ getFieldValue }) => getFieldValue('amap_enabled') ? (
                <>
                  <Form.Item name="amap_js_key" label="高德 JS Key" rules={[{ required: true }]}><Input /></Form.Item>
                  <Form.Item name="amap_security_js_code" label="Security JS Code" rules={[{ required: true }]}>
                    <Input.Password />
                  </Form.Item>
                </>
              ) : null}
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={saving} block>验证并保存</Button>
          </Form>
        ) : (
          <section className="qr-stage">
            <Typography.Title level={4}>管理员使用微信扫码</Typography.Title>
            <Typography.Paragraph type="secondary">
              扫码后将获取微信昵称与头像；资料缺失时会在手机上提示补充。
            </Typography.Paragraph>
            {originMismatch && expectedOrigin ? (
              <Alert
                type="warning"
                showIcon
                message="请从公网 HTTPS 地址继续初始化"
                description="当前页面无法保存 Secure 登录 Cookie。"
                action={<Button href={`${expectedOrigin}/setup`}>打开正确地址</Button>}
              />
            ) : null}
            {!originMismatch && pairing?.auth_url && pairing.status === 'pending' ? (
              <QRCodeSVG value={pairing.auth_url} size={220} level="M" />
            ) : null}
            <Typography.Text type="secondary">
              {adminPairingStatus[pairing?.status ?? 'pending'] ?? '正在确认绑定状态'}
            </Typography.Text>
            {pairingError ? <Alert type="error" showIcon message={pairingError} /> : null}
            <Button onClick={() => void createPairing()}>刷新二维码</Button>
          </section>
        )}
      </Card>
    </main>
  );
}