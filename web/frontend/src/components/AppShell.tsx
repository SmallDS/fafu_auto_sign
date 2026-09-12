import {
  AuditOutlined, DashboardOutlined, FileSearchOutlined, HistoryOutlined, MenuOutlined,
  PictureOutlined, SettingOutlined, TeamOutlined, UnorderedListOutlined, UserOutlined,
} from '@ant-design/icons';
import { Avatar, Button, Drawer, Grid, Layout, Menu, Space, Typography } from 'antd';
import { useState, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const { Header, Sider, Content } = Layout;
const userItems = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: '概览' },
  { key: '/settings', icon: <SettingOutlined />, label: '规则签到' },
  { key: '/sign-tasks', icon: <UnorderedListOutlined />, label: '签到任务' },
  { key: '/images', icon: <PictureOutlined />, label: '图片' },
  { key: '/history', icon: <HistoryOutlined />, label: '历史' },
  { key: '/profile', icon: <UserOutlined />, label: '个人中心' },
];
const adminItems = [
  { key: '/admin', icon: <DashboardOutlined />, label: '管理概览' },
  { key: '/admin/users', icon: <TeamOutlined />, label: '用户管理' },
  { key: '/admin/system', icon: <SettingOutlined />, label: '系统设置' },
  { key: '/admin/audit', icon: <AuditOutlined />, label: '审计日志' },
  { key: '/logs', icon: <FileSearchOutlined />, label: '系统日志' },
  { key: '/dashboard', icon: <UnorderedListOutlined />, label: '我的签到' },
  { key: '/profile', icon: <UserOutlined />, label: '个人中心' },
];

function Brand(): ReactNode {
  return (
    <Space size={10} className="brand">
      <span className="brand-mark" aria-hidden="true">F</span>
      <span>
        <Typography.Text strong className="brand-title">FAFU 签到</Typography.Text>
        <Typography.Text className="brand-subtitle">多用户控制台</Typography.Text>
      </span>
    </Space>
  );
}

export function AppShell({ children }: { children: ReactNode }): ReactNode {
  const mobile = !Grid.useBreakpoint().md;
  const [drawerOpen, setDrawerOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const { user } = useAuth();
  const items = user?.role === 'admin' ? adminItems : userItems;
  const activeKey = [...items]
    .sort((a, b) => b.key.length - a.key.length)
    .find((item) => location.pathname === item.key || location.pathname.startsWith(item.key + '/'))?.key
    ?? '/dashboard';

  const navigation = (
    <>
      <Menu
        className="app-menu"
        mode="inline"
        selectedKeys={[activeKey]}
        items={items}
        onClick={({ key }) => {
          navigate(key);
          setDrawerOpen(false);
        }}
      />
      <div className="nav-user">
        <Avatar src={user?.avatar_url}>{user?.nickname?.slice(0, 1)}</Avatar>
        <Typography.Text ellipsis>{user?.nickname}</Typography.Text>
      </div>
    </>
  );

  return (
    <Layout className="app-layout">
      {!mobile && (
        <Sider width={232} theme="light" className="app-sider">
          <div className="sider-brand"><Brand /></div>
          {navigation}
        </Sider>
      )}
      <Layout>
        {mobile && (
          <Header className="mobile-header">
            <Brand />
            <Button type="text" icon={<MenuOutlined />} aria-label="打开导航" onClick={() => setDrawerOpen(true)} />
          </Header>
        )}
        <Content className="app-content">{children}</Content>
      </Layout>
      <Drawer
        className="navigation-drawer"
        placement="left"
        width="min(82vw, 300px)"
        open={mobile && drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title={<Brand />}
        styles={{ body: { padding: '8px 12px' } }}
      >
        {navigation}
      </Drawer>
    </Layout>
  );
}
