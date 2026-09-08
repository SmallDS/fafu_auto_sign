import { Alert, Empty, Skeleton } from 'antd';
import type { ReactNode } from 'react';
import { getErrorMessage } from '../api/client';

interface AsyncStateProps {
  loading: boolean;
  error?: unknown;
  empty?: boolean;
  emptyText?: string;
  children: ReactNode;
}

export function AsyncState({ loading, error, empty, emptyText = '暂无数据', children }: AsyncStateProps): ReactNode {
  if (loading) return <Skeleton active paragraph={{ rows: 5 }} />;
  if (error) return <Alert type="error" showIcon message="加载失败" description={getErrorMessage(error)} />;
  if (empty) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText} />;
  return children;
}