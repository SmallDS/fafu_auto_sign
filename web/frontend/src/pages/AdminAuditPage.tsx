import { App, Card, Empty, Grid, List, Table, Tag } from 'antd';
import { useEffect, useState, type ReactNode } from 'react';
import { api, getErrorMessage } from '../api/client';
import { PageHeading } from '../components/PageHeading';
import { PageSkeleton } from '../components/PageSkeleton';
import type { AuditLog } from '../types/api';

export function AdminAuditPage(): ReactNode {
  const { message } = App.useApp();
  const mobile = !Grid.useBreakpoint().md;
  const [items, setItems] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void api.getAdminAudit(1, 100)
      .then((page) => setItems(page.items))
      .catch((error) => message.error(getErrorMessage(error)))
      .finally(() => setLoading(false));
  }, [message]);

  if (loading && items.length === 0) return <div className="page-container"><PageSkeleton variant="list" /></div>;

  return (
    <div className="page-container">
      <PageHeading title="审计日志" description="记录秘密查看、配置修改、用户管理和菜单同步操作。" />
      <Card className="content-card">
        {mobile ? (
          <List
            loading={loading}
            dataSource={items}
            locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无审计记录" /> }}
            renderItem={(item) => (
              <List.Item className="audit-mobile-item" extra={<Tag color={item.result === 'success' ? 'green' : 'red'}>{item.result}</Tag>}>
                <List.Item.Meta
                  title={item.action}
                  description={(item.detail || '—') + ' · ' + new Date(item.created_at).toLocaleString()}
                />
              </List.Item>
            )}
          />
        ) : (
          <Table
            rowKey="id"
            loading={loading}
            dataSource={items}
            scroll={{ x: 960 }}
            pagination={{ pageSize: 30 }}
            locale={{ emptyText: '暂无审计记录' }}
            columns={[
              { title: '时间', dataIndex: 'created_at', width: 180, render: (value: string) => new Date(value).toLocaleString() },
              { title: '操作', dataIndex: 'action', width: 180 },
              { title: '操作者', dataIndex: 'actor_user_id', width: 180, ellipsis: true },
              { title: '目标用户', dataIndex: 'target_user_id', width: 180, ellipsis: true },
              { title: '结果', dataIndex: 'result', width: 90 },
              { title: '说明', dataIndex: 'detail', ellipsis: true },
            ]}
          />
        )}
      </Card>
    </div>
  );
}
