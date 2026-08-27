"""
Streamlit主入口
负责路由和页面分发
"""
import streamlit as st
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 页面配置
st.set_page_config(
    page_title="智能股票分析系统",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 初始化数据库
from database.db_manager import db_manager
db_manager.initialize()

# 加载认证配置
def load_auth_config():
    config_path = "config.yaml"
    if not os.path.exists(config_path):
        # 创建默认配置
        default_config = {
            "cookie": {
                "expiry_days": 30,
                "key": os.getenv("SECRET_KEY", "random_key"),
                "name": "stock_analysis_cookie"
            },
            "credentials": {
                "usernames": {
                    os.getenv("ADMIN_USERNAME", "admin"): {
                        "email": "admin@example.com",
                        "first_name": "Admin",
                        "last_name": "User",
                        "password": os.getenv("ADMIN_PASSWORD", "admin123"),
                        "roles": ["admin"]
                    }
                }
            },
            "pre-authorized": {
                "emails": []
            }
        }
        with open(config_path, "w") as f:
            yaml.dump(default_config, f)
    
    with open(config_path) as file:
        return yaml.load(file, Loader=SafeLoader)

config = load_auth_config()
authenticator = stauth.Authenticate(
    config["credentials"],
    config["cookie"]["name"],
    config["cookie"]["key"],
    config["cookie"]["expiry_days"]
)

# 登录状态管理
if "authentication_status" not in st.session_state:
    st.session_state["authentication_status"] = None
if "username" not in st.session_state:
    st.session_state["username"] = None

def login():
    """显示登录表单并处理登录"""
    result = authenticator.login(
        location="main",
        fields={
            "Form name": "登录",
            "Username": "用户名",
            "Password": "密码",
            "Login": "登录"
        }
    )
    if result is None:
        return
    name, authentication_status, username = result
    if authentication_status:
        st.session_state["authentication_status"] = authentication_status
        st.session_state["username"] = username
        st.session_state["name"] = name
        st.rerun()
    elif authentication_status is False:
        st.error("用户名或密码错误")
    elif authentication_status is None:
        st.info("请输入用户名和密码")

def logout():
    """退出登录"""
    for key in ["authentication_status", "username", "name", "page"]:
        if key in st.session_state:
            del st.session_state[key]
    st.rerun()

def main():
    # 未登录 -> 显示登录
    if not st.session_state.get("authentication_status", False):
        login()
        return

    username = st.session_state["username"]

    # ===== 同步/获取用户信息（在会话内完成所有属性提取） =====
    from database.db_manager import db_manager
    from database.models import User, UserRole
    from datetime import datetime, timedelta
    import yaml

    with db_manager.get_session() as session:
        user = session.query(User).filter_by(username=username).first()

        if not user:
            # 从 config.yaml 获取用户信息
            with open("config.yaml", "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            user_data = config["credentials"]["usernames"].get(username, {})

            new_user = User(
                username=username,
                email=user_data.get("email", f"{username}@example.com"),
                password_hash="",
                role=UserRole.ADMIN if "admin" in user_data.get("roles", []) else UserRole.USER,
                balance=10.0,
                total_tokens_used=0,
                membership_expiry=datetime.utcnow() + timedelta(days=30),
                first_name=user_data.get("first_name", ""),
                last_name=user_data.get("last_name", ""),
                is_active=True
            )
            session.add(new_user)
            session.commit()
            # 重新查询以获取完整对象
            user = session.query(User).filter_by(username=username).first()

        if not user:
            st.error("用户同步失败，请检查数据库")
            return

        # 在会话内提取所有需要的属性，保存为普通变量
        user_id = user.id
        role = user.role.value
        balance = user.balance
        total_tokens_used = user.total_tokens_used
        membership_expiry = user.membership_expiry
        is_member_active = user.is_member_active()
        first_name = user.first_name
        last_name = user.last_name
        email = user.email

    # ============================================

    # 侧边栏
    with st.sidebar:
        st.title("📈 股票分析系统")
        st.write(f"👤 欢迎, {st.session_state['name']}")
        st.write(f"📋 角色: {'管理员' if role == 'admin' else '普通用户'}")

        if role == "user":
            st.metric("💰 账户余额", f"¥{balance:.2f}")
            st.metric("📊 已用Token", f"{total_tokens_used:,}")

        st.divider()

        # 导航
        if role == "admin":
            if "page" not in st.session_state:
                st.session_state.page = "📊 用户面板"
            page_options = ["📊 用户面板", "📊 我的分析", "🧠 模型训练", "⚙️ 模型设置", "👥 用户管理"]
            selected = st.radio(
                "导航",
                page_options,
                index=page_options.index(st.session_state.page),
                key="admin_nav"
            )
            if selected != st.session_state.page:
                st.session_state.page = selected
                st.rerun()
            page = st.session_state.page
        else:
            if "page" not in st.session_state:
                st.session_state.page = "📊 我的分析"
            page_options = ["📊 我的分析", "👤 个人设置"]
            selected = st.radio(
                "导航",
                page_options,
                index=page_options.index(st.session_state.page),
                key="user_nav"
            )
            if selected != st.session_state.page:
                st.session_state.page = selected
                st.rerun()
            page = st.session_state.page

        st.divider()
        if st.button("🚪 退出登录"):
            logout()

    # ===== 页面路由 =====
    if role == "admin":
        if page == "📊 用户面板":
            from pages.admin_dashboard import show
            show()
        elif page == "📊 我的分析":
            from pages.user_dashboard import show
            show(user_id)   # 管理员自己的分析列表
        elif page == "🧠 模型训练":
            from pages.admin_model import show
            show()
        elif page == "⚙️ 模型设置":
            from pages.admin_settings import show
            show()
        elif page == "👥 用户管理":
            from pages.admin_users import show
            show()
    else:
        if page == "📊 我的分析":
            from pages.user_dashboard import show
            show(user_id)
        elif page == "👤 个人设置":
            from pages.user_settings import show
            show(user_id)

if __name__ == "__main__":
    main()