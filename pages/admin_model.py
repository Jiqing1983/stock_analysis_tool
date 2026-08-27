"""
管理员 - 模型训练页面
"""
import streamlit as st
from datetime import datetime
import json

from core.deepseek_client import DeepSeekClient
from database.db_manager import db_manager
from database.models import ModelTrainingLog, ModelConfig


def show():
    """显示模型训练页面"""
    st.title("🧠 模型训练与管理")
    
    # ========== 加载保存的训练参数 ==========
    train_settings = {
        "model": "deepseek-v4-flash",
        "max_tokens": 32000,
        "temperature": 0.7,
        "enable_search": True,
        "system_prompt": "你是一位专业的股票分析师，拥有丰富的金融市场分析经验。请基于可获得的信息，对股票进行客观、全面的分析。"
    }
    
    with db_manager.get_session() as session:
        config = session.query(ModelConfig).filter_by(
            config_key="train_settings"
        ).first()
        if config:
            try:
                saved = json.loads(config.config_value)
                train_settings.update(saved)
                # 打印日志（调试）
                print(f"加载训练参数: {saved}")
            except Exception as e:
                print(f"加载训练参数失败: {e}")
    
    # 初始化 DeepSeek 客户端
    if "train_client" not in st.session_state:
        st.session_state.train_client = DeepSeekClient()
        st.session_state.train_history = []
        st.session_state.train_session_id = None
        st.session_state.auto_load_notified = False
    
    client = st.session_state.train_client
    
    # ========== 自动加载激活的会话 ==========
    active_session_id = None
    active_messages = []
    
    with db_manager.get_session() as session:
        active_log = session.query(ModelTrainingLog).filter_by(
            status='active'
        ).order_by(
            ModelTrainingLog.created_at.desc()
        ).first()
        
        if active_log:
            active_session_id = active_log.session_id
            active_messages = active_log.messages
    
    if active_session_id:
        if st.session_state.train_session_id != active_session_id:
            st.session_state.train_history = active_messages
            client._conversation_history = active_messages
            st.session_state.train_session_id = active_session_id
            if not st.session_state.auto_load_notified:
                st.info(f"已自动加载激活的会话: {active_session_id}")
                st.session_state.auto_load_notified = True
    else:
        if st.session_state.train_session_id is not None:
            st.session_state.train_history = []
            client._conversation_history = []
            st.session_state.train_session_id = None
            st.session_state.auto_load_notified = False
    
    history = st.session_state.train_history
    
    # === 模型配置（使用保存的参数作为默认值） ===
    with st.expander("⚙️ 模型配置", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            model_options = ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-v4-flash-vision-exp"]
            current_model = train_settings.get("model", "deepseek-v4-flash")
            try:
                default_index = model_options.index(current_model)
            except ValueError:
                default_index = 0

            model = st.selectbox(
                "模型选择",
                model_options,
                index=default_index,
                key="train_model_select"
            )
            client.model = model
        
        with col2:
            max_tokens = st.number_input(
                "最大输出Token",
                min_value=100,
                max_value=32000,
                value=train_settings["max_tokens"],
                step=100,
                key="train_max_tokens"
            )
            temperature = st.slider(
                "温度",
                min_value=0.0,
                max_value=1.0,
                value=train_settings["temperature"],
                step=0.1,
                key="train_temperature"
            )
        
        enable_search = st.checkbox(
            "🔍 启用联网搜索",
            value=train_settings["enable_search"],
            key="train_enable_search"
        )
        
        # 系统提示词
        system_prompt = st.text_area(
            "系统提示词（System Prompt）",
            value=train_settings["system_prompt"],
            height=100,
            help="定义AI的角色和行为准则",
            key="train_system_prompt"
        )
        
        # 显示当前生效的 max_tokens（调试信息）
        st.caption(f"当前最大Token: {max_tokens} (将在下次对话时生效)")
        
        # 保存参数按钮
        if st.button("💾 保存参数设置", use_container_width=True):
            new_settings = {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "enable_search": enable_search,
                "system_prompt": system_prompt
            }
            with db_manager.get_session() as session:
                config = session.query(ModelConfig).filter_by(
                    config_key="train_settings"
                ).first()
                if config:
                    config.config_value = json.dumps(new_settings, ensure_ascii=False)
                else:
                    config = ModelConfig(
                        config_key="train_settings",
                        config_value=json.dumps(new_settings, ensure_ascii=False),
                        description="模型训练参数设置"
                    )
                    session.add(config)
            st.success(f"✅ 参数已保存（最大Token: {max_tokens}）")
            # 刷新页面，使新参数立即生效
            st.rerun()
    
    # === 对话区域 ===
    st.subheader("💬 对话训练")
    
    if history:
        with st.container():
            st.success(f"当前会话: {st.session_state.train_session_id}，包含 {len(history)} 条消息")
            if st.button("清空当前会话历史"):
                client.clear_history()
                st.session_state.train_history = []
                st.session_state.train_session_id = None
                st.rerun()
    else:
        st.info("当前无会话历史。您可以开始新对话，或从历史会话中加载。")
    
    # 显示历史对话
    if history:
        for i, msg in enumerate(history):
            role = "👤 用户" if msg["role"] == "user" else "🤖 助手"
            with st.chat_message(msg["role"]):
                st.write(msg["content"])
                if st.button(f"🗑️ 删除此对话", key=f"del_{i}"):
                    if st.session_state.get(f"confirm_del_{i}", False):
                        if client.delete_history_item(i):
                            st.session_state.train_history = client.get_history()
                            st.rerun()
                    else:
                        st.session_state[f"confirm_del_{i}"] = True
                        st.warning(f"再次点击确认删除对话 {i//2 + 1}")
    
    # === 输入新消息 ===
    user_input = st.chat_input("输入训练指令或股票分析问题...")
    
    if user_input:
        with st.chat_message("user"):
            st.write(user_input)
        
        with st.chat_message("assistant"):
            with st.spinner("AI思考中..."):
                try:
                    # ===== 关键：显式传递所有参数 =====
                    result = client.chat_with_history(
                        user_message=user_input,
                        system_prompt=system_prompt,
                        enable_search=enable_search,
                        max_tokens=max_tokens,          # 传递当前控件值
                        temperature=temperature,        # 传递当前控件值
                        model=model                     # 传递模型
                    )
                    
                    st.write(result["content"])
                    st.caption(f"Token使用: {result['usage']['total_tokens']} | 费用: ¥{result['usage']['total_tokens']/1000*0.01:.4f}")
                    
                    # 保存到数据库
                    current_session_id = st.session_state.train_session_id
                    if not current_session_id:
                        current_session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                        st.session_state.train_session_id = current_session_id
                    
                    with db_manager.get_session() as session:
                        log = session.query(ModelTrainingLog).filter_by(
                            session_id=current_session_id
                        ).first()
                        if log:
                            log.messages = client.get_history()
                            log.tokens_used = result["usage"]["total_tokens"]
                        else:
                            log = ModelTrainingLog(
                                session_id=current_session_id,
                                messages=client.get_history(),
                                tokens_used=result["usage"]["total_tokens"],
                                status="archived"
                            )
                            session.add(log)
                    
                    st.session_state.train_history = client.get_history()
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"调用失败: {e}")
    
    # === 上下文管理 ===
    st.divider()
    st.subheader("📊 上下文管理")
    
    if history:
        total_tokens = client.count_messages_tokens(history)
        st.info(f"当前上下文 Token: {total_tokens} / {client.MAX_CONTEXT_TOKENS}")
        
        if total_tokens > client.MAX_CONTEXT_TOKENS * 0.8:
            if st.button("✂️ 裁剪上下文（保留最新对话）"):
                trimmed = client.trim_context(
                    [{"role": "user" if i%2==0 else "assistant", "content": h["content"]} 
                     for i, h in enumerate(history)],
                    max_tokens=40000
                )
                new_history = []
                for msg in trimmed:
                    if msg["role"] == "user":
                        new_history.append({"role": "user", "content": msg["content"]})
                    else:
                        new_history.append({"role": "assistant", "content": msg["content"]})
                client._conversation_history = new_history
                st.session_state.train_history = new_history
                st.success("✅ 上下文已裁剪")
                st.rerun()
    else:
        st.info("暂无对话历史")
    
    # === 会话管理 ===
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 新建会话"):
            client.clear_history()
            st.session_state.train_history = []
            st.session_state.train_session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            st.session_state.auto_load_notified = False
            st.success("✅ 已新建会话")
            st.rerun()
    
    with col2:
        if st.button("💾 保存当前会话（存档）"):
            if not st.session_state.train_history:
                st.warning("当前无对话历史可保存")
            else:
                current_session_id = st.session_state.train_session_id
                if not current_session_id:
                    current_session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    st.session_state.train_session_id = current_session_id
                
                with db_manager.get_session() as session:
                    log = session.query(ModelTrainingLog).filter_by(
                        session_id=current_session_id
                    ).first()
                    if log:
                        log.messages = client.get_history()
                        log.status = "archived"
                    else:
                        log = ModelTrainingLog(
                            session_id=current_session_id,
                            messages=client.get_history(),
                            status="archived"
                        )
                        session.add(log)
                st.success("✅ 会话已保存（状态：存档）")
    
    # === 历史会话 ===
    with st.expander("📚 历史会话", expanded=False):
        logs_data = []
        with db_manager.get_session() as session:
            logs = session.query(ModelTrainingLog).order_by(
                ModelTrainingLog.created_at.desc()
            ).limit(20).all()
            
            for log in logs:
                logs_data.append({
                    "id": log.id,
                    "session_id": log.session_id,
                    "created_at": log.created_at.strftime('%Y-%m-%d %H:%M'),
                    "tokens_used": log.tokens_used,
                    "status": log.status,
                    "messages": log.messages
                })
        
        if logs_data:
            for log_data in logs_data:
                col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                with col1:
                    st.write(f"**{log_data['session_id']}**")
                    st.caption(f"创建: {log_data['created_at']} | Token: {log_data['tokens_used']} | 状态: {'✅ 激活' if log_data['status']=='active' else '📦 存档'}")
                with col2:
                    if st.button("📂 加载", key=f"load_{log_data['id']}"):
                        st.session_state.train_history = log_data['messages']
                        client._conversation_history = log_data['messages']
                        st.session_state.train_session_id = log_data['session_id']
                        st.rerun()
                with col3:
                    if log_data['status'] != 'active':
                        if st.button("✅ 激活", key=f"activate_{log_data['id']}"):
                            with db_manager.get_session() as sess:
                                sess.query(ModelTrainingLog).update({"status": "archived"})
                                log_to_activate = sess.query(ModelTrainingLog).filter_by(
                                    id=log_data['id']
                                ).first()
                                if log_to_activate:
                                    log_to_activate.status = "active"
                                sess.commit()
                            st.session_state.train_history = log_data['messages']
                            client._conversation_history = log_data['messages']
                            st.session_state.train_session_id = log_data['session_id']
                            st.session_state.auto_load_notified = False
                            st.success(f"已激活会话 {log_data['session_id']}")
                            st.rerun()
                    else:
                        st.write("✅ 当前激活")
                with col4:
                    if st.button("🗑️ 删除", key=f"del_log_{log_data['id']}"):
                        if st.session_state.get(f"confirm_del_log_{log_data['id']}", False):
                            with db_manager.get_session() as sess:
                                log_to_delete = sess.query(ModelTrainingLog).filter_by(
                                    id=log_data['id']
                                ).first()
                                if log_to_delete:
                                    sess.delete(log_to_delete)
                                    sess.commit()
                            if st.session_state.train_session_id == log_data['session_id']:
                                st.session_state.train_history = []
                                client._conversation_history = []
                                st.session_state.train_session_id = None
                                st.session_state.auto_load_notified = False
                            st.rerun()
                        else:
                            st.session_state[f"confirm_del_log_{log_data['id']}"] = True
                            st.warning("再次点击确认删除")
        else:
            st.info("暂无历史会话")