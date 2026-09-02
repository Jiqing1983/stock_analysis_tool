"""
Streamlit主入口 - 自定义认证版本
"""
import streamlit as st
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta

# 加载环境变量（本地开发用）
load_dotenv()

# ==================== 页面配置 ====================
st.set_page_config(
    page_title="智能股票分析系统",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==================== 数据库初始化 ====================
from database.db_manager import db_manager
db_manager.initialize()


# ==================== 导入自定义模块 ====================
from database.models import User, UserRole
from core.auth import hash_password, verify_password

# ==================== 确保管理员账户存在 ====================
def ensure_admin_user():
    """从环境变量（Secrets）读取管理员凭据，若不存在则创建"""
    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    admin_password = os.getenv("ADMIN_PASSWORD", "admin123")
    admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
    
    with db_manager.get_session() as session:
        admin = session.query(User).filter_by(username=admin_username).first()
        if not admin:
            hashed = hash_password(admin_password)
            admin = User(
                username=admin_username,
                email=admin_email,
                password_hash=hashed,
                role=UserRole.ADMIN,
                balance=100.0,
                total_tokens_used=0,
                membership_expiry=datetime.utcnow() + timedelta(days=365),
                is_active=True
            )
            session.add(admin)
            session.commit()


# 执行管理员初始化
ensure_admin_user()

# ==================== 会话状态初始化 ====================
if "authentication_status" not in st.session_state:
    st.session_state["authentication_status"] = None
if "username" not in st.session_state:
    st.session_state["username"] = None
if "page" not in st.session_state:
    st.session_state["page"] = "📊 我的分析"

# ==================== 登录与登出函数 ====================
def login():
    """显示登录表单"""
    st.sidebar.title("🔐 登录")
    with st.sidebar.form("login_form"):
        username = st.text_input("用户名", placeholder="请输入用户名")
        password = st.text_input("密码", type="password", placeholder="请输入密码")
        submitted = st.form_submit_button("登录")
        
        if submitted:
            if not username or not password:
                st.sidebar.error("用户名和密码不能为空")
                return
            
            with db_manager.get_session() as session:
                user = session.query(User).filter_by(username=username).first()
                if user and verify_password(password, user.password_hash):
                    st.session_state["authentication_status"] = True
                    st.session_state["username"] = username
                    st.session_state["name"] = username
                    st.rerun()
                else:
                    st.sidebar.error("用户名或密码错误")
    
    # 注册入口
    st.sidebar.markdown("---")
    if st.sidebar.button("📝 还没有账号？立即注册"):
        st.session_state["page"] = "register"
        st.rerun()

def logout():
    """退出登录"""
    for key in ["authentication_status", "username", "name", "page"]:
        if key in st.session_state:
            del st.session_state[key]
    st.rerun()

# ==================== 主函数 ====================
def main():
    # ---------- 未登录 ----------
    if not st.session_state.get("authentication_status", False):
        login()  # 显示登录表单
        
        # 如果用户点击了注册，则显示注册页面（覆盖登录表单区域）
        if st.session_state.get("page") == "register":
            from views.register import show
            show()
        return
    
    # ---------- 已登录 ----------
    username = st.session_state["username"]
    
    # 从数据库获取用户信息（在会话内提取所有属性）
    with db_manager.get_session() as session:
        user = session.query(User).filter_by(username=username).first()
        if not user:
            st.error("用户不存在，请重新登录")
            logout()
            return
        user_id = user.id
        role = user.role.value
        balance = user.balance
        total_tokens_used = user.total_tokens_used
    
    # ---------- 侧边栏 ----------
    with st.sidebar:
        st.title("📈 股票分析系统")
        st.write(f"👤 欢迎, {username}")
        st.write(f"📋 角色: {'管理员' if role == 'admin' else '普通用户'}")
        
        if role == "user":
            st.metric("💰 账户余额", f"¥{balance:.2f}")
            st.metric("📊 已用Token", f"{total_tokens_used:,}")
        
        st.divider()
        
        # 导航菜单
        if role == "admin":
            page_options = ["📊 用户面板", "📊 我的分析", "🧠 模型训练", "⚙️ 模型设置", "👥 用户管理"]
        else:
            page_options = ["📖 模型简介","📊 我的分析", "👤 个人设置"]
        
        # 确保当前页面在选项列表中
        if st.session_state.page not in page_options:
            st.session_state.page = page_options[0]
        
        selected = st.radio("导航", page_options, index=page_options.index(st.session_state.page))
        if selected != st.session_state.page:
            st.session_state.page = selected
            st.rerun()
        
        st.divider()
        if st.button("🚪 退出登录"):
            logout()
    
    # ---------- 页面路由 ----------
    page = st.session_state.page
    
    if role == "admin":
        if page == "📊 用户面板":
            from views.admin_dashboard import show
            show()
        elif page == "📊 我的分析":
            from views.user_dashboard import show
            show(user_id)
        elif page == "🧠 模型训练":
            from views.admin_model import show
            show()
        elif page == "⚙️ 模型设置":
            from views.admin_settings import show
            show()
        elif page == "👥 用户管理":
            from views.admin_users import show
            show()
    else:  # 普通用户
        if page == "📖 模型简介":
            from views.intro import show
            show()
        elif page == "📊 我的分析":
            from views.user_dashboard import show
            show(user_id)
        elif page == "👤 个人设置":
            from views.user_settings import show
            show(user_id)

# ==================== 程序入口 ====================
if __name__ == "__main__":
    main()