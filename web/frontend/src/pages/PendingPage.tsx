import { Alert, Button, Card, Result } from 'antd';
import { useEffect, useState, type ReactNode } from 'react';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import type { UserStatus } from '../types/api';

export function PendingPage(): ReactNode {
  const { user, refresh, clearUser } = useAuth();
  const [status, setStatus] = useState<UserStatus>(user?.status ?? 'pending');
  const [reason, setReason] = useState(user?.rejection_reason ?? '');

  useEffect(() => {
    const events = new EventSource('/api/onboarding/status/stream');
    const update = (event: MessageEvent<string>) => {
      const data = JSON.parse(event.data) as { status: UserStatus; rejection_reason?: string };
      setStatus(data.status);
      setReason(data.rejection_reason ?? '');
      if (data.status === 'active') {
        events.close();
        void refresh().then(() => window.location.assign('/settings'));
      }
    };
    events.addEventListener('status', update as EventListener);
    events.onerror = () => { void api.getOnboardingStatus().then((current) => setStatus(current.status)); };
    return () => events.close();
  }, [refresh]);

  const logout = async () => {
    await api.logout();
    clearUser();
    window.location.assign('/login');
  };

  return (
    <main className="auth-page">
      <Card className="auth-card">
        {status === 'rejected' ? (
          <Result status="error" title="账号申请未通过" subTitle={reason || '管理员未填写原因'} />
        ) : status === 'disabled' ? (
          <Result status="warning" title="账号已禁用" />
        ) : (
          <>
            <Result status="info" title="等待管理员审核" subTitle="审核结果会自动更新，无需反复刷新。" />
            <Alert type="info" showIcon message="审核通过后将进入 FAFU 首次配置" />
          </>
        )}
        <Button block onClick={() => void logout()}>退出登录</Button>
      </Card>
    </main>
  );
}