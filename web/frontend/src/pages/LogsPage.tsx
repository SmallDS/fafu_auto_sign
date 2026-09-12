import { CopyOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons';
import { App as AntApp, Button, Card, Empty, Select, Space, Switch, Tag, Typography } from 'antd';
import dayjs from 'dayjs';
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { api, getErrorMessage } from '../api/client';
import { PageHeading } from '../components/PageHeading';
import { PageSkeleton } from '../components/PageSkeleton';
import type { LogEntry, LogLevel } from '../types/api';

const levelColors: Record<string, string> = {
  DEBUG: 'default',
  INFO: 'blue',
  WARNING: 'orange',
  ERROR: 'red',
  CRITICAL: 'magenta',
};

function entryText(entry: LogEntry): string {
  return `${entry.timestamp} ${entry.level.padEnd(8)} ${entry.logger ? `[${entry.logger}] ` : ''}${entry.message}`;
}

export function LogsPage(): ReactNode {
  const { message } = AntApp.useApp();
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [cursor, setCursor] = useState<string | number | null>(null);
  const [level, setLevel] = useState<LogLevel | undefined>();
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [followTail, setFollowTail] = useState(true);
  const [loading, setLoading] = useState(false);
  const cursorRef = useRef<string | number | null>(null);
  const viewportRef = useRef<HTMLDivElement>(null);

  useEffect(() => { cursorRef.current = cursor; }, [cursor]);

  const load = useCallback(async (resetCursor = false): Promise<void> => {
    setLoading(true);
    try {
      const response = await api.getLogs(resetCursor ? null : cursorRef.current, 200, level);
      setEntries((current) => response.reset || resetCursor ? response.entries : [...current, ...response.entries].slice(-2000));
      setCursor(response.next_cursor);
      cursorRef.current = response.next_cursor;
    } catch (error) {
      message.error(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [level, message]);

  useEffect(() => {
    setEntries([]);
    setCursor(null);
    cursorRef.current = null;
    void load(true);
  }, [level]);

  useEffect(() => {
    if (!autoRefresh) return undefined;
    const timer = window.setInterval(() => void load(), 3_000);
    return () => window.clearInterval(timer);
  }, [autoRefresh, load]);

  useEffect(() => {
    if (followTail && viewportRef.current) {
      viewportRef.current.scrollTop = viewportRef.current.scrollHeight;
    }
  }, [entries, followTail]);

  const copyLogs = async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(entries.map(entryText).join('\n'));
      message.success('日志已复制');
    } catch {
      message.error('浏览器未允许复制，请手动选择日志文本');
    }
  };

  if (loading && entries.length === 0) return <div className="page-container"><PageSkeleton variant="logs" /></div>;

  return (
    <div className="page-container">
      <PageHeading
        title="运行日志"
        description="日志每 3 秒增量读取一次，页面最多保留最近 2,000 条。"
        extra={
          <>
            <Button icon={<CopyOutlined />} disabled={!entries.length} onClick={() => void copyLogs()}>复制</Button>
            <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>刷新</Button>
          </>
        }
      />
      <Card className="content-card log-card">
        <div className="log-toolbar">
          <Space wrap>
            <Select
              allowClear
              placeholder="全部级别"
              value={level}
              onChange={setLevel}
              options={['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'].map((value) => ({ value, label: value }))}
            />
            <Space size={6}><Switch size="small" checked={autoRefresh} onChange={setAutoRefresh} /><Typography.Text>自动刷新</Typography.Text></Space>
            <Space size={6}><Switch size="small" checked={followTail} onChange={setFollowTail} /><Typography.Text>跟随最新</Typography.Text></Space>
          </Space>
          <Button type="text" icon={<DeleteOutlined />} onClick={() => setEntries([])}>清空页面</Button>
        </div>
        <div className="log-viewport" ref={viewportRef} aria-live="polite">
          {entries.length ? entries.map((entry, index) => (
            <div className={`log-line log-${entry.level.toLowerCase()}`} key={entry.id ?? `${entry.timestamp}-${index}`}>
              <time>{dayjs(entry.timestamp).isValid() ? dayjs(entry.timestamp).format('MM-DD HH:mm:ss.SSS') : entry.timestamp}</time>
              <Tag color={levelColors[entry.level] ?? 'default'}>{entry.level}</Tag>
              {entry.logger && <span className="log-logger">[{entry.logger}]</span>}
              <span className="log-message">{entry.message}</span>
            </div>
          )) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无日志" />
          )}
        </div>
      </Card>
    </div>
  );
}