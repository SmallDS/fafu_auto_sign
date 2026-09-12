import { App, Button, Card, Form, Input, Select, Switch } from 'antd';
import { useEffect, useState, type ReactNode } from 'react';
import { api, getErrorMessage } from '../api/client';
import { PageHeading } from '../components/PageHeading';
import type { SystemSettingsUpdate } from '../types/api';

export function AdminSystemPage(): ReactNode {
  const { message, modal } = App.useApp();
  const [form] = Form.useForm<SystemSettingsUpdate>();
  const [loading, setLoading] = useState(true);
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
  }, []);

  const save = async (values: SystemSettingsUpdate) => {
    try {
      await api.updateAdminSystem(values);
      form.setFieldsValue({ wechat_app_secret: '', amap_security_js_code: '' });
      message.success('系统设置已保存');
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };
  const synchronize = () => {
    modal.confirm({
      title: '同步公众号菜单',
      content: '该操作会覆盖测试号当前的自定义菜单。',
      onOk: async () => {
        await api.syncMenu();
        message.success('公众号菜单已同步');
      },
    });
  };

  return (
    <>
      <PageHeading title="系统设置" description="配置测试号、公众号菜单、高德地图和系统日志。" />
      <Form form={form} layout="vertical" onFinish={save} disabled={loading}>
        <Card title="微信公众号测试号" className="section-card">
          <Form.Item name="wechat_enabled" label="启用测试号" valuePropName="checked"><Switch /></Form.Item>
          <Form.Item name="wechat_app_id" label="AppID"><Input /></Form.Item>
          <Form.Item name="wechat_app_secret" label="AppSecret">
            <Input.Password placeholder="留空保留已保存值" autoComplete="new-password" />
          </Form.Item>
          <Form.Item name="wechat_template_id" label="模板 ID"><Input /></Form.Item>
          <Form.Item name="public_base_url" label="公网 HTTPS 地址"><Input /></Form.Item>
          <Form.Item name="menu_name" label="菜单名称"><Input maxLength={32} /></Form.Item>
          <Button onClick={synchronize}>同步公众号菜单</Button>
        </Card>
        <Card title="高德地图" className="section-card">
          <Form.Item name="amap_enabled" label="启用地图" valuePropName="checked"><Switch /></Form.Item>
          <Form.Item name="amap_js_key" label="JS Key"><Input /></Form.Item>
          <Form.Item name="amap_security_js_code" label="Security JS Code">
            <Input.Password placeholder="留空保留已保存值" autoComplete="new-password" />
          </Form.Item>
        </Card>
        <Card title="日志" className="section-card">
          <Form.Item name="log_level" label="级别">
            <Select options={['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'].map((value) => ({ value, label: value }))} />
          </Form.Item>
        </Card>
        <Button type="primary" htmlType="submit">保存系统设置</Button>
      </Form>
    </>
  );
}