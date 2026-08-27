"""
管理员 - 模型设置页面
"""
import streamlit as st
import json
from datetime import datetime
from typing import List

from core.stock_service import StockAnalysisService
from database.db_manager import db_manager
from database.models import ModelConfig


def show():
    """显示模型设置页面"""
    st.title("⚙️ 模型设置")
    
    service = StockAnalysisService()
    
    # === 分析模板设置 ===
    st.subheader("📋 分析输出模板")
    st.caption("定义用户页面分析列表的显示字段")
    
    current_fields = service.get_analysis_template()
    st.info(f"当前模板字段: {', '.join(current_fields)}")
    
    # 输入方式
    input_method = st.radio(
        "选择输入方式",
        ["逗号分隔", "JSON数组", "直接编辑列表"],
        horizontal=True
    )
    
    template_input = ""
    if input_method == "逗号分隔":
        template_input = st.text_input(
            "输入字段名（英文逗号分隔）",
            value=",".join(current_fields),
            placeholder="股票名称,股票代码,综合评分,赔率,目标价格,现价,分析日期,推荐评级,分析摘要,风险提示"
        )
    elif input_method == "JSON数组":
        template_input = st.text_area(
            "粘贴JSON数组",
            value=json.dumps(current_fields, ensure_ascii=False),
            height=100,
            placeholder='["股票名称", "股票代码", "综合评分"]'
        )
    else:
        # 直接编辑列表
        template_input = st.text_area(
            "每行一个字段",
            value="\n".join(current_fields),
            height=150
        )
    
    if st.button("💾 保存模板", use_container_width=True):
        try:
            if input_method == "逗号分隔":
                fields = [f.strip() for f in template_input.split(",") if f.strip()]
            elif input_method == "JSON数组":
                fields = json.loads(template_input)
                if not isinstance(fields, list):
                    st.error("请输入有效的JSON数组")
                    return
            else:
                fields = [f.strip() for f in template_input.split("\n") if f.strip()]
            
            if not fields:
                st.error("至少需要1个字段")
                return
            
            service.set_analysis_template(fields, st.session_state.get("username", "admin"))
            st.success(f"✅ 模板已更新，共 {len(fields)} 个字段")
            st.rerun()
        except json.JSONDecodeError:
            st.error("JSON格式错误，请检查")
        except Exception as e:
            st.error(f"保存失败: {e}")
    
    # 预设模板
    st.caption("快速选择预设模板")
    presets = {
        "基础分析": ["股票名称", "股票代码", "综合评分", "推荐评级", "分析摘要"],
        "完整分析": ["股票名称", "股票代码", "综合评分", "赔率", "目标价格", "现价", "分析日期", "推荐评级", "分析摘要", "风险提示"],
        "技术分析": ["股票名称", "股票代码", "现价", "支撑位", "压力位", "RSI", "MACD", "均线", "技术评级"],
        "基本面分析": ["股票名称", "股票代码", "市盈率", "市净率", "ROE", "营收增长", "利润增长", "行业排名"]
    }
    
    cols = st.columns(len(presets))
    for i, (name, fields) in enumerate(presets.items()):
        with cols[i]:
            if st.button(f"📋 {name}", key=f"preset_{i}"):
                service.set_analysis_template(fields, st.session_state.get("username", "admin"))
                st.success(f"✅ 已切换到 '{name}' 模板")
                st.rerun()
    
    st.divider()
    
    # === 其他模型设置 ===
    st.subheader("🔧 其他设置")
    
    with db_manager.get_session() as session:
        # Token价格设置
        price_config = session.query(ModelConfig).filter_by(
            config_key="token_price"
        ).first()
        current_price = float(price_config.config_value) if price_config else 0.01
        
        new_price = st.number_input(
            "Token价格（元/1000 tokens）",
            min_value=0.001,
            max_value=1.0,
            value=current_price,
            step=0.001,
            format="%.3f"
        )
        
        if new_price != current_price:
            if st.button("💾 更新价格"):
                if price_config:
                    price_config.config_value = str(new_price)
                else:
                    config = ModelConfig(
                        config_key="token_price",
                        config_value=str(new_price),
                        description="每1000个token的价格"
                    )
                    session.add(config)
                st.success("✅ 价格已更新")
                st.rerun()
    
    # === 系统状态 ===
    st.divider()
    st.subheader("📊 系统状态")
    
    with db_manager.get_session() as session:
        # 用户统计
        from database.models import User, StockAnalysis
        total_users = session.query(User).count()
        total_analyses = session.query(StockAnalysis).count()
        today_analyses = session.query(StockAnalysis).filter(
            StockAnalysis.analysis_date >= datetime.now().replace(hour=0, minute=0, second=0)
        ).count()
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("👥 总用户数", total_users)
        with col2:
            st.metric("📊 总分析数", total_analyses)
        with col3:
            st.metric("📈 今日分析", today_analyses)