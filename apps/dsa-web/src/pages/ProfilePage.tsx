import type React from 'react';
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { tradeLogApi, type TradeLogStats } from '../api/tradeLog';
import apiClient from '../api/index';
import { configApi, type ConfigFieldSchema } from '../api/config';
import { Button } from '../components/common/Button';
import { Select } from '../components/common/Select';

const ChevronRight = () => (
  <svg className="w-4 h-4 text-muted/70" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
  </svg>
);

const StatCell: React.FC<{ label: string; value: string; sub?: string; color?: string }> = ({ label, value, sub, color = 'text-primary/80' }) => (
  <div className="text-center">
    <div className="text-[10px] text-muted mb-1">{label}</div>
    <div className={`text-[18px] font-bold font-mono ${color}`}>{value}</div>
    {sub && <div className="text-[10px] text-muted mt-0.5">{sub}</div>}
  </div>
);

// ====== 基础配置组件 ======

const Toggle: React.FC<{ checked: boolean; onChange: (checked: boolean) => void }> = ({ checked, onChange }) => (
  <button
    type="button"
    onClick={() => onChange(!checked)}
    className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none ${
      checked ? 'bg-cyan-500' : 'bg-black/[0.1]'
    }`}
  >
    <span
      className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
        checked ? 'translate-x-4' : 'translate-x-1'
      } shadow`}
    />
  </button>
);

const PasswordInput: React.FC<{ value: string; onChange: (v: string) => void; placeholder?: string }> = ({ value, onChange, placeholder }) => {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <input
        type={show ? 'text' : 'password'}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="input-terminal pr-10"
      />
      <button
        type="button"
        onClick={() => setShow(!show)}
        className="absolute inset-y-0 right-0 px-3 flex items-center text-muted hover:text-primary transition"
        title={show ? '隐藏' : '显示'}
      >
        {show ? (
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" /></svg>
        ) : (
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
        )}
      </button>
    </div>
  );
};

const GROUP1_KEYS = [
  'STOCK_LIST',
  'PORTFOLIO_SIZE',
  'TIME_HORIZON',
  'SIGNAL_CONFIRM_DAYS',
  'ENABLE_ALERT_MONITOR',
  'FAST_MODE'
];

const GROUP2_KEYS = [
  'GEMINI_API_KEY',
  'GEMINI_MODEL',
  'SCHEDULE_ENABLED',
  'SCHEDULE_TIME',
  'ENABLE_REALTIME_QUOTE',
  'ENABLE_CHIP_DISTRIBUTION',
  'ENABLE_MARGIN_HISTORY'
];

const ProfilePage: React.FC = () => {
  const navigate = useNavigate();
  const [stats, setStats] = useState<TradeLogStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [apiHealthy, setApiHealthy] = useState<boolean | null>(null);
  
  // 配置状态
  const [showConfig, setShowConfig] = useState(false);
  const [configSchema, setConfigSchema] = useState<Record<string, ConfigFieldSchema>>({});
  const [configValues, setConfigValues] = useState<Record<string, string>>({});
  const [loadingConfig, setLoadingConfig] = useState(false);
  const [savingConfig, setSavingConfig] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const fetchStats = async () => {
      try {
        const data = await tradeLogApi.stats();
        if (!cancelled) setStats(data);
      } catch {
        if (!cancelled) setStatsError('加载失败');
      } finally {
        if (!cancelled) setStatsLoading(false);
      }
    };

    const checkHealth = async () => {
      try {
        const res = await apiClient.get('/api/health', { timeout: 5000 });
        if (!cancelled) setApiHealthy(res.status === 200);
      } catch {
        if (!cancelled) setApiHealthy(false);
      }
    };

    fetchStats();
    checkHealth();

    return () => { cancelled = true; };
  }, []);

  const fetchConfig = useCallback(async () => {
    setLoadingConfig(true);
    try {
      const [schemaRes, valuesRes] = await Promise.all([
        configApi.getSchema(),
        configApi.getValues()
      ]);
      if (schemaRes.success) {
        const flatSchema: Record<string, ConfigFieldSchema> = {};
        Object.values(schemaRes.schema).forEach(group => {
          Object.assign(flatSchema, group);
        });
        setConfigSchema(flatSchema);
      }
      if (valuesRes.success) {
        setConfigValues(valuesRes.values);
      }
    } catch {
      showToast('获取配置失败');
    } finally {
      setLoadingConfig(false);
    }
  }, [showToast]);

  useEffect(() => {
    if (showConfig) {
      fetchConfig();
    }
  }, [showConfig, fetchConfig]);

  const showToast = useCallback((msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3000);
  }, []);

  const handleConfigChange = (key: string, value: string) => {
    setConfigValues(prev => ({ ...prev, [key]: value }));
  };

  const handleSaveConfig = async () => {
    setSavingConfig(true);
    try {
      const updates = { ...configValues };
      Object.keys(updates).forEach(key => {
        if (updates[key] && updates[key].includes('****')) {
          delete updates[key];
        }
      });
      const res = await configApi.update(updates);
      if (res.success) {
        showToast('保存成功');
        await fetchConfig(); // 刷新掩码
      } else {
        showToast(`保存失败: ${res.error}`);
      }
    } catch {
      showToast('保存出错');
    } finally {
      setSavingConfig(false);
    }
  };

  const handleRestoreDefault = () => {
    if (window.confirm('确定要恢复这些配置的默认值吗？未保存的修改将丢失。')) {
      const defaultValues = { ...configValues };
      [...GROUP1_KEYS, ...GROUP2_KEYS].forEach(key => {
        const schema = configSchema[key];
        if (schema) {
          if (schema.default !== undefined) {
            defaultValues[key] = schema.default;
          } else if (schema.type === 'boolean') {
            defaultValues[key] = 'false';
          } else {
            defaultValues[key] = '';
          }
        }
      });
      setConfigValues(defaultValues);
      showToast('已恢复默认值，请点击保存生效');
    }
  };

  const renderField = (key: string) => {
    const schema = configSchema[key];
    if (!schema) return null;

    const val = configValues[key] ?? schema.default ?? '';

    return (
      <div key={key} className="flex flex-col gap-1.5 py-1">
        <div className="flex items-center justify-between">
          <label className="text-[13px] font-medium text-primary/80">{schema.label}</label>
          {schema.type === 'boolean' && (
            <Toggle
              checked={String(val).toLowerCase() === 'true'}
              onChange={(checked) => handleConfigChange(key, checked ? 'true' : 'false')}
            />
          )}
        </div>
        {schema.description && (
          <div className="text-[11px] text-muted leading-snug">{schema.description}</div>
        )}
        <div className="mt-1">
          {schema.type === 'text' || schema.type === 'number' ? (
            <input
              type={schema.type}
              value={val}
              onChange={(e) => handleConfigChange(key, e.target.value)}
              placeholder={schema.placeholder}
              className="input-terminal"
            />
          ) : schema.type === 'password' ? (
            <PasswordInput
              value={val}
              onChange={(v) => handleConfigChange(key, v)}
              placeholder={schema.placeholder}
            />
          ) : schema.type === 'select' ? (
            <Select
              value={val}
              onChange={(v) => handleConfigChange(key, v)}
              options={(schema.options || []).map(o => ({ label: o, value: o }))}
              className="w-full"
            />
          ) : null}
        </div>
      </div>
    );
  };

  const winRate = stats && stats.totalTrades > 0
    ? ((stats.profitCount / stats.reviewedCount) * 100)
    : null;

  const menuItems = [
    { icon: '📋', label: '分析历史', desc: '查看所有分析报告', onClick: () => navigate('/analysis') },
    { icon: '📊', label: '回测工具', desc: '策略回测验证', onClick: () => navigate('/analysis?tab=backtest') },
  ];

  return (
    <div className="min-h-screen pb-6 relative">
      <div className={`mx-auto px-4 py-4 space-y-4 ${showConfig ? 'max-w-5xl' : 'max-w-3xl'}`}>
        
        {/* Toast 提示 */}
        {toastMessage && (
          <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 bg-gray-900 text-white px-4 py-2 rounded-lg shadow-lg text-[13px] animate-slide-up">
            {toastMessage}
          </div>
        )}

        {!showConfig ? (
          // ================= 主界面 =================
          <>
            <h1 className="text-[18px] font-bold text-primary">我的</h1>

            {/* 本月战绩卡片 */}
            <div className="terminal-card p-4">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-[14px]">📈</span>
                <span className="text-[13px] font-medium text-primary/70">本月战绩</span>
                {stats && stats.totalTrades > 0 && (
                  <span className="text-[10px] text-muted/70 ml-auto font-mono">{stats.totalTrades}笔交易</span>
                )}
              </div>

              {statsLoading ? (
                <div className="grid grid-cols-3 gap-3 animate-pulse">
                  {[1, 2, 3].map(i => (
                    <div key={i} className="text-center">
                      <div className="h-3 w-10 bg-black/[0.03] rounded mx-auto mb-2" />
                      <div className="h-6 w-14 bg-black/[0.03] rounded mx-auto" />
                    </div>
                  ))}
                </div>
              ) : statsError ? (
                <div className="text-center py-4">
                  <p className="text-[12px] text-danger">{statsError}</p>
                </div>
              ) : !stats || stats.totalTrades === 0 ? (
                <div className="text-center py-6">
                  <p className="text-[13px] text-muted">暂无交易记录</p>
                  <p className="text-[11px] text-muted/50 mt-1">在持仓页面记录交易后，这里会显示战绩统计</p>
                </div>
              ) : (
                <div className="grid grid-cols-3 gap-3">
                  <StatCell
                    label="胜率"
                    value={winRate != null && stats.reviewedCount > 0 ? `${winRate.toFixed(0)}%` : '--'}
                    sub={stats.reviewedCount > 0 ? `${stats.profitCount}胜/${stats.lossCount}负` : '暂无复盘'}
                    color={winRate != null && winRate >= 50 ? 'text-red-600' : winRate != null ? 'text-emerald-600' : 'text-muted'}
                  />
                  <StatCell
                    label="总盈亏"
                    value={stats.totalPnl !== 0 ? `${stats.totalPnl >= 0 ? '+' : ''}${(stats.totalPnl / 10000).toFixed(2)}万` : '--'}
                    sub={stats.avgPnlPct !== 0 ? `均${stats.avgPnlPct >= 0 ? '+' : ''}${stats.avgPnlPct.toFixed(1)}%` : undefined}
                    color={stats.totalPnl > 0 ? 'text-red-600' : stats.totalPnl < 0 ? 'text-emerald-600' : 'text-muted'}
                  />
                  <StatCell
                    label="纪律执行"
                    value={stats.followedAdviceCount > 0 ? `${((stats.followedAdviceCount / stats.totalTrades) * 100).toFixed(0)}%` : '--'}
                    sub={stats.followedAdviceCount > 0 ? `${stats.followedAdviceCount}/${stats.totalTrades}遵循` : '暂无数据'}
                    color="text-cyan"
                  />
                </div>
              )}
            </div>

            {/* 功能入口列表 */}
            <div className="terminal-card overflow-hidden">
              {menuItems.map((item) => (
                <button
                  key={item.label}
                  type="button"
                  onClick={item.onClick}
                  className={`w-full flex items-center gap-3 px-4 py-3.5 hover:bg-black/[0.02] transition text-left border-b border-black/[0.05]`}
                >
                  <span className="text-[16px] flex-shrink-0">{item.icon}</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-[13px] text-primary/80 font-medium">{item.label}</div>
                    <div className="text-[11px] text-muted">{item.desc}</div>
                  </div>
                  <ChevronRight />
                </button>
              ))}

              <button
                type="button"
                onClick={() => setShowConfig(true)}
                className="w-full flex items-center gap-3 px-4 py-3.5 hover:bg-black/[0.02] transition text-left"
              >
                <span className="text-[16px] flex-shrink-0">⚙️</span>
                <div className="flex-1 min-w-0">
                  <div className="text-[13px] text-primary/80 font-medium">系统设置</div>
                  <div className="text-[11px] text-muted">自定义你的散户炒股助手</div>
                </div>
                <ChevronRight />
              </button>
            </div>

            <p className="text-[10px] text-muted/40 text-center pt-2">
              DSA · A股散户智能分析助手
            </p>
          </>
        ) : (
          // ================= 配置界面 =================
          <div className="animate-slide-in-right">
            <div className="flex items-center gap-3 mb-4">
              <button
                onClick={() => setShowConfig(false)}
                className="p-1 -ml-1 text-muted hover:text-primary transition"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                </svg>
              </button>
              <h1 className="text-[18px] font-bold text-primary">系统设置</h1>
            </div>

            {loadingConfig ? (
              <div className="flex justify-center py-10">
                <span className="animate-spin h-6 w-6 text-cyan border-2 border-t-transparent border-current rounded-full"></span>
              </div>
            ) : Object.keys(configSchema).length === 0 ? (
              <div className="terminal-card p-8 text-center">
                <div className="text-[24px] mb-2">🔌</div>
                <div className="text-[13px] text-danger font-medium mb-1">无法加载配置项</div>
                <div className="text-[12px] text-muted mb-4">请确保后端 API 服务已正常启动</div>
                <Button variant="secondary" onClick={fetchConfig} className="mx-auto">
                  点击重试
                </Button>
              </div>
            ) : (
              <div className="space-y-6">
                
                {/* 散户实战组 */}
                <div className="terminal-card p-4 space-y-4">
                  <h2 className="text-[14px] font-bold text-primary flex items-center gap-2">
                    <span className="w-1 h-3 bg-cyan-500 rounded-full" />
                    散户实战
                  </h2>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-4">
                    {GROUP1_KEYS.map(key => renderField(key))}
                  </div>
                </div>

                {/* 系统基础组 */}
                <div className="terminal-card p-4 space-y-4">
                  <h2 className="text-[14px] font-bold text-primary flex items-center gap-2">
                    <span className="w-1 h-3 bg-purple-500 rounded-full" />
                    系统基础
                  </h2>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-4">
                    {GROUP2_KEYS.map(key => renderField(key))}
                  </div>
                </div>

                {/* 只读信息：版本/API状态 */}
                <div className="terminal-card p-4 space-y-2.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[12px] text-muted">版本号</span>
                    <span className="text-[12px] text-secondary font-mono">v1.0.0</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[12px] text-muted">API 状态</span>
                    <span className="flex items-center gap-1.5">
                      <span className={`w-2 h-2 rounded-full ${
                        apiHealthy === null ? 'bg-muted/70 animate-pulse' : apiHealthy ? 'bg-emerald-400' : 'bg-red-400'
                      }`} />
                      <span className={`text-[12px] font-mono ${
                        apiHealthy === null ? 'text-muted' : apiHealthy ? 'text-emerald-400' : 'text-red-400'
                      }`}>
                        {apiHealthy === null ? '检查中' : apiHealthy ? '正常' : '离线'}
                      </span>
                    </span>
                  </div>
                </div>

                {/* 操作按钮区 */}
                <div className="flex gap-3 pt-2">
                  <Button
                    variant="primary"
                    className="flex-1"
                    onClick={handleSaveConfig}
                    isLoading={savingConfig}
                  >
                    保存配置
                  </Button>
                  <Button
                    variant="secondary"
                    className="flex-1"
                    onClick={handleRestoreDefault}
                    disabled={savingConfig}
                  >
                    恢复默认
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default ProfilePage;
