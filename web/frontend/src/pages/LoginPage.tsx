import { Alert, Button, Card, Space, Typography } from 'antd';
import { QRCodeSVG } from 'qrcode.react';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { api, getErrorMessage } from '../api/client';
import { useAuth } from '../context/AuthContext';
import type { Pairing } from '../types/api';

const statusText: Record<string, string> = {
  pending: '等待微信扫码',
  scanning: '已扫码，正在完成微信授权',
  profile_pending: '已扫码，请在手机上完善昵称和头像',
  awaiting_approval: '资料已提交，正在等待管理员审核',
  ready: '登录成功，正在进入系统…',
  expired: '二维码已过期，请刷新',
  rejected: '账号申请未通过',
  disabled: '账号已被禁用',
  consumed: '二维码已经使用',
};

const oauthErrors: Record<string, string> = {
  oauth_denied: '你取消了微信资料授权，请重新扫码',
  account_disabled: '该微信账号已被禁用',
  wechat_oauth_failed: '微信授权失败，请刷新二维码后重试',
};

export function LoginPage(): ReactNode {
  const { acceptUser } = useAuth();
  const [pairing, setPairing] = useState<Pairing | null>(null);
  const [now, setNow] = useState(Date.now());
  const [error, setError] = useState<string | null>(() => {
    const code = new URLSearchParams(window.location.search).get('error') ?? '';
    return oauthErrors[code] ?? null;
  });

  const expectedOrigin = useMemo(() => {
    if (!pairing?.auth_url) return null;
    try {
      return new URL(pairing.auth_url).origin;
    } catch {
      return null;
    }
  }, [pairing?.auth_url]);
  const originMismatch = Boolean(expectedOrigin && expectedOrigin !== window.location.origin);
  const remaining = pairing
    ? Math.max(0, Math.ceil((new Date(pairing.expires_at).getTime() - now) / 1000))
    : 0;

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
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    if (!pairing || originMismatch || ['expired', 'consumed', 'rejected', 'disabled'].includes(pairing.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const current = await api.getLoginPairing(pairing.id);
        setPairing((previous) => ({ ...current, auth_url: current.auth_url ?? previous?.auth_url ?? null }));
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
  }, [acceptUser, originMismatch, pairing?.id, pairing?.status]);

  return (
    <main className="auth-page">
      <Card className="auth-card qr-stage">
        <Typography.Title level={2}>微信扫码登录</Typography.Title>
        <Typography.Paragraph type="secondary">请使用已绑定本系统的微信扫码。</Typography.Paragraph>
        {originMismatch && expectedOrigin ? (
          <Alert
            type="warning"
            showIcon
            message="当前地址无法完成登录"
            description="Session Cookie 只会在系统配置的公网 HTTPS 地址生效。"
            action={<Button href={`${expectedOrigin}/login`}>打开正确地址</Button>}
          />
        ) : null}
        {!originMismatch && pairing?.auth_url && pairing.status === 'pending' ? (
          <QRCodeSVG value={pairing.auth_url} size={220} level="M" />
        ) : null}
        <Space orientation="vertical" size={2}>
          <Typography.Text>{statusText[pairing?.status ?? 'pending'] ?? '正在确认登录状态'}</Typography.Text>
          {pairing && !['consumed', 'rejected', 'disabled'].includes(pairing.status) ? (
            <Typography.Text type="secondary">剩余 {remaining} 秒</Typography.Text>
          ) : null}
        </Space>
        {error ? <Alert type="error" showIcon message={error} /> : null}
        <Button type="primary" onClick={() => void create()}>刷新二维码</Button>
      </Card>
    </main>
  );
}