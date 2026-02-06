# -*- coding: utf-8 -*-
"""
===================================
A股自选股智能分析系统 - 存储层
===================================

职责：
1. 管理 SQLite 数据库连接（单例模式）
2. 定义 ORM 数据模型
3. 提供数据存取接口
4. 实现智能更新逻辑（断点续传）
"""

import atexit
import hashlib
import json
import logging
import re
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from pathlib import Path

import pandas as pd
from sqlalchemy import (
    create_engine,
    Column,
    String,
    Float,
    Date,
    DateTime,
    Integer,
    Index,
    UniqueConstraint,
    Text,
    select,
    and_,
    desc,
    text
)
from sqlalchemy.orm import (
    declarative_base,
    sessionmaker,
    Session,
)
from sqlalchemy.exc import IntegrityError

from src.config import get_config

logger = logging.getLogger(__name__)

# SQLAlchemy ORM 基类
Base = declarative_base()

if TYPE_CHECKING:
    from src.search_service import SearchResponse


# === 数据模型定义 ===

class StockDaily(Base):
    """
    股票日线数据模型
    """
    __tablename__ = 'stock_daily'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)
    amount = Column(Float)
    pct_chg = Column(Float)
    ma5 = Column(Float)
    ma10 = Column(Float)
    ma20 = Column(Float)
    volume_ratio = Column(Float)
    data_source = Column(String(50))
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    __table_args__ = (
        UniqueConstraint('code', 'date', name='uix_code_date'),
        Index('ix_code_date', 'code', 'date'),
    )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'code': self.code,
            'date': self.date,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
            'amount': self.amount,
            'pct_chg': self.pct_chg,
            'ma5': self.ma5,
            'ma10': self.ma10,
            'ma20': self.ma20,
            'volume_ratio': self.volume_ratio,
            'data_source': self.data_source,
        }


class NewsIntel(Base):
    """新闻情报数据模型"""
    __tablename__ = 'news_intel'

    id = Column(Integer, primary_key=True, autoincrement=True)
    query_id = Column(String(64), index=True)
    code = Column(String(10), nullable=False, index=True)
    name = Column(String(50))
    dimension = Column(String(32), index=True)
    query = Column(String(255))
    provider = Column(String(32), index=True)
    title = Column(String(300), nullable=False)
    snippet = Column(Text)
    url = Column(String(1000), nullable=False)
    source = Column(String(100))
    published_date = Column(DateTime, index=True)
    fetched_at = Column(DateTime, default=datetime.now, index=True)
    query_source = Column(String(32), index=True)
    requester_platform = Column(String(20))
    requester_user_id = Column(String(64))
    requester_user_name = Column(String(64))
    requester_chat_id = Column(String(64))
    requester_message_id = Column(String(64))
    requester_query = Column(String(255))

    __table_args__ = (
        UniqueConstraint('url', name='uix_news_url'),
        Index('ix_news_code_pub', 'code', 'published_date'),
    )


class AnalysisHistory(Base):
    """分析结果历史记录模型"""
    __tablename__ = 'analysis_history'

    id = Column(Integer, primary_key=True, autoincrement=True)
    query_id = Column(String(64), index=True)
    code = Column(String(10), nullable=False, index=True)
    name = Column(String(50))
    report_type = Column(String(16), index=True)
    sentiment_score = Column(Integer)
    operation_advice = Column(String(20))
    trend_prediction = Column(String(50))
    analysis_summary = Column(Text)
    raw_result = Column(Text)
    news_content = Column(Text)
    context_snapshot = Column(Text)
    ideal_buy = Column(Float)
    secondary_buy = Column(Float)
    stop_loss = Column(Float)
    take_profit = Column(Float)
    created_at = Column(DateTime, default=datetime.now, index=True)

    __table_args__ = (
        Index('ix_analysis_code_time', 'code', 'created_at'),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'query_id': self.query_id,
            'code': self.code,
            'name': self.name,
            'report_type': self.report_type,
            'sentiment_score': self.sentiment_score,
            'operation_advice': self.operation_advice,
            'trend_prediction': self.trend_prediction,
            'analysis_summary': self.analysis_summary,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class DatabaseManager:
    """
    数据库管理器 - 单例模式
    """
    
    _instance: Optional['DatabaseManager'] = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, db_url: Optional[str] = None):
        if self._initialized:
            return
        
        if db_url is None:
            config = get_config()
            db_url = config.get_db_url()
        
        self._engine = create_engine(
            db_url,
            echo=False,
            pool_pre_ping=True,
        )
        
        self._SessionLocal = sessionmaker(
            bind=self._engine,
            autocommit=False,
            autoflush=False,
        )
        
        Base.metadata.create_all(self._engine)
        self._initialized = True
        logger.info(f"数据库初始化完成: {db_url}")
        atexit.register(DatabaseManager._cleanup_engine, self._engine)
    
    @classmethod
    def get_instance(cls) -> 'DatabaseManager':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        if cls._instance is not None:
            cls._instance._engine.dispose()
            cls._instance = None

    @classmethod
    def _cleanup_engine(cls, engine) -> None:
        try:
            if engine is not None:
                engine.dispose()
        except Exception:
            pass
    
    def get_session(self) -> Session:
        session = self._SessionLocal()
        try:
            return session
        except Exception:
            session.close()
            raise
    
    def has_today_data(self, code: str, target_date: Optional[date] = None) -> bool:
        if target_date is None:
            target_date = date.today()
        
        with self.get_session() as session:
            result = session.execute(
                select(StockDaily).where(
                    and_(StockDaily.code == code, StockDaily.date == target_date)
                )
            ).scalar_one_or_none()
            return result is not None
    
    def get_latest_data(self, code: str, days: int = 2) -> List[StockDaily]:
        with self.get_session() as session:
            results = session.execute(
                select(StockDaily)
                .where(StockDaily.code == code)
                .order_by(desc(StockDaily.date))
                .limit(days)
            ).scalars().all()
            return list(results)

    def save_news_intel(self, code: str, name: str, dimension: str, query: str, response: Any, query_context: Optional[Dict] = None) -> int:
        if not response or not response.results:
            return 0
        saved_count = 0
        with self.get_session() as session:
            try:
                for item in response.results:
                    title = (item.title or '').strip()
                    url = (item.url or '').strip()
                    if not title and not url: continue
                    
                    url_key = url or self._build_fallback_url_key(code, title, item.source, self._parse_published_date(item.published_date))
                    existing = session.execute(select(NewsIntel).where(NewsIntel.url == url_key)).scalar_one_or_none()

                    if existing:
                        existing.fetched_at = datetime.now()
                    else:
                        try:
                            with session.begin_nested():
                                record = NewsIntel(
                                    code=code, name=name, dimension=dimension, query=query, provider=response.provider,
                                    title=title, snippet=item.snippet, url=url_key, source=item.source,
                                    published_date=self._parse_published_date(item.published_date),
                                    fetched_at=datetime.now(),
                                    query_id=(query_context or {}).get("query_id"),
                                    query_source=(query_context or {}).get("query_source")
                                )
                                session.add(record)
                            saved_count += 1
                        except IntegrityError:
                            pass
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"保存新闻情报失败: {e}")
        return saved_count

    def get_recent_news(self, code: str, days: int = 7, limit: int = 20) -> List[NewsIntel]:
        cutoff_date = datetime.now() - timedelta(days=days)
        with self.get_session() as session:
            results = session.execute(
                select(NewsIntel)
                .where(and_(NewsIntel.code == code, NewsIntel.fetched_at >= cutoff_date))
                .order_by(desc(NewsIntel.fetched_at))
                .limit(limit)
            ).scalars().all()
            return list(results)

    def save_analysis_history(self, result: Any, query_id: str, report_type: str, news_content: Optional[str], context_snapshot: Optional[Dict] = None, save_snapshot: bool = True) -> int:
        if result is None: return 0
        sniper_points = self._extract_sniper_points(result)
        raw_result = self._build_raw_result(result)
        context_text = self._safe_json_dumps(context_snapshot) if (save_snapshot and context_snapshot) else None

        record = AnalysisHistory(
            query_id=query_id, code=result.code, name=result.name, report_type=report_type,
            sentiment_score=result.sentiment_score, operation_advice=result.operation_advice,
            trend_prediction=result.trend_prediction, analysis_summary=result.analysis_summary,
            raw_result=self._safe_json_dumps(raw_result), news_content=news_content,
            context_snapshot=context_text, ideal_buy=sniper_points.get("ideal_buy"),
            secondary_buy=sniper_points.get("secondary_buy"), stop_loss=sniper_points.get("stop_loss"),
            take_profit=sniper_points.get("take_profit"), created_at=datetime.now()
        )
        with self.get_session() as session:
            try:
                session.add(record)
                session.commit()
                return 1
            except Exception as e:
                session.rollback()
                logger.error(f"保存分析历史失败: {e}")
                return 0

    def get_analysis_history(self, code: Optional[str] = None, query_id: Optional[str] = None, days: int = 30, limit: int = 50) -> List[AnalysisHistory]:
        cutoff_date = datetime.now() - timedelta(days=days)
        with self.get_session() as session:
            conditions = [AnalysisHistory.created_at >= cutoff_date]
            if code: conditions.append(AnalysisHistory.code == code)
            if query_id: conditions.append(AnalysisHistory.query_id == query_id)
            results = session.execute(
                select(AnalysisHistory).where(and_(*conditions)).order_by(desc(AnalysisHistory.created_at)).limit(limit)
            ).scalars().all()
            return list(results)
    
    def save_daily_data(self, df: pd.DataFrame, code: str, data_source: str = "Unknown") -> int:
        if df is None or df.empty: return 0
        saved_count = 0
        with self.get_session() as session:
            try:
                for _, row in df.iterrows():
                    row_date = row.get('date')
                    if isinstance(row_date, str):
                        row_date = datetime.strptime(row_date, '%Y-%m-%d').date()
                    elif hasattr(row_date, 'date'):
                        row_date = row_date.date()
                    
                    existing = session.execute(select(StockDaily).where(and_(StockDaily.code == code, StockDaily.date == row_date))).scalar_one_or_none()
                    if existing:
                        existing.open = row.get('open')
                        existing.high = row.get('high')
                        existing.low = row.get('low')
                        existing.close = row.get('close')
                        existing.volume = row.get('volume')
                        existing.amount = row.get('amount')
                        existing.pct_chg = row.get('pct_chg')
                        existing.ma5 = row.get('ma5')
                        existing.ma10 = row.get('ma10')
                        existing.ma20 = row.get('ma20')
                        existing.volume_ratio = row.get('volume_ratio')
                        existing.data_source = data_source
                        existing.updated_at = datetime.now()
                    else:
                        record = StockDaily(
                            code=code, date=row_date, open=row.get('open'), high=row.get('high'),
                            low=row.get('low'), close=row.get('close'), volume=row.get('volume'),
                            amount=row.get('amount'), pct_chg=row.get('pct_chg'), ma5=row.get('ma5'),
                            ma10=row.get('ma10'), ma20=row.get('ma20'), volume_ratio=row.get('volume_ratio'),
                            data_source=data_source
                        )
                        session.add(record)
                        saved_count += 1
                session.commit()
                logger.info(f"保存 {code} 数据成功，新增 {saved_count} 条")
            except Exception as e:
                session.rollback()
                logger.error(f"保存 {code} 数据失败: {e}")
                raise
        return saved_count
    
    def get_analysis_context(self, code: str, target_date: Optional[date] = None) -> Optional[Dict[str, Any]]:
        if target_date is None: target_date = date.today()
        recent_data = self.get_latest_data(code, days=2)
        if not recent_data: return None
        
        today_data = recent_data[0]
        context = {'code': code, 'date': today_data.date.isoformat(), 'today': today_data.to_dict()}
        if len(recent_data) > 1:
            yesterday_data = recent_data[1]
            context['yesterday'] = yesterday_data.to_dict()
            if yesterday_data.volume and yesterday_data.volume > 0:
                context['volume_change_ratio'] = round(today_data.volume / yesterday_data.volume, 2)
            if yesterday_data.close and yesterday_data.close > 0:
                context['price_change_ratio'] = round((today_data.close - yesterday_data.close) / yesterday_data.close * 100, 2)
            context['ma_status'] = self._analyze_ma_status(today_data)
        return context

    # === 新增：直接获取历史 DataFrame，用于盘中缝合 ===
    def get_stock_history_df(self, code: str, days: int = 120) -> pd.DataFrame:
        """
        从数据库获取历史 K 线数据，直接转换为 DataFrame
        用于盘中分析时的"历史底座"
        """
        try:
            sql = text(f"""
                SELECT date, open, high, low, close, volume, amount, pct_chg 
                FROM stock_daily 
                WHERE code = :code 
                ORDER BY date DESC 
                LIMIT :limit
            """)
            
            with self._engine.connect() as conn:
                df = pd.read_sql(sql, conn, params={"code": code, "limit": days})
            
            if df.empty:
                return pd.DataFrame()
            
            # 数据库出来是降序(最近的在前)，转为升序(时间的流向)
            df = df.sort_values('date', ascending=True).reset_index(drop=True)
            
            # 确保日期格式统一为 datetime
            df['date'] = pd.to_datetime(df['date'])
            
            return df
        except Exception as e:
            logger.error(f"读取数据库失败 {code}: {e}")
            return pd.DataFrame()
            
    # === 新增：获取历史记忆（用于连续性分析） ===
    def get_last_analysis_summary(self, code: str) -> Optional[Dict[str, str]]:
        """
        获取上一次分析的核心观点
        返回: {'date': '2026-02-04', 'view': '看多，因为...', 'risk': '注意...'}
        """
        with self.get_session() as session:
            # 获取最近的一条记录
            result = session.execute(
                select(AnalysisHistory)
                .where(AnalysisHistory.code == code)
                .order_by(desc(AnalysisHistory.created_at))
                .limit(1)
            ).scalar_one_or_none()
            
            if result:
                return {
                    'date': result.created_at.strftime('%Y-%m-%d'),
                    'trend': result.trend_prediction,
                    'view': result.analysis_summary[:100] + "..." if result.analysis_summary else "", # 截取前100字作为摘要
                    'advice': result.operation_advice
                }
            return None

    def _analyze_ma_status(self, data: StockDaily) -> str:
        close = data.close or 0
        ma5 = data.ma5 or 0
        ma10 = data.ma10 or 0
        ma20 = data.ma20 or 0
        if close > ma5 > ma10 > ma20 > 0: return "多头排列 📈"
        elif close < ma5 < ma10 < ma20 and ma20 > 0: return "空头排列 📉"
        elif close > ma5 and ma5 > ma10: return "短期向好 🔼"
        elif close < ma5 and ma5 < ma10: return "短期走弱 🔽"
        else: return "震荡整理 ↔️"

    @staticmethod
    def _parse_published_date(value: Optional[str]) -> Optional[datetime]:
        if not value: return None
        if isinstance(value, datetime): return value
        text = str(value).strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
            try: return datetime.strptime(text, fmt)
            except ValueError: continue
        return None

    @staticmethod
    def _safe_json_dumps(data: Any) -> str:
        try: return json.dumps(data, ensure_ascii=False, default=str)
        except Exception: return json.dumps(str(data), ensure_ascii=False)

    @staticmethod
    def _build_raw_result(result: Any) -> Dict[str, Any]:
        data = result.to_dict() if hasattr(result, "to_dict") else {}
        data.update({'data_sources': getattr(result, 'data_sources', ''), 'raw_response': getattr(result, 'raw_response', None)})
        return data

    @staticmethod
    def _extract_sniper_points(result: Any) -> Dict[str, Optional[float]]:
        raw_points = result.get_sniper_points() if hasattr(result, "get_sniper_points") else {}
        def parse(v):
            if v is None or isinstance(v, (int, float)): return v
            match = re.search(r"-?\d+(?:\.\d+)?", str(v).replace(',', ''))
            return float(match.group()) if match else None
        return {k: parse(raw_points.get(k)) for k in ["ideal_buy", "secondary_buy", "stop_loss", "take_profit"]}

    @staticmethod
    def _build_fallback_url_key(code: str, title: str, source: str, published_date: Optional[datetime]) -> str:
        date_str = published_date.isoformat() if published_date else ""
        raw_key = f"{code}|{title}|{source}|{date_str}"
        digest = hashlib.md5(raw_key.encode("utf-8")).hexdigest()
        return f"no-url:{code}:{digest}"

def get_db() -> DatabaseManager:
    return DatabaseManager.get_instance()