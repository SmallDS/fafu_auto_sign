import { Card, Col, Row, Statistic, Typography } from 'antd';
import { useEffect, useState, type ReactNode } from 'react';
import { api } from '../api/client';
import { PageHeading } from '../components/PageHeading';

export function AdminDashboardPage(): ReactNode {
  const [stats, setStats] = useState({ users: 0, pending: 0, active: 0, queued_jobs: 0 });
  useEffect(() => { void api.getAdminStats().then(setStats); }, []);

  return (
    <div className="page-container">
      <PageHeading title="管理概览" description="用户、审核和全局签到队列状态。" />
      <Row gutter={[16, 16]}>
        <Col xs={12} md={6}><Card className="metric-card"><Statistic title="用户" value={stats.users} /></Card></Col>
        <Col xs={12} md={6}><Card className="metric-card"><Statistic title="待审核" value={stats.pending} /></Card></Col>
        <Col xs={12} md={6}><Card className="metric-card"><Statistic title="活跃" value={stats.active} /></Card></Col>
        <Col xs={12} md={6}><Card className="metric-card"><Statistic title="排队任务" value={stats.queued_jobs} /></Card></Col>
      </Row>
      <Card className="content-card admin-queue-card">
        <Typography.Paragraph type="secondary">
          所有用户的签到任务按优先级进入同一个持久队列，并由单执行器串行处理。
        </Typography.Paragraph>
      </Card>
    </div>
  );
}
