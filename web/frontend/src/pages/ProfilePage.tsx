import { DesktopOutlined, MobileOutlined } from '@ant-design/icons';
import { Alert, App, Avatar, Button, Card, Form, Input, List, Radio, Space, Switch, Tag, Typography } from 'antd';
import dayjs from 'dayjs';
import { useEffect, useState, type ReactNode } from 'react';
import { api, getErrorMessage } from '../api/client';
import { PageHeading } from '../components/PageHeading';
import { PageSkeleton } from '../components/PageSkeleton';
import { useAuth } from '../context/AuthContext';
import type { FafuAuthAttempt, FafuAuthMode, FafuAuthStartInput, Settings, UserSession } from '../types/api';

interface TokenFormValues {
  user_token: string;
}

interface SmsFormValues {
  code: string;
}

const authStatusLabel: Record<NonNullable<Settings['fafu_auth_status']>, string> = {
  unconfigured: '待配置',
  manual: '手动 Token',
  connected: '自动续期已连接',
  refresh_backoff: '续期等待重试',
  reconnect_required: '需要重新连接',
};

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
  const [autoForm] = Form.useForm<FafuAuthStartInput>();
  const [smsForm] = Form.useForm<SmsFormValues>();
  const [sessions, setSessions] = useState<UserSession[]>([]);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [tokenSaving, setTokenSaving] = useState(false);
  const [authSaving, setAuthSaving] = useState(false);
  const [selectedMode, setSelectedMode] = useState<Exclude<FafuAuthMode, null>>('manual');
  const [attempt, setAttempt] = useState<FafuAuthAttempt | null>(null);
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
      setSelectedMode(nextSettings.fafu_auth_mode === 'auto' ? 'auto' : 'manual');
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
      setSelectedMode('manual');
      message.success('FAFU Token 已保存');
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setTokenSaving(false);
    }
  };

  const clearToken = (): void => {
    modal.confirm({
      title: '确认清除 FAFU 配置？',
      content: '清除后会删除当前登录方式的凭据，并暂停自动检查。',
      okText: '确认清除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      async onOk() {
        try {
          const saved = await api.updateSettings({ clear_user_token: true });
          setSettings(saved);
          tokenForm.resetFields();
          setAttempt(null);
          setSelectedMode('manual');
          message.success('FAFU 配置已清除');
        } catch (error) {
          message.error(getErrorMessage(error));
        }
      },
    });
  };

  const changeMode = (mode: 'manual' | 'auto'): void => {
    if (attempt) {
      void api.cancelFafuAuth(attempt.attempt_id).catch((error: unknown) => message.error(getErrorMessage(error)));
      setAttempt(null);
      smsForm.resetFields();
    }
    setSelectedMode(mode);
  };

  const startAutoAuth = async (values: FafuAuthStartInput): Promise<void> => {
    setAuthSaving(true);
    try {
      const nextAttempt = await api.startFafuAuth({
        username: values.username.trim(),
        password: values.password,
        device_id: values.device_id.trim(),
      });
      setAttempt(nextAttempt);
      autoForm.resetFields();
      message.success('短信验证码已发送');
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setAuthSaving(false);
    }
  };

  const reconnectAutoAuth = async (): Promise<void> => {
    setAuthSaving(true);
    try {
      setAttempt(await api.reconnectFafuAuth());
      message.success('短信验证码已发送');
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setAuthSaving(false);
    }
  };

  const completeAutoAuth = async ({ code }: SmsFormValues): Promise<void> => {
    if (!attempt) return;
    setAuthSaving(true);
    try {
      const saved = await api.completeFafuAuth(attempt.attempt_id, code.trim());
      setSettings(saved);
      setSelectedMode('auto');
      setAttempt(null);
      autoForm.resetFields();
      smsForm.resetFields();
      message.success('FAFU 账号已连接，Token 将自动续期');
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setAuthSaving(false);
    }
  };

  const cancelAutoAuth = async (): Promise<void> => {
    if (!attempt) return;
    setAuthSaving(true);
    try {
      await api.cancelFafuAuth(attempt.attempt_id);
      setAttempt(null);
      smsForm.resetFields();
      message.info('已取消本次连接');
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setAuthSaving(false);
    }
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
            <Typography.Text strong>当前连接</Typography.Text>
            <Typography.Paragraph type="secondary" className="profile-setting-description">
              {settings?.fafu_auth_mode === 'auto'
                ? `学号 ${settings.fafu_username_masked ?? '已绑定'}`
                : settings?.has_user_token
                  ? `已保存 ${settings.user_token_masked ?? 'Token'}`
                  : '尚未配置 FAFU 账号'}
            </Typography.Paragraph>
          </div>
          <Tag color={settings?.fafu_auth_status === 'connected' || settings?.fafu_auth_status === 'manual' ? 'success' : 'warning'}>
            {authStatusLabel[settings?.fafu_auth_status ?? (settings?.has_user_token ? 'manual' : 'unconfigured')]}
          </Tag>
        </div>
        {settings?.fafu_auth_mode === 'auto' && settings.fafu_last_refresh_at && (
          <Typography.Paragraph type="secondary" className="profile-setting-description">
            最近续期：{dayjs(settings.fafu_last_refresh_at).format('YYYY-MM-DD HH:mm')}
          </Typography.Paragraph>
        )}
        {settings?.fafu_auth_mode === 'auto' && settings.fafu_last_error && (
          <Alert className="section-alert" type="warning" showIcon message="最近一次续期未成功" description={settings.fafu_last_error} />
        )}
        <Typography.Paragraph type="secondary" className="profile-setting-description">
          选择一种 FAFU 登录方式。切换会在新方式保存或连接成功后生效。
        </Typography.Paragraph>
        <Radio.Group
          className="profile-auth-mode"
          value={selectedMode}
          disabled={authSaving || tokenSaving}
          onChange={(event) => changeMode(event.target.value as 'manual' | 'auto')}
          optionType="button"
          buttonStyle="solid"
          options={[{ label: '手动输入 Token', value: 'manual' }, { label: '账号登录·自动续期', value: 'auto' }]}
        />

        {selectedMode === 'manual' ? (
          <Form form={tokenForm} layout="vertical" onFinish={saveToken} disabled={!settings} className="profile-auth-form">
            <Form.Item name="user_token" label="FAFU Token" rules={[{ required: true, whitespace: true, message: '请输入 FAFU Token' }]}>
              <Input.Password placeholder="以 2_ 开头，或粘贴完整 Base64 Authorization" autoComplete="new-password" />
            </Form.Item>
            <Space wrap className="profile-token-actions">
              <Button type="primary" htmlType="submit" loading={tokenSaving}>保存 Token</Button>
              {settings?.has_user_token && <Button danger onClick={clearToken}>清除 FAFU 配置</Button>}
            </Space>
          </Form>
        ) : attempt ? (
          <div className="profile-auth-form">
            <Alert
              type="info"
              showIcon
              message="输入短信验证码"
              description={`验证码已发送，连接会话将在 ${dayjs(attempt.expires_at).format('HH:mm:ss')} 过期。`}
            />
            <Form form={smsForm} layout="vertical" onFinish={completeAutoAuth} className="profile-sms-form">
              <Form.Item name="code" label="短信验证码" rules={[{ required: true, message: '请输入短信验证码' }, { pattern: /^\d{4,10}$/, message: '请输入 4～10 位数字验证码' }]}>
                <Input inputMode="numeric" maxLength={10} autoComplete="one-time-code" placeholder="输入收到的验证码" />
              </Form.Item>
              <Space wrap className="profile-token-actions">
                <Button type="primary" htmlType="submit" loading={authSaving}>完成连接</Button>
                <Button onClick={() => void cancelAutoAuth()} disabled={authSaving}>取消本次连接</Button>
              </Space>
            </Form>
          </div>
        ) : (
          <div className="profile-auth-form">
            {settings?.fafu_auth_mode === 'auto' && (
              <Space wrap className="profile-token-actions profile-reconnect-actions">
                <Button type="primary" loading={authSaving} onClick={() => void reconnectAutoAuth()}>重新连接</Button>
                <Button danger onClick={clearToken}>清除 FAFU 配置</Button>
              </Space>
            )}
            <Form form={autoForm} layout="vertical" onFinish={startAutoAuth} disabled={!settings || authSaving}>
              <Typography.Text strong>{settings?.fafu_auth_mode === 'auto' ? '更换 FAFU 账号或设备' : '连接 FAFU 账号'}</Typography.Text>
              <Form.Item name="username" label="学号" rules={[{ required: true, whitespace: true, message: '请输入学号' }]} className="profile-auth-first-field">
                <Input maxLength={64} autoComplete="username" placeholder="填写 FAFU 学号" />
              </Form.Item>
              <Form.Item name="password" label="CAS 密码" rules={[{ required: true, message: '请输入 CAS 密码' }]}>
                <Input.Password maxLength={256} autoComplete="new-password" placeholder="填写统一身份认证密码" />
              </Form.Item>
              <Form.Item
                name="device_id"
                label="已绑定设备 ID（deviceId）"
                extra="必须与已绑定设备的 Android ID 完全一致（区分大小写）。可在该手机“设置 → 关于手机 → 状态信息”查看，或用 adb shell settings get secure android_id 核对。"
                rules={[{ required: true, whitespace: true, message: '请输入已绑定设备 ID' }]}
              >
                <Input maxLength={128} autoComplete="off" placeholder="从已绑定设备复制 deviceId" />
              </Form.Item>
              <Button type={settings?.fafu_auth_mode === 'auto' ? 'default' : 'primary'} htmlType="submit" loading={authSaving} className="mobile-full-button">
                {settings?.fafu_auth_mode === 'auto' ? '连接其他账号' : '登录并发送短信验证码'}
              </Button>
            </Form>
          </div>
        )}
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
