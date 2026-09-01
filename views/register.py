"""
用户注册页面
"""
import streamlit as st
from database.db_manager import db_manager
from database.models import User, UserRole
from core.auth import hash_password
from datetime import datetime


def show():
    st.title("📝 注册新账号")
    
    with st.form("register_form"):
        username = st.text_input("用户名", max_chars=50, placeholder="请设置用户名")
        email = st.text_input("邮箱", max_chars=100, placeholder="请输入邮箱地址")
        password = st.text_input("密码", type="password", max_chars=50, placeholder="至少6位")
        confirm_password = st.text_input("确认密码", type="password", max_chars=50, placeholder="再次输入密码")
        
        # 注册按钮（使用 form_submit_button）
        submitted = st.form_submit_button("注册")
        
        if submitted:
            # 校验
            if not username or not email or not password:
                st.error("所有字段均为必填")
                return
            if password != confirm_password:
                st.error("两次输入的密码不一致")
                return
            if len(password) < 6:
                st.error("密码长度至少6位")
                return
            
            # 检查用户名或邮箱是否已存在
            with db_manager.get_session() as session:
                existing = session.query(User).filter(
                    (User.username == username) | (User.email == email)
                ).first()
                if existing:
                    st.error("用户名或邮箱已被注册")
                    return
                
                # 创建新用户（普通用户，赠送10元体验金）
                hashed_pw = hash_password(password)
                new_user = User(
                    username=username,
                    email=email,
                    password_hash=hashed_pw,
                    role=UserRole.USER,
                    balance=10.0,
                    total_tokens_used=0,
                    membership_expiry=None,
                    is_active=True
                )
                session.add(new_user)
                session.commit()
            
            st.success("✅ 注册成功！请返回登录")
            st.balloons()
    
    # 去登录按钮（放在表单外部）
    if st.button("🔐 去登录"):
        st.session_state["page"] = "📊 我的分析"
        st.rerun()