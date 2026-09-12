import { App, Avatar, Button, Card, List, Space, Typography } from 'antd';
import { useEffect, useState, type ReactNode } from 'react';
import { api, getErrorMessage } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { PageHeading } from '../components/PageHeading';
import type { UserSession } from '../types/api';

export function ProfilePage(): ReactNode {
  const { message } = App.useApp();
  const { user, clearUser } = useAuth();
  const [sessions, setSessions] = useState<UserSession[]>([]);
  const load = () => api.getSessions().then(setSessions).catch((error) => message.error(getErrorMessage(error)));
  useEffect(() => { void load(); }, []);

  const revoke = async (id: string) => {
    try {
      await api.revokeSession(id);
      const current = sessions.find((item) => item.id === id)?.current;
      if (current) {
        clearUser();
        window.location.assign('/login');
      } else {
        await load();
      }
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  const logout = async () => {
    await api.logout();
    clearUser();
    window.location.assign('/login');
  };

  return (
    <>
      <PageHeading title="个人中心" description="查看微信身份与已登录设备。" />
      <Card className="section-card">
        <Space>
          <Avatar size={56} src={user?.avatar_url}>{user?.nickname?.slice(0, 1)}</Avatar>
          <div>
            <Typography.Title level={4}>{user?.nickname}</Typography.Title>
            <Typography.Text type="secondary">{user?.role === 'admin' ? '管理员' : '用户'}</Typography.Text>
          </div>
          <Button onClick={() => window.location.assign('/auth/wechat/refresh')}>在微信内刷新昵称头像</Button>
        </Space>
      </Card>
      <Card title="登录设备" className="section-card">
        <List
          dataSource={sessions}
          renderItem={(item) => (
            <List.Item actions={[<Button danger onClick={() => void revoke(item.id)}>撤销</Button>]}>
              <List.Item.Meta
                title={(item.device_type === 'mobile' ? '手机' : '电脑') + (item.current ? '（当前）' : '')}
                description={item.user_agent || '未知设备'}
              />
            </List.Item>
          )}
        />
      </Card>
      <Button danger onClick={() => void logout()}>退出登录</Button>
    </>
  );
}