"""
安全批量历史数据拉取脚本（用于扩大回测样本）
===============================================
使用 baostock 逐只拉取60只股票的600天日线数据，
存入 stock_daily 表，供后续 IC 分析和回测使用。

安全策略：
- 序列化请求（非并发），每只股票间隔 2~4 秒
- baostock 为免费本地接口，不涉及外部IP封禁风险
- 已有数据的股票跳过拉取（INSERT OR IGNORE）

用法：
    cd /Users/chengxidai/daily_stock_analysis
    python scripts/fetch_history_for_backtest.py
"""
import sys
import os
import time
import random
import logging
import warnings
from datetime import date, timedelta

import pandas as pd
import baostock as bs

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# 60只多样化股票（与 backtest_exhaustive.py 保持一致）
STOCKS = [
    '600519', '000858', '000333', '000002', '600036', '601318', '002415', '300059', '600900',
    '601088', '600019', '000895', '002304', '603288', '002557',
    '002594', '601127', '300750', '600276', '000538', '002916', '000001', '600016', '000568',
    '600028', '601857', '600362', '000039', '601600',
    '002230', '300014', '002475', '603501', '688036',
    '600196', '000661', '300122', '600085',
    '600887', '002714', '601866', '000725', '002352',
    '601328', '000776', '601688', '600030', '600837',
    '000069', '600048', '601668', '000786',
    '300015', '002460', '300274', '601138', '002049',
    '600690', '601166', '600009', '601006',
]
STOCKS = list(dict.fromkeys(STOCKS))  # 去重

HISTORY_DAYS = 600


def fetch_baostock(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """用 baostock 拉取日线数据"""
    prefix = 'sh' if code.startswith(('6', '9')) else 'sz'
    rs = bs.query_history_k_data_plus(
        f'{prefix}.{code}',
        'date,open,high,low,close,volume,amount,pctChg',
        start_date=start_date,
        end_date=end_date,
        frequency='d',
        adjustflag='2'  # 后复权
    )
    data = []
    while rs.next():
        data.append(rs.get_row_data())
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data, columns=rs.fields)
    df['date'] = pd.to_datetime(df['date'])
    for col in ['open', 'high', 'low', 'close', 'volume', 'amount', 'pctChg']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.rename(columns={'pctChg': 'pct_chg'})
    df = df.sort_values('date').reset_index(drop=True)
    return df


def check_existing_count(db, code: str) -> int:
    """检查stock_daily中该code已有多少条数据"""
    from sqlalchemy import text
    with db._engine.connect() as conn:
        r = conn.execute(text('SELECT COUNT(*) FROM stock_daily WHERE code=:code'), {'code': code}).fetchone()
        return r[0] if r else 0


def main():
    from src.storage import DatabaseManager
    db = DatabaseManager()

    end_dt = date.today()
    start_dt = end_dt - timedelta(days=int(HISTORY_DAYS * 1.6))
    end_str = end_dt.strftime('%Y-%m-%d')
    start_str = start_dt.strftime('%Y-%m-%d')

    print(f"准备拉取 {len(STOCKS)} 只股票，时间范围：{start_str} ~ {end_str}")
    print("安全模式：序列化请求，间隔 2~4 秒\n")

    # 登录 baostock
    lg = bs.login()
    if lg.error_code != '0':
        print(f"baostock 登录失败: {lg.error_msg}")
        return

    success, skip, failed = 0, 0, 0

    for i, code in enumerate(STOCKS):
        existing = check_existing_count(db, code)
        if existing >= HISTORY_DAYS * 0.8:
            logger.info(f"[{i+1}/{len(STOCKS)}] {code}: 已有 {existing} 条，跳过")
            skip += 1
            continue

        try:
            df = fetch_baostock(code, start_str, end_str)
            if df.empty:
                logger.warning(f"[{i+1}/{len(STOCKS)}] {code}: 无数据")
                failed += 1
                continue

            saved = db.save_daily_data(df, code, data_source='baostock_backfill')
            logger.info(f"[{i+1}/{len(STOCKS)}] {code}: 拉取 {len(df)} 条，入库 {saved} 条（原有 {existing} 条）")
            success += 1

        except Exception as e:
            logger.error(f"[{i+1}/{len(STOCKS)}] {code}: 失败 - {e}")
            failed += 1

        # 安全间隔
        sleep_t = random.uniform(2.0, 4.0)
        time.sleep(sleep_t)

    bs.logout()

    print(f"\n{'='*50}")
    print(f"完成！成功: {success}  跳过(已有数据): {skip}  失败: {failed}")
    print(f"stock_daily 现有数据覆盖 {len(STOCKS)} 只股票")


if __name__ == '__main__':
    main()
