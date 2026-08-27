import streamlit as st

def show(user_id: int):
    st.title("👤 个人设置")
    st.write(f"用户ID: {user_id}")
    st.info("此页面可查看注册信息、充值记录等。")
    # 后续可展示用户详细信息、充值历史、会员状态等