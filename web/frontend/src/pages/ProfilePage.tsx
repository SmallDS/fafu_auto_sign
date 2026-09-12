import { App, Avatar, Button, Card, List, Space, Typography } from 'antd';
import { useEffect, useState, type ReactNode } from 'react';
import { api, getErrorMessage } from '../api/client';
import { PageHeading } from '../components/PageHeading';
import { useAuth } from '../context/AuthContext';
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
    try {
      await api.logout();
      clearUser();
      window.location.assign('/login');
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  return (
    <div className="page-container narrow-page">
      <PageHeading title="个人中心" description="查看微信身份与已登录设备。" />
      <Card className="content-card section-card">
        <div className="profile-summary">
          <Space className="profile-identity">
            <Avatar size={56} src={user?.avatar_url}>{user?.nickname?.slice(0, 1)}</Avatar>
            <div className="profile-copy">
              <Typography.Title level={4}>{user?.nickname || '未填写昵称'}</Typography.Title>
              <Typography.Text type="secondary">{user?.role === 'admin' ? '管理员' : '用户'}</Typography.Text>
            </div>
          </Space>
          <Button className="profile-refresh" onClick={() => window.location.assign('/auth/wechat/refresh')}>在微信内刷新昵称头像</Button>
        </div>
      </Card>
      <Card title="登录设备" className="content-card section-card">
        <List
          dataSource={sessions}
          locale={{ emptyText: '没有有效设备' }}
          renderItem={(item) => (
            <List.Item className="session-list-item" actions={[<Button danger onClick={() => void revoke(item.id)}>撤销</Button>]}>
              <List.Item.Meta
                title={(item.device_type === 'mobile' ? '手机' : '电脑') + (item.current ? '（当前）' : '')}
                description={item.user_agent || '未知设备'}
              />
            </List.Item>
          )}
        />
      </Card>
      <Button danger className="mobile-full-button" onClick={() => void logout()}>退出登录</Button>
    </div>
  );
}
