import { DesktopOutlined, MobileOutlined } from '@ant-design/icons';
import { Alert, App, Avatar, Button, Card, Form, Input, List, Space, Switch, Tag, Typography } from 'antd';
import dayjs from 'dayjs';
import { useEffect, useState, type ReactNode } from 'react';
import { api, getErrorMessage } from '../api/client';
import { PageHeading } from '../components/PageHeading';
import { PageSkeleton } from '../components/PageSkeleton';
import { useAuth } from '../context/AuthContext';
import type { Settings, UserSession } from '../types/api';

interface TokenFormValues {
  user_token: string;
}

function sessionClient(userAgent: string): string {
  if (/MicroMessenger/i.test(userAgent)) return '微信';
  if (/Edg\//i.test(userAgent)) return 'Edge';
  if (/Chrome\//i.test(userAgent)) return 'Chrome';
  if (/Firefox\//i.test(userAgent)) return 'Firefox';
  if (/Safari\//i.test(userAgent)) return 'Safari';
  return '浏览器';
}

function sessionPlatform(userAgent: string, deviceType: string): string {
  if (/iPhone|iPad|iPod/i.test(userAgent)) return 'iOS';
  if (/Android/i.test(userAgent)) return 'Android';
  if (/Windows/i.test(userAgent)) return 'Windows';
  if (/Macintosh|Mac OS X/i.test(userAgent)) return 'macOS';
  if (/Linux/i.test(userAgent)) return 'Linux';
  return deviceType === 'mobile' ? '手机' : '电脑';
}

function sessionName(session: UserSession): string {
  return `${sessionPlatform(session.user_agent, session.device_type)} · ${sessionClient(session.user_agent)}`;
}

export function ProfilePage(): ReactNode {
  const { message, modal } = App.useApp();
  const { user, clearUser } = useAuth();
  const [tokenForm] = Form.useForm<TokenFormValues>();
  const [sessions, setSessions] = useState<UserSession[]>([]);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [tokenSaving, setTokenSaving] = useState(false);
  const [workerSaving, setWorkerSaving] = useState(false);
  const [notificationSaving, setNotificationSaving] = useState(false);

  const load = async (): Promise<void> => {
    setLoading(true);
    setLoadError(null);
    try {
      const [nextSessions, nextSettings] = await Promise.all([
        api.getSessions(),
        api.getSettings(),
      ]);
      setSessions(nextSessions);
      setSettings(nextSettings);
    } catch (error) {
      const detail = getErrorMessage(error);
      setLoadError(detail);
      message.error(detail);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);

  const revoke = async (id: string) => {
    try {
      await api.revokeSession(id);
      const current = sessions.find((item) => item.id === id)?.current;
      if (current) {
        clearUser();
        window.location.assign('/login');
      } else {
        setSessions(await api.getSessions());
      }
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  const saveToken = async ({ user_token }: TokenFormValues): Promise<void> => {
    setTokenSaving(true);
    try {
      const saved = await api.updateSettings({ user_token: user_token.trim() });
      setSettings(saved);
      tokenForm.resetFields();
      message.success('FAFU Token 已保存');
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setTokenSaving(false);
    }
  };

  const clearToken = (): void => {
    modal.confirm({
      title: '确认清除 FAFU Token？',
      content: '清除后会同时暂停自动检查，重新填写 Token 后才能恢复。',
      okText: '确认清除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      async onOk() {
        try {
          const saved = await api.updateSettings({ clear_user_token: true });
          setSettings(saved);
          tokenForm.resetFields();
          message.success('FAFU Token 已清除');
        } catch (error) {
          message.error(getErrorMessage(error));
        }
      },
    });
  };

  const toggleWorker = async (enabled: boolean): Promise<void> => {
    setWorkerSaving(true);
    try {
      const result = enabled ? await api.resumeWorker() : await api.pauseWorker();
      setSettings(await api.getSettings());
      message.success(result.message);
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setWorkerSaving(false);
    }
  };

  const toggleNotification = async (enabled: boolean): Promise<void> => {
    setNotificationSaving(true);
    try {
      const saved = await api.updateSettings({ notification_enabled: enabled });
      setSettings(saved);
      message.success(enabled ? '微信结果通知已开启' : '微信结果通知已关闭');
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setNotificationSaving(false);
    }
  };

  const logout = async () => {
    try {
      await api.logout();
      clearUser();
      window.location.assign('/login');
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  if (loading) {
    return <div className="page-container narrow-page"><PageSkeleton variant="profile" /></div>;
  }

  return (
    <div className="page-container narrow-page">
      <PageHeading title="个人中心" description="管理微信身份、FAFU 账号、运行偏好与登录设备。" />
      {loadError && <Alert className="section-alert" type="error" showIcon message="个人设置加载失败" description={loadError} action={<Button onClick={() => void load()}>重试</Button>} />}
      <Card className="content-card section-card">
        <div className="profile-summary">
          <Space className="profile-identity">
            <Avatar size={56} src={user?.avatar_url}>{user?.nickname?.slice(0, 1)}</Avatar>
            <div className="profile-copy">
              <Typography.Title level={4}>{user?.nickname || '未填写昵称'}</Typography.Title>
              <Typography.Text type="secondary">{user?.role === 'admin' ? '管理员' : '用户'}</Typography.Text>
            </div>
          </Space>
          <Button className="profile-refresh" onClick={() => window.location.assign('/auth/wechat/refresh')}>刷新微信资料</Button>
        </div>
      </Card>

      <Card title="FAFU 账号" className="content-card section-card">
        <div className="profile-setting-heading">
          <div>
            <Typography.Text strong>FAFU Token</Typography.Text>
            <Typography.Paragraph type="secondary" className="profile-setting-description">
              {settings?.has_user_token ? `已保存 ${settings.user_token_masked ?? 'Token'}` : '尚未配置 Token'}
            </Typography.Paragraph>
          </div>
          <Tag color={settings?.has_user_token ? 'success' : 'warning'}>{settings?.has_user_token ? '已配置' : '待配置'}</Tag>
        </div>
        <Form form={tokenForm} layout="vertical" onFinish={saveToken} disabled={!settings}>
          <Form.Item name="user_token" label="更新 Token" rules={[{ required: true, whitespace: true, message: '请输入 FAFU Token' }]}>
            <Input.Password placeholder="以 2_ 开头，或粘贴完整 Base64 Authorization" autoComplete="new-password" />
          </Form.Item>
          <Space wrap className="profile-token-actions">
            <Button type="primary" htmlType="submit" loading={tokenSaving}>保存 Token</Button>
            {settings?.has_user_token && <Button danger onClick={clearToken}>清除 Token</Button>}
          </Space>
        </Form>
      </Card>

      <Card title="运行偏好" className="content-card section-card">
        <div className="profile-setting-row">
          <div>
            <Typography.Text strong>自动检查</Typography.Text>
            <Typography.Paragraph type="secondary" className="profile-setting-description">按规则签到页设置的周期检查待签到任务</Typography.Paragraph>
          </div>
          <Switch checked={settings?.worker_enabled ?? false} loading={workerSaving} disabled={!settings} onChange={(checked) => void toggleWorker(checked)} />
        </div>
        <div className="profile-setting-row">
          <div>
            <Typography.Text strong>微信结果通知</Typography.Text>
            <Typography.Paragraph type="secondary" className="profile-setting-description">签到完成后向当前微信账号发送结果</Typography.Paragraph>
          </div>
          <Switch checked={settings?.notification_enabled ?? false} loading={notificationSaving} disabled={!settings} onChange={(checked) => void toggleNotification(checked)} />
        </div>
      </Card>

      <Card title={`登录设备（${sessions.length}）`} className="content-card section-card">
        <List
          dataSource={sessions}
          locale={{ emptyText: '没有有效设备' }}
          renderItem={(item) => (
            <List.Item
              className="session-list-item"
              actions={[<Button key="revoke" danger type="link" size="small" onClick={() => void revoke(item.id)}>{item.current ? '退出此设备' : '下线'}</Button>]}
            >
              <List.Item.Meta
                avatar={item.device_type === 'mobile' ? <MobileOutlined className="session-device-icon" /> : <DesktopOutlined className="session-device-icon" />}
                title={<Space size={6}><span>{sessionName(item)}</span>{item.current && <Tag color="success">当前</Tag>}</Space>}
                description={`最近活跃 ${dayjs(item.last_seen_at).format('YYYY-MM-DD HH:mm')}`}
              />
            </List.Item>
          )}
        />
      </Card>
      <Button danger className="mobile-full-button" onClick={() => void logout()}>退出登录</Button>
    </div>
  );
}
