import { Alert, App, Button, Card, Form, Input, Select, Space, Switch, Typography } from 'antd';
import { useEffect, useState, type ReactNode } from 'react';
import { api, getErrorMessage } from '../api/client';
import { PageHeading } from '../components/PageHeading';
import type { SystemSettingsUpdate } from '../types/api';

function menuNameLength(value: string): number {
  return Array.from(value).reduce(
    (total, character) => total + (/^[\x00-\x7F]$/.test(character) ? 1 : 2),
    0,
  );
}

export function AdminSystemPage(): ReactNode {
  const { message, modal } = App.useApp();
  const [form] = Form.useForm<SystemSettingsUpdate>();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [menuError, setMenuError] = useState<string | null>(null);

  useEffect(() => {
    void api.getAdminSystem().then((value) => {
      form.setFieldsValue({
        public_base_url: value.public_base_url ?? '',
        menu_name: value.menu_name,
        wechat_app_id: value.wechat_app_id ?? '',
        wechat_template_id: value.wechat_template_id ?? '',
        wechat_enabled: value.wechat_enabled,
        amap_enabled: value.amap_enabled,
        amap_js_key: value.amap_js_key ?? '',
        log_level: value.log_level,
      });
    }).catch((error) => message.error(getErrorMessage(error))).finally(() => setLoading(false));
  }, [form, message]);

  const save = async (values: SystemSettingsUpdate) => {
    setSaving(true);
    try {
      await api.updateAdminSystem(values);
      form.setFieldsValue({ wechat_app_secret: '', amap_security_js_code: '' });
      message.success('系统设置已保存');
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const synchronize = () => {
    setMenuError(null);
    modal.confirm({
      title: '同步公众号菜单',
      content: '将先保存当前表单配置，再覆盖测试号现有自定义菜单。',
      okText: '保存并同步',
      cancelText: '取消',
      onOk: async () => {
        try {
          const values = await form.validateFields();
          await api.updateAdminSystem(values);
          form.setFieldsValue({ wechat_app_secret: '', amap_security_js_code: '' });
          const result = await api.syncMenu();
          setMenuError(null);
          message.success(result.message || '系统设置已保存，公众号菜单已同步');
        } catch (error) {
          const detail = getErrorMessage(error);
          setMenuError(detail);
          message.error(detail);
        }
      },
    });
  };

  return (
    <div className="page-container narrow-page">
      <PageHeading title="系统设置" description="配置测试号、公众号菜单、高德地图和系统日志。" />
      {menuError ? (
        <Alert className="section-alert" type="error" showIcon closable title="公众号菜单同步失败" description={menuError} onClose={() => setMenuError(null)} />
      ) : null}
      <Form form={form} layout="vertical" onFinish={save} disabled={loading}>
        <Card title="微信公众号测试号" className="content-card section-card">
          <Form.Item name="wechat_enabled" label="启用测试号" valuePropName="checked"><Switch /></Form.Item>
          <Form.Item name="wechat_app_id" label="AppID"><Input /></Form.Item>
          <Form.Item name="wechat_app_secret" label="AppSecret">
            <Input.Password placeholder="留空保留已保存值" autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="wechat_template_id" label="模板 ID"><Input /></Form.Item>
          <Form.Item
            name="public_base_url"
            label="公网 HTTPS 地址"
            extra="填写 https://sign.example.com；测试号后台网页授权域名只填写 sign.example.com。"
            rules={[{ pattern: /^https:\/\/[^/:?#]+\/?$/, message: '请输入不含路径和端口的 HTTPS 域名' }]}
          >
            <Input placeholder="https://sign.example.com" />
          </Form.Item>
          <Form.Item
            name="menu_name"
            label="菜单名称"
            extra="一级菜单最多 4 个汉字或 8 个英文字符。"
            rules={[
              { required: true, message: '请输入菜单名称' },
              {
                validator: (_, value: string) => menuNameLength(value ?? '') <= 8
                  ? Promise.resolve()
                  : Promise.reject(new Error('一级菜单最多 4 个汉字或 8 个英文字符')),
              },
            ]}
          >
            <Input maxLength={8} />
          </Form.Item>
          <Button className="mobile-full-button" onClick={synchronize}>同步公众号菜单</Button>
        </Card>
        <Card title="高德地图" className="content-card section-card">
          <Form.Item name="amap_enabled" label="启用地图" valuePropName="checked"><Switch /></Form.Item>
          <Form.Item name="amap_js_key" label="JS Key"><Input /></Form.Item>
          <Form.Item name="amap_security_js_code" label="Security JS Code">
            <Input.Password placeholder="留空保留已保存值" autoComplete="new-password" />
          </Form.Item>
        </Card>
        <Card title="日志" className="content-card section-card">
          <Form.Item name="log_level" label="级别">
            <Select options={['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'].map((value) => ({ value, label: value }))} />
          </Form.Item>
        </Card>
        <div className="sticky-save-bar">
          <Typography.Text type="secondary">秘密字段留空时保留原值</Typography.Text>
          <Space><Button type="primary" htmlType="submit" size="large" loading={saving}>保存系统设置</Button></Space>
        </div>
      </Form>
    </div>
  );
}
