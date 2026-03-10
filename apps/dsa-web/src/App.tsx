import type React from 'react';
import { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, useLocation } from 'react-router-dom';
import HomePage from './pages/HomePage';
import MarketPage from './pages/MarketPage';
import ProfilePage from './pages/ProfilePage';
import NotFoundPage from './pages/NotFoundPage';
import PortfolioPage from './pages/PortfolioPage';
import SimpleViewPage from './pages/SimpleViewPage';
import ScreenerPage from './pages/ScreenerPage';
import TopNav from './components/layout/TopNav';
import { CommandPalette } from './components/CommandPalette';
import './App.css';

const AppLayout: React.FC = () => {
    const location = useLocation();
    const hideNav = location.pathname.includes('/simple');
    const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);

    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            const target = e.target as HTMLElement;
            if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
                return;
            }
            if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
                e.preventDefault();
                setCommandPaletteOpen((prev) => !prev);
            }
        };
        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, []);

    return (
        <div className="min-h-screen bg-base">
            {!hideNav && <TopNav />}
            <CommandPalette open={commandPaletteOpen} onClose={() => setCommandPaletteOpen(false)} />
            <div className={hideNav ? '' : 'pt-12'}>
                <Routes>
                    <Route path="/" element={<MarketPage />} />
                    <Route path="/screener" element={<ScreenerPage />} />
                    <Route path="/analysis" element={<HomePage />} />
                    <Route path="/portfolio" element={<PortfolioPage />} />
                    <Route path="/portfolio/:code/simple" element={<SimpleViewPage />} />
                    <Route path="/profile" element={<ProfilePage />} />
                    <Route path="*" element={<NotFoundPage />} />
                </Routes>
            </div>
        </div>
    );
};

const App: React.FC = () => {
    return (
        <Router>
            <AppLayout />
        </Router>
    );
};

export default App;
