import {
  DashboardOutlined,
  FileSearchOutlined,
  HistoryOutlined,
  MenuOutlined,
  PictureOutlined,
  SettingOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons';
import { Button, Drawer, Grid, Layout, Menu, Space, Typography } from 'antd';
import { useState, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

const { Header, Sider, Content } = Layout;

const menuItems = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: '概览' },
  { key: '/settings', icon: <SettingOutlined />, label: '设置' },
  { key: '/sign-tasks', icon: <UnorderedListOutlined />, label: '签到任务' },
  { key: '/images', icon: <PictureOutlined />, label: '图片' },
  { key: '/history', icon: <HistoryOutlined />, label: '历史' },
  { key: '/logs', icon: <FileSearchOutlined />, label: '日志' },
];

interface AppShellProps {
  children: ReactNode;
}

function Brand(): ReactNode {
  return (
    <Space size={10} className="brand">
      <span className="brand-mark" aria-hidden="true">F</span>
      <span>
        <Typography.Text strong className="brand-title">FAFU 签到</Typography.Text>
        <Typography.Text className="brand-subtitle">管理控制台</Typography.Text>
      </span>
    </Space>
  );
}

export function AppShell({ children }: AppShellProps): ReactNode {
  const screens = Grid.useBreakpoint();
  const mobile = !screens.md;
  const [drawerOpen, setDrawerOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const activeKey = menuItems.find((item) => location.pathname.startsWith(item.key))?.key ?? '/dashboard';

  const navigation = (
    <Menu
      className="app-menu"
      mode="inline"
      selectedKeys={[activeKey]}
      items={menuItems}
      onClick={({ key }) => {
        navigate(key);
        setDrawerOpen(false);
      }}
    />
  );

  return (
    <Layout className="app-layout">
      {!mobile && (
        <Sider width={232} theme="light" className="app-sider">
          <div className="sider-brand"><Brand /></div>
          {navigation}
          <div className="trusted-network-note">仅供可信局域网使用</div>
        </Sider>
      )}
      <Layout>
        {mobile && (
          <Header className="mobile-header">
            <Brand />
            <Button
              type="text"
              icon={<MenuOutlined />}
              aria-label="打开导航"
              onClick={() => setDrawerOpen(true)}
            />
          </Header>
        )}
        <Content className="app-content">{children}</Content>
      </Layout>
      <Drawer
        placement="left"
        width="min(82vw, 300px)"
        open={mobile && drawerOpen}
        onClose={() => setDrawerOpen(false)}
        title={<Brand />}
        styles={{ body: { padding: '8px 12px' } }}
      >
        {navigation}
        <div className="trusted-network-note drawer-note">仅供可信局域网使用</div>
      </Drawer>
    </Layout>
  );
}