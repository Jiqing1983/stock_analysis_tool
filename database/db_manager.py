"""
数据库连接管理
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from typing import Generator
import logging

from .models import Base

logger = logging.getLogger(__name__)


class DatabaseManager:
    """数据库管理器（单例模式）"""
    
    _instance = None
    _engine = None
    _session_factory = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def initialize(self, database_url: str = None):
        """初始化数据库连接"""
        if self._engine is not None:
            return
        
        database_url = database_url or os.getenv("DATABASE_URL", "sqlite:///./data/stock_analysis.db")
        
        # 确保数据目录存在
        if database_url.startswith("sqlite:///"):
            
            db_path = database_url.replace("sqlite:///", "")
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        self._engine = create_engine(
            database_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            echo=False
        )
        self._session_factory = sessionmaker(bind=self._engine)
        
        # 创建表
        Base.metadata.create_all(self._engine)
        logger.info(f"Database initialized: {database_url}")
    
    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """获取数据库会话（上下文管理器）"""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            session.close()
    
    def get_engine(self):
        return self._engine


# 全局数据库管理器实例
db_manager = DatabaseManager()