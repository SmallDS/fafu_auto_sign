import { App as AntApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import type { ReactNode } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { DashboardPage } from './pages/DashboardPage';
import { HistoryPage } from './pages/HistoryPage';
import { ImagesPage } from './pages/ImagesPage';
import { LogsPage } from './pages/LogsPage';
import { SettingsPage } from './pages/SettingsPage';
import { SignTasksPage } from './pages/SignTasksPage';

export default function App(): ReactNode {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#0f766e',
          colorInfo: '#0f766e',
          colorSuccess: '#15803d',
          colorWarning: '#d97706',
          colorError: '#b42318',
          borderRadius: 10,
          fontFamily: "Inter, 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif",
        },
        components: {
          Layout: { bodyBg: '#f5f7f8', siderBg: '#ffffff', headerBg: '#ffffff' },
          Card: { headerBg: 'transparent' },
          Menu: { itemBorderRadius: 8 },
        },
      }}
    >
      <AntApp>
        <AppShell>
          <Routes>
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/sign-tasks" element={<SignTasksPage />} />
            <Route path="/images" element={<ImagesPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/logs" element={<LogsPage />} />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </AppShell>
      </AntApp>
    </ConfigProvider>
  );
}