import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App as AntApp, ConfigProvider } from 'antd';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type { Settings } from '../types/api';
import { ImagesPage } from './ImagesPage';

vi.mock('../api/client', () => ({
  api: {
    listImages: vi.fn(),
    getSettings: vi.fn(),
    uploadImages: vi.fn(),
    updateSettings: vi.fn(),
    deleteImage: vi.fn(),
    imageUrl: vi.fn(),
  },
  getErrorMessage: (error: unknown) => error instanceof Error ? error.message : '错误',
}));

const mockedApi = vi.mocked(api);
const settings: Settings = {
  configured: true,
  version: 1,
  has_user_token: true,
  user_token_masked: '2_ab****yz',
  jitter: 0.00005,
  heartbeat_interval: 900,
  task_keywords: [],
  image_mode: 'library',
  selected_image_id: null,
  worker_enabled: true,
  notification_enabled: true,
};

describe('ImagesPage upload entrances', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedApi.listImages.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 24 });
    mockedApi.getSettings.mockResolvedValue(settings);
  });

  afterEach(() => cleanup());

  it('加载完成前显示图库页面骨架', () => {
    mockedApi.listImages.mockReturnValue(new Promise(() => undefined));
    render(<ConfigProvider><AntApp><ImagesPage /></AntApp></ConfigProvider>);
    expect(screen.getByLabelText('页面加载中')).toHaveAttribute('aria-busy', 'true');
  });

  it('将拍照与选择图片拆成两个独立文件入口', async () => {
    const { container } = render(<ConfigProvider><AntApp><ImagesPage /></AntApp></ConfigProvider>);
    await screen.findByRole('heading', { name: '图片管理' });

    expect(screen.getByRole('button', { name: /拍照$/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /选择图片$/ })).toBeInTheDocument();
    expect(screen.queryByText('拍照 / 选择')).not.toBeInTheDocument();

    const cameraInput = container.querySelector<HTMLInputElement>('input[type="file"][capture="environment"]');
    expect(cameraInput).not.toBeNull();
    expect(cameraInput?.multiple).toBe(false);
    const galleryInput = [...container.querySelectorAll<HTMLInputElement>('input[type="file"]')]
      .find((input) => !input.hasAttribute('capture') && input.multiple);
    expect(galleryInput).toBeDefined();
  });

  it('拍照选择的文件会进入统一待上传列表', async () => {
    const { container } = render(<ConfigProvider><AntApp><ImagesPage /></AntApp></ConfigProvider>);
    await screen.findByRole('heading', { name: '图片管理' });
    const cameraInput = container.querySelector<HTMLInputElement>('input[type="file"][capture="environment"]');
    const file = new File(['image'], 'camera.jpg', { type: 'image/jpeg' });

    fireEvent.change(cameraInput!, { target: { files: [file] } });
    await waitFor(() => expect(screen.getByText('已选择 1 张')).toBeInTheDocument());
  });
});
