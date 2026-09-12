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
      content: '将先保存当前表单配置，再覆盖测试号现有自定义菜单。',
      okText: '保存并同步',
      onOk: async () => {
        try {
          const values = await form.validateFields();
          await api.updateAdminSystem(values);
          form.setFieldsValue({ wechat_app_secret: '', amap_security_js_code: '' });
          await api.syncMenu();
          message.success('系统设置已保存，公众号菜单已同步');
        } catch (error) {
          message.error(getErrorMessage(error));
          throw error;
        }
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
                validator: (_, value: string) => {
                  const length = Array.from(value ?? '').reduce((total, character) => total + (/^[\x00-\x7F]$/.test(character) ? 1 : 2), 0);
                  return length <= 8 ? Promise.resolve() : Promise.reject(new Error('一级菜单最多 4 个汉字或 8 个英文字符'));
                },
              },
            ]}
          >
            <Input maxLength={8} />
          </Form.Item>
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