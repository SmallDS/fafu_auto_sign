import { CameraOutlined, CheckOutlined, DeleteOutlined, InboxOutlined, UploadOutlined } from '@ant-design/icons';
import {
  App as AntApp,
  Button,
  Card,
  Col,
  Empty,
  Image,
  Pagination,
  Row,
  Segmented,
  Space,
  Tag,
  Typography,
  Upload,
} from 'antd';
import type { UploadFile } from 'antd';
import { useEffect, useState, type ReactNode } from 'react';
import { api, getErrorMessage } from '../api/client';
import { PageHeading } from '../components/PageHeading';
import type { ImageCategory, ImageRecord, Settings } from '../types/api';

const { Dragger } = Upload;
const PAGE_SIZE = 24;
const ACCEPTED = '.jpg,.jpeg,.png,.gif,.webp';

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / 1024 / 1024).toFixed(1)} MiB`;
}

export function ImagesPage(): ReactNode {
  const { message, modal } = AntApp.useApp();
  const [category, setCategory] = useState<ImageCategory>('library');
  const [images, setImages] = useState<ImageRecord[]>([]);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [fileList, setFileList] = useState<UploadFile[]>([]);

  const load = async (requestedPage = page, requestedCategory = category): Promise<void> => {
    setLoading(true);
    try {
      const [result, nextSettings] = await Promise.all([
        api.listImages(requestedPage, PAGE_SIZE, requestedCategory),
        api.getSettings(),
      ]);
      setImages(result.items);
      setTotal(result.total);
      setSettings(nextSettings);
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load(page, category);
  }, [page, category]);

  const upload = async (): Promise<void> => {
    const files = fileList.flatMap((item) => item.originFileObj ? [item.originFileObj] : []);
    if (!files.length) {
      message.warning('请先选择图片');
      return;
    }
    setUploading(true);
    try {
      await api.uploadImages(files, category);
      setFileList([]);
      message.success(`已上传 ${files.length} 张图片`);
      setPage(1);
      await load(1, category);
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setUploading(false);
    }
  };

  const selectImage = async (image: ImageRecord): Promise<void> => {
    try {
      const next = await api.updateSettings({ image_mode: 'single', selected_image_id: image.id });
      setSettings(next);
      message.success('已设为固定签到图片');
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  const removeImage = (image: ImageRecord): void => {
    modal.confirm({
      title: '确认删除图片？',
      content: image.original_name,
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          await api.deleteImage(image.id);
          message.success('图片已删除');
          const nextPage = images.length === 1 && page > 1 ? page - 1 : page;
          setPage(nextPage);
          await load(nextPage, category);
        } catch (error) {
          message.error(getErrorMessage(error));
        }
      },
    });
  };

  return (
    <div className="page-container">
      <PageHeading title="图片管理" description="维护持久图库与最新图片队列，单张图片最大 10 MiB。" />
      <Card className="content-card upload-card">
        <Segmented<ImageCategory>
          block
          value={category}
          options={[{ label: '持久图库', value: 'library' }, { label: '最新队列', value: 'latest' }]}
          onChange={(value) => { setCategory(value); setPage(1); setFileList([]); }}
        />
        <Dragger
          multiple
          maxCount={10}
          accept={ACCEPTED}
          capture="environment"
          fileList={fileList}
          beforeUpload={(file) => {
            if (file.size > 10 * 1024 * 1024) {
              message.error(`${file.name} 超过 10 MiB`);
              return Upload.LIST_IGNORE;
            }
            return false;
          }}
          onChange={({ fileList: next }) => setFileList(next.slice(-10))}
          onRemove={(file) => { setFileList((items) => items.filter((item) => item.uid !== file.uid)); return true; }}
          disabled={uploading}
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p className="ant-upload-text">点击、拖放或拍照选择图片</p>
          <p className="ant-upload-hint">支持 JPG、JPEG、PNG、GIF、WEBP，一次最多 10 张</p>
        </Dragger>
        <div className="upload-actions">
          <Typography.Text type="secondary">已选择 {fileList.length} 张</Typography.Text>
          <Space wrap>
            <Button icon={<CameraOutlined />} onClick={() => document.querySelector<HTMLElement>('.ant-upload input')?.click()}>拍照 / 选择</Button>
            <Button type="primary" icon={<UploadOutlined />} loading={uploading} disabled={!fileList.length} onClick={() => void upload()}>开始上传</Button>
          </Space>
        </div>
      </Card>

      <div className="image-list-heading">
        <Typography.Title level={4}>{category === 'library' ? '持久图库' : '最新图片队列'}</Typography.Title>
        <Typography.Text type="secondary">共 {total} 张</Typography.Text>
      </div>

      {loading ? (
        <Row gutter={[16, 16]}>{Array.from({ length: 8 }, (_, index) => <Col xs={12} sm={8} md={6} xl={4} key={index}><Card loading /></Col>)}</Row>
      ) : images.length === 0 ? (
        <Card><Empty description="这里还没有图片" /></Card>
      ) : (
        <>
          <Image.PreviewGroup>
            <Row gutter={[12, 12]}>
              {images.map((item) => {
                const selected = settings?.selected_image_id === item.id;
                return (
                  <Col xs={12} sm={8} md={6} xl={4} key={item.id}>
                    <Card
                      className={`image-card${selected ? ' image-card-selected' : ''}`}
                      cover={<div className="image-cover"><Image src={api.imageUrl(item.id)} alt={item.original_name} fallback="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='240' height='180'%3E%3Crect width='100%25' height='100%25' fill='%23f2f4f7'/%3E%3C/svg%3E" /></div>}
                      actions={[
                        <Button
                          type="text"
                          size="small"
                          aria-label={`选择 ${item.original_name}`}
                          icon={<CheckOutlined />}
                          disabled={selected || category !== 'library'}
                          onClick={() => void selectImage(item)}
                        >
                          {category !== 'library' ? '队列图片' : selected ? '已选择' : '设为固定'}
                        </Button>,
                        <Button danger type="text" size="small" aria-label={`删除 ${item.original_name}`} icon={<DeleteOutlined />} onClick={() => removeImage(item)}>删除</Button>,
                      ]}
                    >
                      <Card.Meta
                        title={<span title={item.original_name}>{item.original_name}</span>}
                        description={<Space size={4} wrap>{selected && <Tag color="success">当前固定图</Tag>}<span>{formatBytes(item.size)}</span></Space>}
                      />
                    </Card>
                  </Col>
                );
              })}
            </Row>
          </Image.PreviewGroup>
          {total > PAGE_SIZE && (
            <Pagination className="center-pagination" current={page} pageSize={PAGE_SIZE} total={total} showSizeChanger={false} onChange={setPage} />
          )}
        </>
      )}
    </div>
  );
}
