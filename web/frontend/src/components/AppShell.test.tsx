import { fireEvent, render, screen } from '@testing-library/react';
import { ConfigProvider } from 'antd';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { AppShell } from './AppShell';
import { RunResultTag, WorkerStatusTag } from './StatusTag';

describe('AppShell', () => {
  it('在移动断点显示抽屉导航并渲染内容', () => {
    render(
      <ConfigProvider>
        <MemoryRouter initialEntries={['/dashboard']}>
          <AppShell><div>页面内容</div></AppShell>
        </MemoryRouter>
      </ConfigProvider>,
    );

    expect(screen.getByText('页面内容')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '打开导航' }));
    expect(screen.getByText('概览')).toBeInTheDocument();
    expect(screen.getByText('设置')).toBeInTheDocument();
  });

  it('显示本地化状态', () => {
    render(<><WorkerStatusTag state="executing" /><RunResultTag result="partial" /></>);
    expect(screen.getByText('正在检查')).toBeInTheDocument();
    expect(screen.getByText('部分成功')).toBeInTheDocument();
  });
});