import { Grid, List, Table, Tag } from 'antd';
import { useEffect, useState, type ReactNode } from 'react';
import { api } from '../api/client';
import { PageHeading } from '../components/PageHeading';
import type { AuditLog } from '../types/api';

export function AdminAuditPage(): ReactNode {
  const mobile = !Grid.useBreakpoint().md;
  const [items, setItems] = useState<AuditLog[]>([]);
  useEffect(() => {
    void api.getAdminAudit(1, 100).then((page) => setItems(page.items));
  }, []);
  return (
    <>
      <PageHeading title="审计日志" description="记录秘密查看、配置修改、用户管理和菜单同步操作。" />
      {mobile ? (
        <List
          dataSource={items}
          renderItem={(item) => (
            <List.Item>
              <List.Item.Meta
                title={item.action}
                description={(item.detail || '—') + ' · ' + new Date(item.created_at).toLocaleString()}
              />
              <Tag color={item.result === 'success' ? 'green' : 'red'}>{item.result}</Tag>
            </List.Item>
          )}
        />
      ) : (
        <Table
          rowKey="id"
          dataSource={items}
          pagination={{ pageSize: 30 }}
          columns={[
            { title: '时间', dataIndex: 'created_at', render: (value: string) => new Date(value).toLocaleString() },
            { title: '操作', dataIndex: 'action' },
            { title: '操作者', dataIndex: 'actor_user_id', ellipsis: true },
            { title: '目标用户', dataIndex: 'target_user_id', ellipsis: true },
            { title: '结果', dataIndex: 'result' },
            { title: '说明', dataIndex: 'detail' },
          ]}
        />
      )}
    </>
  );
}