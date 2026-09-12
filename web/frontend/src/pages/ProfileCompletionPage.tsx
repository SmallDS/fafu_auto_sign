import { App, Button, Card, Form, Input, Upload, Typography } from 'antd';
import type { UploadFile } from 'antd';
import { useState, type ReactNode } from 'react';
import { api, getErrorMessage } from '../api/client';
import { useAuth } from '../context/AuthContext';

export function ProfileCompletionPage(): ReactNode {
  const { message } = App.useApp();
  const { user, acceptUser } = useAuth();
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [saving, setSaving] = useState(false);

  const submit = async ({ nickname }: { nickname: string }) => {
    setSaving(true);
    try {
      const file = files[0]?.originFileObj;
      const next = await api.completeProfile(nickname, file);
      acceptUser(next);
      window.location.assign(next.status === 'active' ? '/admin' : '/pending');
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <main className="auth-page">
      <Card className="auth-card">
        <Typography.Title level={2}>完善微信资料</Typography.Title>
        <Form layout="vertical" initialValues={{ nickname: user?.nickname ?? '' }} onFinish={submit}>
          <Form.Item name="nickname" label="昵称" rules={[{ required: true }, { max: 64 }]}>
            <Input />
          </Form.Item>
          <Form.Item label="头像" required={!user?.avatar_url}>
            <Upload
              accept="image/jpeg,image/png,image/webp"
              maxCount={1}
              beforeUpload={() => false}
              fileList={files}
              onChange={({ fileList }) => setFiles(fileList)}
            >
              <Button>选择头像</Button>
            </Upload>
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={saving} block>保存资料</Button>
        </Form>
      </Card>
    </main>
  );
}