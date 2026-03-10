import type React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

const TrendingUpIcon = () => (
  <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
  </svg>
);

const SearchIcon = () => (
  <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
  </svg>
);

const BriefcaseIcon = () => (
  <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
  </svg>
);

const FilterIcon = () => (
  <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
  </svg>
);

const UserIcon = () => (
  <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
  </svg>
);

interface TabItem {
  path: string;
  label: string;
  icon: React.ReactNode;
  matchPrefix?: boolean;
}

const tabs: TabItem[] = [
  { path: '/', label: '市场', icon: <TrendingUpIcon /> },
  { path: '/screener', label: '选股', icon: <FilterIcon /> },
  { path: '/analysis', label: '分析', icon: <SearchIcon /> },
  { path: '/portfolio', label: '持仓', icon: <BriefcaseIcon />, matchPrefix: true },
  { path: '/profile', label: '我的', icon: <UserIcon /> },
];

const BottomNav: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();

  const isActive = (tab: TabItem) => {
    if (tab.matchPrefix) {
      return location.pathname === tab.path || location.pathname.startsWith(tab.path + '/');
    }
    return location.pathname === tab.path;
  };

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 bg-card/95 backdrop-blur-xl border-t border-border safe-area-bottom">
      <div className="flex items-center justify-around h-14 max-w-lg mx-auto">
        {tabs.map((tab) => {
          const active = isActive(tab);
          return (
            <button
              key={tab.path}
              type="button"
              onClick={() => navigate(tab.path)}
              className={`flex flex-col items-center justify-center flex-1 h-full gap-0.5 transition-colors ${
                active
                  ? 'text-cyan'
                  : 'text-muted hover:text-secondary'
              }`}
            >
              <span className={active ? 'drop-shadow-[0_0_6px_rgba(0,212,255,0.4)]' : ''}>
                {tab.icon}
              </span>
              <span className={`text-[10px] font-medium ${active ? 'text-cyan' : ''}`}>
                {tab.label}
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
};

export default BottomNav;
