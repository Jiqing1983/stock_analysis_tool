import streamlit as st
from database.db_manager import db_manager
from database.models import User

def show():
    st.title("👥 用户管理")
    with db_manager.get_session() as session:
        users = session.query(User).all()
        if users:
            data = []
            for u in users:
                data.append({
                    "ID": u.id,
                    "用户名": u.username,
                    "邮箱": u.email,
                    "角色": u.role.value,
                    "余额": f"¥{u.balance:.2f}",
                    "已用Token": u.total_tokens_used,
                    "会员到期": u.membership_expiry.strftime("%Y-%m-%d") if u.membership_expiry else "无",
                    "激活": "✅" if u.is_active else "❌"
                })
            st.dataframe(data, use_container_width=True)
        else:
            st.info("暂无用户")