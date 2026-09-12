import { App as AntApp, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import type { ReactNode } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { AuthProvider, useAuth } from './context/AuthContext';
import { AdminAuditPage } from './pages/AdminAuditPage';
import { AdminDashboardPage } from './pages/AdminDashboardPage';
import { AdminSystemPage } from './pages/AdminSystemPage';
import { AdminUsersPage } from './pages/AdminUsersPage';
import { DashboardPage } from './pages/DashboardPage';
import { HistoryPage } from './pages/HistoryPage';
import { ImagesPage } from './pages/ImagesPage';
import { LoginPage } from './pages/LoginPage';
import { LogsPage } from './pages/LogsPage';
import { PendingPage } from './pages/PendingPage';
import { ProfileCompletionPage } from './pages/ProfileCompletionPage';
import { ProfilePage } from './pages/ProfilePage';
import { SettingsPage } from './pages/SettingsPage';
import { SetupPage } from './pages/SetupPage';
import { SignTasksPage } from './pages/SignTasksPage';

function RoutedApp(): ReactNode {
  const { bootstrap, user } = useAuth();
  if (!bootstrap?.initialized) return <SetupPage />;
  if (!user) return <LoginPage />;
  if (user.status === 'profile_pending') return <ProfileCompletionPage />;
  if (user.status !== 'active') return <PendingPage />;
  const admin = user.role === 'admin';

  return (
    <AppShell>
      <Routes>
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/sign-tasks" element={<SignTasksPage />} />
        <Route path="/images" element={<ImagesPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/admin" element={admin ? <AdminDashboardPage /> : <Navigate to="/dashboard" replace />} />
        <Route path="/admin/users" element={admin ? <AdminUsersPage /> : <Navigate to="/dashboard" replace />} />
        <Route path="/admin/system" element={admin ? <AdminSystemPage /> : <Navigate to="/dashboard" replace />} />
        <Route path="/admin/audit" element={admin ? <AdminAuditPage /> : <Navigate to="/dashboard" replace />} />
        <Route path="/logs" element={admin ? <LogsPage /> : <Navigate to="/dashboard" replace />} />
        <Route path="*" element={<Navigate to={admin ? '/admin' : '/dashboard'} replace />} />
      </Routes>
    </AppShell>
  );
}

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
        <AuthProvider><RoutedApp /></AuthProvider>
      </AntApp>
    </ConfigProvider>
  );
}