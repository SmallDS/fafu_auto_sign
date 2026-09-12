import { Card, Col, Row, Skeleton, Space } from 'antd';
import type { ReactNode } from 'react';

export type PageSkeletonVariant = 'dashboard' | 'form' | 'profile' | 'gallery' | 'list' | 'logs';

interface PageSkeletonProps {
  variant?: PageSkeletonVariant;
}

function HeadingSkeleton(): ReactNode {
  return (
    <div className="page-skeleton-heading">
      <Skeleton.Input active size="large" className="page-skeleton-title" />
      <Skeleton.Input active size="small" className="page-skeleton-description" />
    </div>
  );
}

function FormSkeleton(): ReactNode {
  return (
    <Space orientation="vertical" size={16} className="full-width">
      {[0, 1].map((index) => (
        <Card className="content-card section-card page-skeleton-card" key={index}>
          <Skeleton active title={{ width: '32%' }} paragraph={{ rows: index === 0 ? 3 : 4 }} />
        </Card>
      ))}
    </Space>
  );
}

function ProfileSkeleton(): ReactNode {
  return (
    <Space orientation="vertical" size={16} className="full-width">
      <Card className="content-card page-skeleton-card">
        <Skeleton active avatar={{ size: 56 }} title={{ width: '30%' }} paragraph={{ rows: 1 }} />
      </Card>
      {[0, 1, 2].map((index) => (
        <Card className="content-card page-skeleton-card" key={index}>
          <Skeleton active title={{ width: '28%' }} paragraph={{ rows: index === 2 ? 3 : 2 }} />
        </Card>
      ))}
    </Space>
  );
}

function GallerySkeleton(): ReactNode {
  return (
    <>
      <Card className="content-card section-card page-skeleton-card">
        <Skeleton active title={{ width: '36%' }} paragraph={{ rows: 3 }} />
      </Card>
      <Row gutter={[12, 12]}>
        {Array.from({ length: 8 }, (_, index) => (
          <Col xs={12} sm={8} md={6} xl={4} key={index}>
            <Card className="page-skeleton-image-card">
              <Skeleton.Image active />
              <Skeleton active title={{ width: '78%' }} paragraph={false} />
            </Card>
          </Col>
        ))}
      </Row>
    </>
  );
}

function DashboardSkeleton(): ReactNode {
  return (
    <Space orientation="vertical" size={16} className="full-width">
      <Row gutter={[16, 16]}>
        {Array.from({ length: 4 }, (_, index) => (
          <Col xs={12} md={6} key={index}>
            <Card className="metric-card page-skeleton-card"><Skeleton active title={{ width: '55%' }} paragraph={{ rows: 1 }} /></Card>
          </Col>
        ))}
      </Row>
      <Row gutter={[16, 16]}>
        {[0, 1].map((index) => (
          <Col xs={24} lg={12} key={index}>
            <Card className="content-card page-skeleton-card"><Skeleton active title={{ width: '30%' }} paragraph={{ rows: 4 }} /></Card>
          </Col>
        ))}
      </Row>
    </Space>
  );
}

function ListSkeleton({ dark = false }: { dark?: boolean }): ReactNode {
  return (
    <Card className={`content-card page-skeleton-card${dark ? ' page-skeleton-log-card' : ''}`}>
      <Skeleton active title={{ width: '22%' }} paragraph={{ rows: 7 }} />
    </Card>
  );
}

export function PageSkeleton({ variant = 'form' }: PageSkeletonProps): ReactNode {
  return (
    <div className={`page-skeleton page-skeleton-${variant}`} aria-busy="true" aria-label="页面加载中">
      <HeadingSkeleton />
      {variant === 'profile' ? <ProfileSkeleton />
        : variant === 'gallery' ? <GallerySkeleton />
          : variant === 'dashboard' ? <DashboardSkeleton />
            : variant === 'list' ? <ListSkeleton />
              : variant === 'logs' ? <ListSkeleton dark />
                : <FormSkeleton />}
    </div>
  );
}