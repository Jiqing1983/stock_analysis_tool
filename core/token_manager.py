"""
Token计费和用户余额管理
"""
import logging
from typing import Optional
from datetime import datetime, timedelta

from database.db_manager import db_manager
from database.models import User, Payment

logger = logging.getLogger(__name__)


class TokenManager:
    """Token计费管理器"""
    
    # 价格配置（元/1000 tokens）
    TOKEN_PRICE = 0.01
    
    def __init__(self):
        pass
    
    def get_user_balance(self, user_id: int) -> float:
        """获取用户余额"""
        with db_manager.get_session() as session:
            user = session.query(User).filter_by(id=user_id).first()
            return user.balance if user else 0.0
    
    def get_user_info(self, user_id: int) -> Optional[dict]:
        """获取用户完整信息"""
        with db_manager.get_session() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                return None
            
            return {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": user.role.value,
                "balance": user.balance,
                "total_tokens_used": user.total_tokens_used,
                "membership_expiry": user.membership_expiry.isoformat() if user.membership_expiry else None,
                "is_member_active": user.is_member_active(),
                "created_at": user.created_at.isoformat()
            }
    
    def deduct_tokens(self, user_id: int, tokens: int) -> bool:
        """扣除token费用"""
        cost = tokens / 1000 * self.TOKEN_PRICE
        
        with db_manager.get_session() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                return False
            
            if user.balance < cost:
                return False
            
            user.balance -= cost
            user.total_tokens_used += tokens
            return True
    
    def add_balance(self, user_id: int, amount: float, tokens: int, transaction_id: str) -> bool:
        """充值"""
        with db_manager.get_session() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                return False
            
            user.balance += amount
            
            payment = Payment(
                user_id=user_id,
                amount=amount,
                tokens=tokens,
                transaction_id=transaction_id,
                status="success",
                completed_at=datetime.utcnow()
            )
            session.add(payment)
            return True
    
    def get_payment_history(self, user_id: int, limit: int = 50) -> list:
        """获取充值记录"""
        with db_manager.get_session() as session:
            payments = session.query(Payment).filter_by(
                user_id=user_id,
                status="success"
            ).order_by(Payment.created_at.desc()).limit(limit).all()
            
            return [
                {
                    "id": p.id,
                    "amount": p.amount,
                    "tokens": p.tokens,
                    "payment_method": p.payment_method,
                    "transaction_id": p.transaction_id,
                    "created_at": p.created_at.isoformat(),
                    "completed_at": p.completed_at.isoformat() if p.completed_at else None
                }
                for p in payments
            ]
    
    def calculate_cost(self, tokens: int) -> float:
        """计算费用"""
        return tokens / 1000 * self.TOKEN_PRICE