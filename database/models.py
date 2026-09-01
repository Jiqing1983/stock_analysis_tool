"""
数据库模型定义
使用SQLAlchemy ORM
"""
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Text, 
    Boolean, ForeignKey, JSON, Enum, create_engine
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from datetime import datetime, timezone
import enum
import json
Base = declarative_base()


class UserRole(enum.Enum):
    ADMIN = "admin"
    USER = "user"


class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.USER)
    
    # 账户信息
    balance = Column(Float, default=0.0)  # 账户余额（元）
    total_tokens_used = Column(Integer, default=0)
    membership_expiry = Column(DateTime, nullable=True)  # 会员到期日
    
    # 个人信息
    first_name = Column(String(50))
    last_name = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    # 关联
    analyses = relationship("StockAnalysis", back_populates="user")
    payments = relationship("Payment", back_populates="user")
    
def is_member_active(self) -> bool:
    from datetime import datetime, timezone
    if not self.membership_expiry:
        return False
    expiry = self.membership_expiry
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) < expiry


class StockAnalysis(Base):
    __tablename__ = "stock_analyses"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # 股票信息
    stock_code = Column(String(20), nullable=False)
    stock_name = Column(String(100))
    
    # 分析结果（按模板字段存储）
    analysis_data = Column(JSON, nullable=False)  # 存储所有字段的键值对
    
    # 元数据
    analysis_date = Column(DateTime, default=datetime.utcnow)
    tokens_used = Column(Integer, default=0)
    cost = Column(Float, default=0.0)  # 本次分析费用
    
    # 原始报告
    raw_report = Column(Text)
    
    # 关联
    user = relationship("User", back_populates="analyses")
    
    def to_dict(self, fields: list = None) -> dict:
        """转换为字典，自动解析 JSON 字符串"""
        data = self.analysis_data
        # 如果 data 是字符串，尝试解析为 JSON
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except:
                data = {}
        if fields:
            return {f: data.get(f, "") for f in fields}
        return data


class Payment(Base):
    __tablename__ = "payments"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    amount = Column(Float, nullable=False)  # 充值金额
    tokens = Column(Integer, nullable=False)  # 购买的token数
    payment_method = Column(String(50))
    transaction_id = Column(String(100), unique=True)
    
    status = Column(String(20), default="pending")  # pending, success, failed
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    user = relationship("User", back_populates="payments")


class ModelConfig(Base):
    __tablename__ = "model_configs"
    
    id = Column(Integer, primary_key=True)
    config_key = Column(String(50), unique=True, nullable=False)
    config_value = Column(Text, nullable=False)
    description = Column(String(200))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(String(50))


class ModelTrainingLog(Base):
    __tablename__ = "model_training_logs"
    
    id = Column(Integer, primary_key=True)
    session_id = Column(String(50))
    messages = Column(JSON)  # 对话记录
    tokens_used = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default="active")  # active, archived