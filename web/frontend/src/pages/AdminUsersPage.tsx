import {
  App, Avatar, Button, Card, Descriptions, Divider, Drawer, Grid, Input, InputNumber,
  List, Popconfirm, Select, Space, Switch, Table, Tag, Typography,
} from 'antd';
import { useEffect, useState, type ReactNode } from 'react';
import { api, getErrorMessage } from '../api/client';
import { PageHeading } from '../components/PageHeading';
import type {
  AdminUser, AuditLog, ImageRecord, RunRecord, Settings, UserSession, UserStatus,
} from '../types/api';

const statusLabels: Record<string, string> = {
  profile_pending: '待补资料', pending: '待审核', active: '正常', rejected: '已驳回', disabled: '已禁用',
};

export function AdminUsersPage(): ReactNode {
  const { message } = App.useApp();
  const mobile = !Grid.useBreakpoint().md;
  const [items, setItems] = useState<AdminUser[]>([]);
  const [selected, setSelected] = useState<AdminUser | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [sessions, setSessions] = useState<UserSession[]>([]);
  const [images, setImages] = useState<ImageRecord[]>([]);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [audits, setAudits] = useState<AuditLog[]>([]);
  const [token, setToken] = useState('');
  const [keywords, setKeywords] = useState('');
  const [reason, setReason] = useState('');
  const [filter, setFilter] = useState<UserStatus | undefined>();

  const load = async () => {
    try {
      const page = await api.listAdminUsers(1, 100, filter);
      setItems(page.items);
      if (selected) setSelected(page.items.find((item) => item.id === selected.id) ?? null);
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };
  useEffect(() => { void load(); }, [filter]);

  const open = async (user: AdminUser) => {
    setSelected(user);
    setReason(user.rejection_reason ?? '');
    setToken('');
    try {
      const [nextSettings, sessionRows, imagePage, runPage, auditPage] = await Promise.all([
        api.getAdminUserSettings(user.id),
        api.getAdminUserSessions(user.id),
        api.getAdminUserImages(user.id),
        api.getAdminUserRuns(user.id),
        api.getAdminAudit(1, 20, user.id),
      ]);
      setSettings(nextSettings);
      setKeywords(nextSettings.task_keywords.join(', '));
      setSessions(sessionRows);
      setImages(imagePage.items);
      setRuns(runPage.items);
      setAudits(auditPage.items);
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  const update = async (input: Parameters<typeof api.updateAdminUser>[1]) => {
    if (!selected) return;
    try {
      const next = await api.updateAdminUser(selected.id, input);
      setSelected(next);
      message.success('用户状态已更新');
      await load();
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  const reveal = async () => {
    if (!selected) return;
    try {
      const result = await api.revealAdminUserToken(selected.id);
      setToken(result.user_token ?? '');
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  const saveConfiguration = async () => {
    if (!selected || !settings) return;
    try {
      const next = await api.updateAdminUserSettings(selected.id, {
        user_token: token.trim() || undefined,
        jitter: settings.jitter,
        heartbeat_interval: settings.heartbeat_interval,
        task_keywords: keywords.split(',').map((item) => item.trim()).filter(Boolean),
        image_mode: settings.image_mode,
        selected_image_id: settings.image_mode === 'single' ? settings.selected_image_id : null,
        worker_enabled: settings.worker_enabled,
        notification_enabled: settings.notification_enabled,
      });
      setSettings(next);
      setToken('');
      message.success('用户签到配置已保存');
      await load();
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  const remove = async () => {
    if (!selected) return;
    try {
      await api.deleteAdminUser(selected.id);
      setSelected(null);
      await load();
      message.success('用户及个人数据已删除');
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  const action = (user: AdminUser) => <Button onClick={() => void open(user)}>管理</Button>;
  return (
    <>
      <PageHeading title="用户管理" description="审核用户，管理角色、完整签到配置、设备与运行记录。" />
      <Select
        allowClear
        placeholder="筛选状态"
        style={{ width: 180, marginBottom: 16 }}
        value={filter}
        onChange={setFilter}
        options={Object.entries(statusLabels).map(([value, label]) => ({ value, label }))}
      />
      {mobile ? (
        <List
          dataSource={items}
          renderItem={(user) => (
            <Card className="mobile-list-card">
              <List.Item actions={[action(user)]}>
                <List.Item.Meta
                  avatar={<Avatar src={user.avatar_url}>{user.nickname?.slice(0, 1)}</Avatar>}
                  title={user.nickname || '未填写昵称'}
                  description={<Space wrap><Tag>{statusLabels[user.status]}</Tag><Tag>{user.role}</Tag></Space>}
                />
              </List.Item>
            </Card>
          )}
        />
      ) : (
        <Table
          rowKey="id"
          dataSource={items}
          pagination={{ pageSize: 20 }}
          columns={[
            { title: '用户', render: (_, user) => <Space><Avatar src={user.avatar_url} />{user.nickname}</Space> },
            { title: 'OpenID', dataIndex: 'openid', ellipsis: true },
            { title: '角色', dataIndex: 'role' },
            { title: '状态', render: (_, user) => <Tag>{statusLabels[user.status]}</Tag> },
            { title: '配置', render: (_, user) => user.configured ? '完整' : '未完成' },
            { title: '操作', render: (_, user) => action(user) },
          ]}
        />
      )}
      <Drawer
        title={selected?.nickname || '用户详情'}
        width={mobile ? '100%' : 680}
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
      >
        {selected ? (
          <Space direction="vertical" size="large" style={{ width: '100%' }}>
            <Descriptions column={1} bordered size="small">
              <Descriptions.Item label="OpenID">{selected.openid}</Descriptions.Item>
              <Descriptions.Item label="状态">{statusLabels[selected.status]}</Descriptions.Item>
              <Descriptions.Item label="角色">{selected.role}</Descriptions.Item>
              <Descriptions.Item label="配置">{selected.configured ? '完整' : '未完成'}</Descriptions.Item>
            </Descriptions>
            <Space wrap>
              <Button type="primary" onClick={() => void update({ status: 'active' })}>批准/恢复</Button>
              <Button onClick={() => void update({ status: 'disabled' })}>禁用</Button>
              <Select
                value={selected.role}
                onChange={(role) => void update({ role })}
                options={[{ value: 'user', label: '普通用户' }, { value: 'admin', label: '管理员' }]}
              />
            </Space>
            <Input.TextArea value={reason} onChange={(event) => setReason(event.target.value)} placeholder="驳回原因" />
            <Button danger onClick={() => void update({ status: 'rejected', rejection_reason: reason })}>驳回</Button>

            <Card size="small" title="签到配置">
              {settings ? (
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Space.Compact block>
                    <Input.Password value={token} onChange={(event) => setToken(event.target.value)} placeholder={settings.user_token_masked || '输入新 Token'} />
                    <Button onClick={() => void reveal()}>显示</Button>
                  </Space.Compact>
                  <Input value={keywords} onChange={(event) => setKeywords(event.target.value)} placeholder="任务关键词，逗号分隔；留空匹配全部" />
                  <Space wrap>
                    <Typography.Text>GPS 抖动</Typography.Text>
                    <InputNumber min={0} max={0.001} step={0.00001} value={settings.jitter} onChange={(value) => setSettings({ ...settings, jitter: value ?? 0 })} />
                    <Typography.Text>间隔（秒）</Typography.Text>
                    <InputNumber min={10} max={86400} value={settings.heartbeat_interval} onChange={(value) => setSettings({ ...settings, heartbeat_interval: value ?? 900 })} />
                  </Space>
                  <Select
                    value={settings.image_mode}
                    onChange={(image_mode) => setSettings({ ...settings, image_mode })}
                    options={[{ value: 'single', label: '固定单图' }, { value: 'library', label: '随机图库' }, { value: 'latest', label: '最新图片队列' }]}
                  />
                  {settings.image_mode === 'single' ? (
                    <Select
                      allowClear
                      placeholder="选择用户图库图片"
                      value={settings.selected_image_id}
                      onChange={(selected_image_id) => setSettings({ ...settings, selected_image_id })}
                      options={images.filter((item) => item.category === 'library').map((item) => ({ value: item.id, label: item.original_name }))}
                    />
                  ) : null}
                  <Space wrap>
                    <Typography.Text>自动检查</Typography.Text>
                    <Switch checked={settings.worker_enabled} onChange={(worker_enabled) => setSettings({ ...settings, worker_enabled })} />
                    <Typography.Text>微信通知</Typography.Text>
                    <Switch checked={settings.notification_enabled} onChange={(notification_enabled) => setSettings({ ...settings, notification_enabled })} />
                  </Space>
                  <Button type="primary" onClick={() => void saveConfiguration()}>保存完整配置</Button>
                </Space>
              ) : null}
            </Card>

            <Space wrap>
              <Button onClick={() => void api.pauseAdminUserWorker(selected.id).then(() => { message.success('已暂停自动检查'); void open(selected); }).catch((error) => message.error(getErrorMessage(error)))}>暂停自动检查</Button>
              <Button onClick={() => void api.resumeAdminUserWorker(selected.id).then(() => { message.success('已恢复自动检查'); void open(selected); }).catch((error) => message.error(getErrorMessage(error)))}>恢复自动检查</Button>
              <Button onClick={() => void api.runAdminUserNow(selected.id).then(() => message.success('已加入队列')).catch((error) => message.error(getErrorMessage(error)))}>立即检查</Button>
              <Button onClick={() => void api.testAdminUserNotification(selected.id).then(() => message.success('测试消息已提交')).catch((error) => message.error(getErrorMessage(error)))}>测试推送</Button>
              <Button onClick={() => void api.revokeAdminUserSessions(selected.id).then(() => { setSessions([]); message.success('会话已撤销'); }).catch((error) => message.error(getErrorMessage(error)))}>撤销全部设备</Button>
            </Space>

            <Divider titlePlacement="start">设备（{sessions.length}）</Divider>
            <List size="small" dataSource={sessions} locale={{ emptyText: '没有有效设备' }} renderItem={(item) => <List.Item><List.Item.Meta title={item.device_type} description={item.user_agent || '未知设备'} /></List.Item>} />
            <Divider titlePlacement="start">图片（{images.length}）</Divider>
            <List grid={{ gutter: 8, xs: 2, sm: 3 }} dataSource={images.slice(0, 12)} locale={{ emptyText: '暂无图片' }} renderItem={(item) => <List.Item><Card size="small" cover={<img className="admin-user-image" src={api.adminUserImageUrl(selected.id, item.id)} alt={item.original_name} />}><Typography.Text ellipsis>{item.original_name}</Typography.Text></Card></List.Item>} />
            <Divider titlePlacement="start">最近运行</Divider>
            <List size="small" dataSource={runs} locale={{ emptyText: '暂无运行记录' }} renderItem={(item) => <List.Item extra={<Tag>{item.result}</Tag>}><List.Item.Meta title={item.summary || '签到检查'} description={new Date(item.started_at).toLocaleString()} /></List.Item>} />
            <Divider titlePlacement="start">相关审计</Divider>
            <List size="small" dataSource={audits} locale={{ emptyText: '暂无审计记录' }} renderItem={(item) => <List.Item><List.Item.Meta title={item.action} description={`${new Date(item.created_at).toLocaleString()} · ${item.result}`} /></List.Item>} />

            <Popconfirm title="彻底删除该用户及其全部数据？" onConfirm={() => void remove()}>
              <Button danger>彻底删除用户及个人数据</Button>
            </Popconfirm>
          </Space>
        ) : null}
      </Drawer>
    </>
  );
}