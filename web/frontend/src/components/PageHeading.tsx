import { Space, Typography } from 'antd';
import type { ReactNode } from 'react';

interface PageHeadingProps {
  title: string;
  description: string;
  extra?: ReactNode;
}

export function PageHeading({ title, description, extra }: PageHeadingProps): ReactNode {
  return (
    <div className="page-heading">
      <div className="page-heading-copy">
        <Typography.Title level={2}>{title}</Typography.Title>
        <Typography.Text type="secondary">{description}</Typography.Text>
      </div>
      {extra && <Space wrap className="page-heading-actions">{extra}</Space>}
    </div>
  );
}