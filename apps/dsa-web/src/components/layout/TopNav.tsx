import type React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

interface TabItem {
  path: string;
  label: string;
  matchPrefix?: boolean;
}

const tabs: TabItem[] = [
  { path: '/', label: '市场' },
  { path: '/screener', label: '选股' },
  { path: '/analysis', label: '分析' },
  { path: '/portfolio', label: '持仓', matchPrefix: true },
  { path: '/profile', label: '我的' },
];

const TopNav: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();

  const isActive = (tab: TabItem) => {
    if (tab.matchPrefix) {
      return location.pathname === tab.path || location.pathname.startsWith(tab.path + '/');
    }
    return location.pathname === tab.path;
  };

  return (
    <nav className="fixed top-0 left-0 right-0 z-[60] header-bar" style={{ minHeight: '48px' }}>
      <div className="flex items-center h-12 px-4">
        {/* Logo */}
        <div className="flex items-center gap-2 flex-shrink-0 mr-6">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-cyan/80 to-cyan/40 flex items-center justify-center shadow-lg shadow-cyan/20">
            <svg className="w-3.5 h-3.5 text-white" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
            </svg>
          </div>
          <span className="text-[14px] font-bold text-primary/90 tracking-tight">DSA</span>
        </div>

        {/* 导航项 */}
        <div className="flex items-center gap-1">
          {tabs.map((tab) => {
            const active = isActive(tab);
            return (
              <button
                key={tab.path}
                type="button"
                onClick={() => navigate(tab.path)}
                className={`relative px-3 py-1.5 text-[14px] font-medium transition-colors rounded-md ${
                  active
                    ? 'text-cyan'
                    : 'text-muted hover:text-secondary hover:bg-black/[0.03]'
                }`}
              >
                {tab.label}
                {active && (
                  <span className="absolute bottom-0 left-1/2 -translate-x-1/2 w-5 h-[2px] bg-cyan rounded-full" />
                )}
              </button>
            );
          })}
        </div>
      </div>
    </nav>
  );
};

export default TopNav;
