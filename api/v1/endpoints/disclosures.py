# -*- coding: utf-8 -*-
"""F10 公告与披露 API"""
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()


class DisclosureItem(BaseModel):
    title: str
    pub_date: str
    url: Optional[str] = None
    category: Optional[str] = None


class DisclosureResponse(BaseModel):
    stock_code: str
    items: List[DisclosureItem]
    total: int


@router.get("/{stock_code}", response_model=DisclosureResponse)
async def get_disclosures(
    stock_code: str,
    days: int = Query(default=90, ge=1, le=365, description="查询最近N天"),
    limit: int = Query(default=20, ge=1, le=100, description="返回条数上限"),
):
    """
    获取股票 F10 公告与披露信息（巨潮资讯）
    """
    try:
        import akshare as ak

        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

        df = ak.stock_zh_a_disclosure_report_cninfo(
            symbol=stock_code,
            market="沪深京",
            start_date=start_date,
            end_date=end_date,
        )

        items: List[DisclosureItem] = []
        if df is not None and not df.empty:
            for row in df.head(limit).to_dict('records'):
                items.append(
                    DisclosureItem(
                        title=str(row.get("公告标题", "")),
                        pub_date=str(row.get("公告时间", "")),
                        url=str(row.get("公告链接", "")) or None,
                        category=None,
                    )
                )

        return DisclosureResponse(
            stock_code=stock_code,
            items=items,
            total=len(items),
        )

    except Exception as e:
        logger.warning(f"[{stock_code}] 获取公告失败: {e}")
        return DisclosureResponse(stock_code=stock_code, items=[], total=0)
