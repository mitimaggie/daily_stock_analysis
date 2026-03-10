import type React from 'react';
import { BrowserRouter as Router, Routes, Route, useLocation } from 'react-router-dom';
import HomePage from './pages/HomePage';
import MarketPage from './pages/MarketPage';
import ProfilePage from './pages/ProfilePage';
import NotFoundPage from './pages/NotFoundPage';
import PortfolioPage from './pages/PortfolioPage';
import SimpleViewPage from './pages/SimpleViewPage';
import ScreenerPage from './pages/ScreenerPage';
import BottomNav from './components/layout/BottomNav';
import './App.css';

const AppLayout: React.FC = () => {
    const location = useLocation();
    const hideBottomNav = location.pathname.includes('/simple');

    return (
        <div className="min-h-screen bg-base">
            <Routes>
                <Route path="/" element={<MarketPage />} />
                <Route path="/screener" element={<ScreenerPage />} />
                <Route path="/analysis" element={<HomePage />} />
                <Route path="/portfolio" element={<PortfolioPage />} />
                <Route path="/portfolio/:code/simple" element={<SimpleViewPage />} />
                <Route path="/profile" element={<ProfilePage />} />
                <Route path="*" element={<NotFoundPage />} />
            </Routes>
            {!hideBottomNav && <BottomNav />}
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
