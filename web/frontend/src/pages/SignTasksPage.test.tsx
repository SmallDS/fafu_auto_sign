import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App as AntApp, ConfigProvider } from 'antd';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import { SignTasksPage } from './SignTasksPage';

vi.mock('../api/client', () => ({
  api: {
    listSignTasks: vi.fn(),
    getSignTask: vi.fn(),
    getMapConfig: vi.fn(),
    submitSignTask: vi.fn(),
  },
  getErrorMessage: (error: unknown) => error instanceof Error ? error.message : '错误',
}));

const mockedApi = vi.mocked(api);

afterEach(() => cleanup());

function renderPage() {
  return render(
    <ConfigProvider>
      <AntApp><SignTasksPage /></AntApp>
    </ConfigProvider>,
  );
}

describe('SignTasksPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    const now = Date.now();
    mockedApi.listSignTasks.mockResolvedValue({
      items: [{ id: '123', name: '课堂签到', begin_time: now - 60_000, end_time: now + 60_000 }],
      total: null,
      page: 1,
      page_size: 20,
      has_more: true,
    });
    mockedApi.getSignTask.mockResolvedValue({
      task_id: 123,
      position_id: 456,
      base_lng: 118.1,
      base_lat: 25.1,
      position_name: '宿舍楼',
    });
    mockedApi.getMapConfig.mockResolvedValue({
      enabled: false,
      js_key: null,
      jitter: 0.00005,
      service_host: '/_AMapService',
    });
    mockedApi.submitSignTask.mockResolvedValue({
      id: 1,
      trigger: 'manual',
      config_version: 1,
      started_at: new Date().toISOString(),
      finished_at: new Date().toISOString(),
      result: 'success',
      task_count: 1,
      success_count: 1,
      failure_count: 0,
      summary: '签到成功',
      details: [],
    });
  });

  it('浏览详情并显示任务地图', async () => {
    renderPage();
    expect(await screen.findByText('课堂签到')).toBeInTheDocument();
    expect(screen.getByText('下一页')).toBeEnabled();

    fireEvent.click(screen.getByRole('button', { name: /详情/ }));
    expect(await screen.findByText('宿舍楼')).toBeInTheDocument();
    expect(mockedApi.getSignTask).toHaveBeenCalledWith('123');
    expect(mockedApi.getMapConfig).toHaveBeenCalledOnce();
    expect(await screen.findByText('高德地图未启用')).toBeInTheDocument();
    expect(screen.queryByText('本次签到参数')).not.toBeInTheDocument();
  });

  it('单次 GPS 偏移只随本次签到请求提交', async () => {
    renderPage();
    expect(await screen.findByText('课堂签到')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /签到$/ }));
    expect(await screen.findByText('本次签到参数')).toBeInTheDocument();

    const jitter = screen.getByRole('spinbutton', { name: '本次 GPS 随机偏移' });
    fireEvent.change(jitter, { target: { value: '0.00012' } });
    fireEvent.click(screen.getByRole('button', { name: /提交本次签到/ }));
    fireEvent.click(await screen.findByRole('button', { name: '确认签到' }));

    await waitFor(() => expect(mockedApi.submitSignTask).toHaveBeenCalledWith(
      '123',
      1,
      20,
      { location_mode: 'rule_jitter', jitter: 0.00012 },
    ));
    await waitFor(() => expect(mockedApi.listSignTasks).toHaveBeenCalledTimes(2));
  });

  it('支持填写 GCJ-02 手动坐标并作为单次选点提交', async () => {
    renderPage();
    expect(await screen.findByText('课堂签到')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /签到$/ }));
    expect(await screen.findByText('本次签到参数')).toBeInTheDocument();
    fireEvent.click(screen.getByText('手动选点'));

    fireEvent.change(screen.getByRole('spinbutton', { name: '手动经度' }), {
      target: { value: '118.123456' },
    });
    fireEvent.change(screen.getByRole('spinbutton', { name: '手动纬度' }), {
      target: { value: '25.654321' },
    });
    fireEvent.click(screen.getByRole('button', { name: /提交本次签到/ }));
    fireEvent.click(await screen.findByRole('button', { name: '确认签到' }));

    await waitFor(() => expect(mockedApi.submitSignTask).toHaveBeenCalledWith(
      '123',
      1,
      20,
      {
        location_mode: 'manual_point',
        longitude: 118.123456,
        latitude: 25.654321,
      },
    ));
  }, 10000);
});
