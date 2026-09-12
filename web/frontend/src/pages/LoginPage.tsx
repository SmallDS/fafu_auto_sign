import { Alert, Button, Card, Typography } from 'antd';
import { QRCodeSVG } from 'qrcode.react';
import { useEffect, useState, type ReactNode } from 'react';
import { api, getErrorMessage } from '../api/client';
import { useAuth } from '../context/AuthContext';
import type { Pairing } from '../types/api';

export function LoginPage(): ReactNode {
  const { acceptUser } = useAuth();
  const [pairing, setPairing] = useState<Pairing | null>(null);
  const [error, setError] = useState<string | null>(null);

  const create = async () => {
    try {
      setError(null);
      setPairing(await api.createLoginPairing());
    } catch (reason) {
      setError(getErrorMessage(reason));
    }
  };
  useEffect(() => { void create(); }, []);
  useEffect(() => {
    if (!pairing || ['expired', 'consumed', 'rejected', 'disabled'].includes(pairing.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const current = await api.getLoginPairing(pairing.id);
        setPairing(current);
        if (current.status === 'ready') {
          const user = await api.exchangeLoginPairing(current.id);
          acceptUser(user);
          window.location.assign(user.role === 'admin' ? '/admin' : '/dashboard');
        }
      } catch (reason) {
        setError(getErrorMessage(reason));
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [acceptUser, pairing?.id, pairing?.status]);

  return (
    <main className="auth-page">
      <Card className="auth-card qr-stage">
        <Typography.Title level={2}>微信扫码登录</Typography.Title>
        <Typography.Paragraph type="secondary">请使用已绑定本系统的微信扫码。</Typography.Paragraph>
        {pairing?.auth_url ? <QRCodeSVG value={pairing.auth_url} size={220} level="M" /> : null}
        <Typography.Text>
          {pairing?.status === 'awaiting_approval' ? '账号正在等待管理员审核' :
            pairing?.status === 'expired' ? '二维码已过期' : '等待扫码'}
        </Typography.Text>
        {error ? <Alert type="error" showIcon message={error} /> : null}
        <Button type="primary" onClick={() => void create()}>刷新二维码</Button>
      </Card>
    </main>
  );
}