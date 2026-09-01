"""
管理员仪表盘 - 赔率排名 TOP 20（支持价格刷新 + 日志显示）
"""
import streamlit as st
import pandas as pd
import re
from datetime import datetime
from database.db_manager import db_manager
from database.models import User, StockAnalysis
from core.stock_service import StockAnalysisService
from sqlalchemy.orm.attributes import flag_modified


def extract_number(value):
    """从可能包含单位/文字的字符串中提取数字"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r'(\d+\.?\d*)', value)
        if match:
            return float(match.group(1))
    return None


def update_price_in_text(text, new_price):
    """保留文字，只替换价格数字部分"""
    if text is None:
        return str(new_price)
    text_str = str(text)
    match = re.search(r'(\d+\.?\d*)', text_str)
    if match:
        prefix = text_str[:match.start()]
        suffix = text_str[match.end():]
        formatted_price = f"{new_price:.2f}"
        return f"{prefix}{formatted_price}{suffix}"
    return str(new_price)


def show():
    st.title("📊 管理员仪表盘")
    st.subheader("🏆 股票分析赔率排名 TOP 20（全体用户）")
    st.caption("按赔率由高到低排序，点击「查看报告」可查看完整分析内容")
    
    if "refresh_completed" not in st.session_state:
        st.session_state.refresh_completed = False
    if "refresh_logs" not in st.session_state:
        st.session_state.refresh_logs = []
    
    # 获取排名数据
    with db_manager.get_session() as session:
        analyses = session.query(StockAnalysis).order_by(
            StockAnalysis.analysis_date.desc()
        ).all()
        
        users = session.query(User).all()
        user_map = {user.id: user.username for user in users}
        
        ranking = []
        for a in analyses:
            data = a.analysis_data
            if data and "赔率" in data:
                odds = extract_number(data.get("赔率"))
                if odds is None:
                    continue
                
                username = user_map.get(a.user_id, "未知")
                target_price_num = extract_number(data.get("目标价格"))
                current_price_num = extract_number(data.get("现价"))
                
                ranking.append({
                    "id": a.id,
                    "用户": username,
                    "股票代码": a.stock_code,
                    "股票名称": a.stock_name or "",
                    "目标价格": target_price_num,
                    "现价": current_price_num,
                    "赔率": odds,
                    "分析日期": a.analysis_date.strftime("%Y-%m-%d %H:%M"),
                    "评分": data.get("综合评分", "N/A"),
                    "原始报告": a.raw_report,
                })
    
    if not ranking:
        st.info("暂无分析记录")
        return
    
    ranking_sorted = sorted(ranking, key=lambda x: x["赔率"], reverse=True)
    top_20 = ranking_sorted[:20]
    
    # ========== 刷新按钮 + 日志窗口 ==========
    st.subheader("🔄 价格刷新控制台")
    
    log_container = st.container(height=200, border=True)
    
    col_refresh, col_info = st.columns([1, 3])
    with col_refresh:
        refresh_clicked = st.button("🔄 刷新价格", use_container_width=True, type="primary")
    
    with col_info:
        st.caption(f"📌 共 {len(top_20)} 只股票，点击「刷新价格」获取最新股价并重新计算赔率")
    
    if refresh_clicked:
        service = StockAnalysisService()
        logs = []
        
        def add_log(stock_code, status, message, price=None):
            timestamp = datetime.now().strftime("%H:%M:%S")
            logs.append({
                "时间": timestamp,
                "股票代码": stock_code,
                "状态": status,
                "消息": message,
                "价格": price
            })
        
        stock_codes = list(set([row["股票代码"] for row in top_20]))
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        def on_progress(current, total, code):
            progress_bar.progress(current / total)
            status_text.text(f"正在获取 {code} 的最新价格... ({current}/{total})")
        
        add_log("系统", "info", f"开始获取 {len(stock_codes)} 只股票的最新价格...")
        
        price_results = service.update_stock_prices(stock_codes, on_progress)
        
        success_count = 0
        fail_count = 0
        updated_count = 0
        
        with db_manager.get_session() as session:
            for stock_code, new_price in price_results.items():
                if new_price is not None:
                    success_count += 1
                    add_log(stock_code, "success", f"价格获取成功: ¥{new_price:.2f}", new_price)
                    
                    analyses_to_update = session.query(StockAnalysis).filter_by(
                        stock_code=stock_code
                    ).all()
                    
                    for a in analyses_to_update:
                        data = a.analysis_data
                        if data is None:
                            data = {}
                        
                        old_price_text = data.get("现价", str(new_price))
                        new_price_text = update_price_in_text(old_price_text, new_price)
                        data["现价"] = new_price_text
                        add_log(stock_code, "info", f"现价更新: {old_price_text} -> {new_price_text}")
                        
                        target_text = data.get("目标价格")
                        if target_text:
                            target_num = extract_number(target_text)
                            if target_num and target_num > 0 and new_price > 0:
                                new_odds = target_num / new_price
                                data["赔率"] = str(round(new_odds, 2))
                                add_log(stock_code, "info", f"赔率更新: {round(new_odds, 2)}")
                        
                        a.analysis_data = data
                        flag_modified(a, "analysis_data")  # ⭐ 关键：标记已修改
                        updated_count += 1
                    
                    session.commit()
                    add_log(stock_code, "info", f"已更新 {len(analyses_to_update)} 条分析记录")
                else:
                    fail_count += 1
                    add_log(stock_code, "error", "价格获取失败")
            
            session.commit()
        
        add_log("系统", "info", f"✅ 刷新完成！成功 {success_count} 只，失败 {fail_count} 只，更新记录 {updated_count} 条")
        
        progress_bar.progress(1.0)
        status_text.text("✅ 价格刷新完成！")
        
        st.session_state.refresh_logs = logs
        st.session_state.refresh_completed = True
        st.rerun()
    
    # 显示日志
    if st.session_state.refresh_completed and st.session_state.refresh_logs:
        logs = st.session_state.refresh_logs
        
        with log_container:
            for log in logs:
                if log["状态"] == "success":
                    icon = "✅"
                elif log["状态"] == "error":
                    icon = "❌"
                elif log["状态"] == "info":
                    icon = "ℹ️"
                else:
                    icon = "⚪"
                
                price_str = f" (¥{log['价格']:.2f})" if log.get("价格") else ""
                st.markdown(
                    f"`{log['时间']}`  {icon} **{log['股票代码']}** {log['消息']}{price_str}",
                    unsafe_allow_html=True
                )
        
        if st.button("🗑️ 清空日志"):
            st.session_state.refresh_logs = []
            st.session_state.refresh_completed = False
            st.rerun()
    
    st.divider()
    
    # ========== 显示排名表格 ==========
    if top_20:
        display_data = []
        for row in top_20:
            display_data.append({
                "用户": row["用户"],
                "股票代码": row["股票代码"],
                "股票名称": row["股票名称"],
                "目标价格": f"{row['目标价格']:.2f}" if row['目标价格'] else "N/A",
                "现价": f"{row['现价']:.2f}" if row['现价'] else "N/A",
                "赔率": f"{row['赔率']:.2f}",
                "分析日期": row["分析日期"],
                "评分": row["评分"]
            })
        
        df = pd.DataFrame(display_data)
        
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "用户": st.column_config.TextColumn("用户"),
                "股票代码": st.column_config.TextColumn("股票代码"),
                "股票名称": st.column_config.TextColumn("名称"),
                "目标价格": st.column_config.TextColumn("目标价格"),
                "现价": st.column_config.TextColumn("现价"),
                "赔率": st.column_config.TextColumn("赔率"),
                "分析日期": st.column_config.TextColumn("分析日期"),
                "评分": st.column_config.TextColumn("综合评分")
            }
        )
        
        col1, col2, col3 = st.columns(3)
        with col1:
            odds_values = [r["赔率"] for r in top_20 if r["赔率"]]
            st.metric("📊 TOP 20 平均赔率", f"{sum(odds_values)/len(odds_values):.2f}" if odds_values else "N/A")
        with col2:
            st.metric("📈 最高赔率", f"{max(odds_values):.2f}" if odds_values else "N/A")
        with col3:
            stock_count = len(set(r["股票代码"] for r in top_20))
            st.metric("📋 涉及股票数", stock_count)
        
        st.divider()
        
        st.subheader("📄 查看原始分析报告")
        report_options = {
            f"{row['股票代码']} ({row['股票名称']}) - 赔率: {row['赔率']:.2f}": row 
            for row in top_20
        }
        
        if report_options:
            selected_label = st.selectbox("选择要查看报告的股票", list(report_options.keys()))
            
            if selected_label:
                selected = report_options[selected_label]
                with st.expander(f"📝 {selected['股票代码']} 的完整报告", expanded=True):
                    st.markdown(f"**用户**：{selected['用户']}")
                    st.markdown(f"**分析日期**：{selected['分析日期']}")
                    st.markdown(f"**综合评分**：{selected['评分']}")
                    st.markdown(f"**目标价格**：{selected['目标价格']:.2f}" if selected['目标价格'] else "**目标价格**：N/A")
                    st.markdown(f"**现价**：{selected['现价']:.2f}" if selected['现价'] else "**现价**：N/A")
                    st.markdown(f"**赔率**：{selected['赔率']:.2f}")
                    st.markdown("---")
                    st.markdown(selected.get("原始报告", "暂无报告内容"))
    else:
        st.info("暂无有效的赔率数据")