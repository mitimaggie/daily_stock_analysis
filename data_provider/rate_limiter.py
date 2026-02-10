# -*- coding: utf-8 -*-
"""
全局请求限流器 - 令牌桶算法 + 熔断器
用于统一控制所有数据源的请求速率，防止接口封禁
"""

import time
import threading
import logging
from typing import Optional, Dict, Callable
from datetime import datetime, timedelta
from collections import deque

logger = logging.getLogger(__name__)


class TokenBucket:
    """令牌桶限流器
    
    原理：
    - 桶内有固定容量的令牌
    - 每次请求消耗1个令牌
    - 令牌以固定速率补充
    - 桶满时停止补充
    
    优势：
    - 允许短时突发流量（桶内有余量时）
    - 长期平均速率受控
    """
    
    def __init__(self, capacity: int, refill_rate: float):
        """
        Args:
            capacity: 桶容量（最多存储的令牌数）
            refill_rate: 令牌补充速率（每秒补充几个令牌）
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.time()
        self.lock = threading.Lock()
    
    def _refill(self):
        """补充令牌"""
        now = time.time()
        elapsed = now - self.last_refill
        new_tokens = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + new_tokens)
        self.last_refill = now
    
    def acquire(self, tokens: int = 1, blocking: bool = True, timeout: Optional[float] = None) -> bool:
        """获取令牌
        
        Args:
            tokens: 需要的令牌数
            blocking: 是否阻塞等待
            timeout: 超时时间（秒）
        
        Returns:
            是否成功获取令牌
        """
        start_time = time.time()
        
        while True:
            with self.lock:
                self._refill()
                
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True
                
                if not blocking:
                    return False
                
                if timeout is not None and (time.time() - start_time) >= timeout:
                    return False
            
            # 计算需要等待的时间
            tokens_needed = tokens - self.tokens
            wait_time = tokens_needed / self.refill_rate
            time.sleep(min(wait_time, 0.1))  # 最多等待0.1秒后重新检查


class CircuitBreaker:
    """熔断器
    
    状态机：
    - CLOSED: 正常状态，允许请求通过
    - OPEN: 熔断状态，拒绝所有请求
    - HALF_OPEN: 半开状态，允许少量请求测试恢复
    
    熔断条件：
    - 在时间窗口内，失败率超过阈值
    - 连续失败次数超过阈值
    
    恢复条件：
    - 熔断后等待一段时间，进入半开状态
    - 半开状态下成功一定次数后，恢复到关闭状态
    """
    
    STATE_CLOSED = "closed"
    STATE_OPEN = "open"
    STATE_HALF_OPEN = "half_open"
    
    def __init__(
        self, 
        failure_threshold: int = 5,
        success_threshold: int = 2,
        timeout: float = 60.0,
        window_size: int = 100
    ):
        """
        Args:
            failure_threshold: 失败阈值（连续失败几次触发熔断）
            success_threshold: 成功阈值（半开状态成功几次恢复）
            timeout: 熔断超时时间（秒），超时后进入半开状态
            window_size: 滑动窗口大小（记录最近N次请求）
        """
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.timeout = timeout
        self.window_size = window_size
        
        self.state = self.STATE_CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.last_state_change = time.time()
        
        self.recent_calls = deque(maxlen=window_size)
        self.lock = threading.Lock()
    
    def call(self, func: Callable, *args, **kwargs):
        """通过熔断器调用函数
        
        Args:
            func: 要调用的函数
            *args, **kwargs: 函数参数
        
        Returns:
            函数返回值
        
        Raises:
            CircuitBreakerOpen: 熔断器打开时抛出
        """
        with self.lock:
            if self.state == self.STATE_OPEN:
                # 检查是否超时，可以进入半开状态
                if time.time() - self.last_failure_time >= self.timeout:
                    logger.info("🔄 熔断器进入半开状态，尝试恢复")
                    self.state = self.STATE_HALF_OPEN
                    self.success_count = 0
                else:
                    raise CircuitBreakerOpen("熔断器打开，请求被拒绝")
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise e
    
    def _on_success(self):
        """记录成功"""
        with self.lock:
            self.recent_calls.append(True)
            self.failure_count = 0
            
            if self.state == self.STATE_HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.success_threshold:
                    logger.info("✅ 熔断器恢复正常")
                    self.state = self.STATE_CLOSED
                    self.success_count = 0
    
    def _on_failure(self):
        """记录失败"""
        with self.lock:
            self.recent_calls.append(False)
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.state == self.STATE_HALF_OPEN:
                logger.warning("⚠️ 半开状态测试失败，重新熔断")
                self.state = self.STATE_OPEN
                self.success_count = 0
            elif self.failure_count >= self.failure_threshold:
                logger.error(f"🔴 熔断器打开：连续失败{self.failure_count}次")
                self.state = self.STATE_OPEN
                self.last_state_change = time.time()
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self.lock:
            total = len(self.recent_calls)
            if total == 0:
                return {
                    "state": self.state,
                    "total_calls": 0,
                    "failure_rate": 0.0,
                    "failure_count": self.failure_count
                }
            
            failures = sum(1 for call in self.recent_calls if not call)
            return {
                "state": self.state,
                "total_calls": total,
                "failure_rate": failures / total,
                "failure_count": self.failure_count,
                "success_count": self.success_count
            }


class CircuitBreakerOpen(Exception):
    """熔断器打开异常"""
    pass


class GlobalRateLimiter:
    """全局限流器
    
    管理多个数据源的限流策略：
    - 为每个数据源配置独立的令牌桶
    - 为每个数据源配置独立的熔断器
    - 提供统一的请求接口
    """
    
    def __init__(self):
        self.limiters: Dict[str, TokenBucket] = {}
        self.breakers: Dict[str, CircuitBreaker] = {}
        self.lock = threading.Lock()
        
        # 预配置常见数据源
        self._init_default_limiters()
    
    def _init_default_limiters(self):
        """初始化默认限流配置"""
        # akshare: 保守限流（每秒1次，桶容量3）
        self.limiters['akshare'] = TokenBucket(capacity=3, refill_rate=1.0)
        self.breakers['akshare'] = CircuitBreaker(failure_threshold=5, timeout=60.0)
        
        # efinance: 中等限流（每秒0.5次，桶容量2）
        self.limiters['efinance'] = TokenBucket(capacity=2, refill_rate=0.5)
        self.breakers['efinance'] = CircuitBreaker(failure_threshold=5, timeout=60.0)
        
        # baostock: 保守限流（每秒0.5次，桶容量2）
        self.limiters['baostock'] = TokenBucket(capacity=2, refill_rate=0.5)
        self.breakers['baostock'] = CircuitBreaker(failure_threshold=3, timeout=120.0)
        
        # pytdx: 宽松限流（本地接口）
        self.limiters['pytdx'] = TokenBucket(capacity=10, refill_rate=5.0)
        self.breakers['pytdx'] = CircuitBreaker(failure_threshold=10, timeout=30.0)
        
        # yfinance: 保守限流（海外接口）
        self.limiters['yfinance'] = TokenBucket(capacity=2, refill_rate=0.3)
        self.breakers['yfinance'] = CircuitBreaker(failure_threshold=3, timeout=180.0)
        
        logger.info("🛡️ 全局限流器初始化完成")
    
    def acquire(self, source: str, blocking: bool = True, timeout: Optional[float] = 30.0) -> bool:
        """获取请求许可
        
        Args:
            source: 数据源名称
            blocking: 是否阻塞等待
            timeout: 超时时间（秒）
        
        Returns:
            是否成功获取许可
        
        Raises:
            CircuitBreakerOpen: 熔断器打开时抛出
        """
        # 检查熔断器
        breaker = self.breakers.get(source)
        if breaker and breaker.state == CircuitBreaker.STATE_OPEN:
            if time.time() - breaker.last_failure_time < breaker.timeout:
                raise CircuitBreakerOpen(f"{source} 熔断器打开")
        
        # 获取令牌
        limiter = self.limiters.get(source)
        if limiter is None:
            # 未配置的数据源，使用默认限流（每秒1次）
            limiter = TokenBucket(capacity=2, refill_rate=1.0)
            self.limiters[source] = limiter
            self.breakers[source] = CircuitBreaker()
        
        return limiter.acquire(tokens=1, blocking=blocking, timeout=timeout)
    
    def record_success(self, source: str):
        """记录请求成功"""
        breaker = self.breakers.get(source)
        if breaker:
            breaker._on_success()
    
    def record_failure(self, source: str):
        """记录请求失败"""
        breaker = self.breakers.get(source)
        if breaker:
            breaker._on_failure()
    
    def get_stats(self, source: str) -> Dict:
        """获取统计信息"""
        breaker = self.breakers.get(source)
        if breaker:
            return breaker.get_stats()
        return {}
    
    def reset(self, source: str):
        """重置指定数据源的限流器和熔断器"""
        with self.lock:
            if source in self.breakers:
                self.breakers[source].state = CircuitBreaker.STATE_CLOSED
                self.breakers[source].failure_count = 0
                self.breakers[source].success_count = 0
            if source in self.limiters:
                self.limiters[source].tokens = self.limiters[source].capacity


# 全局单例
_global_limiter = None
_limiter_lock = threading.Lock()


def get_global_limiter() -> GlobalRateLimiter:
    """获取全局限流器单例"""
    global _global_limiter
    if _global_limiter is None:
        with _limiter_lock:
            if _global_limiter is None:
                _global_limiter = GlobalRateLimiter()
    return _global_limiter
