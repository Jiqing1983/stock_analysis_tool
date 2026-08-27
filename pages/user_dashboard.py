"""
用户分析主页面
"""
import streamlit as st
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any

from core.stock_service import StockAnalysisService
from core.token_manager import TokenManager
from core.deepseek_client import DeepSeekClient


def show(user_id: int):
    """显示用户分析页面"""
    st.title("📊 股票分析")
    
    # 初始化服务
    service = StockAnalysisService()
    token_manager = TokenManager()
    
    # 获取用户信息
    user_info = token_manager.get_user_info(user_id)
    if user_info:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("💰 余额", f"¥{user_info['balance']:.2f}")
        with col2:
            st.metric("📊 已用Token", f"{user_info['total_tokens_used']:,}")
        with col3:
            status = "✅ 有效" if user_info.get('is_member_active') else "❌ 已过期"
            st.metric("💎 会员状态", status)
    
    st.divider()
    
    # === 输入区域 ===
    st.subheader("📝 输入股票代码")
    
    with st.form("analysis_form"):
        stock_input = st.text_area(
            "请输入股票代码（多个用逗号、分号、空格分隔）",
            placeholder="例如：600036, 000001, 601318",
            height=80,
            help="支持A股代码，多个股票请用分隔符分开"
        )
        
        col1, col2 = st.columns(2)
        with col1:
            enable_search = st.checkbox("🔍 启用联网搜索", value=True)
        with col2:
            # 显示预计费用
            codes = service.parse_stock_codes(stock_input) if stock_input else []
            if codes:
                estimated_tokens = len(codes) * 10000  # 估算
                estimated_cost = estimated_tokens / 1000 * 0.01
                st.info(f"预计分析 {len(codes)} 只股票，费用约 ¥{estimated_cost:.2f}")
        
        submitted = st.form_submit_button("🚀 开始分析", use_container_width=True)
    
    if submitted and stock_input:
        codes = service.parse_stock_codes(stock_input)
        if not codes:
            st.warning("请输入有效的股票代码")
            return
        
        # 检查余额
        balance = token_manager.get_user_balance(user_id)
        estimated_cost = len(codes) * 0.1  # 粗略估算
        if balance < estimated_cost:
            st.error(f"余额不足！需要约 ¥{estimated_cost:.2f}，当前余额 ¥{balance:.2f}")
            return
        
        # 执行分析
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        results = service.analyze_stocks_batch(
            stock_codes=codes,
            user_id=user_id,
            enable_search=enable_search,
            on_progress=lambda i, total, code: (
                progress_bar.progress(i / total),
                status_text.text(f"正在分析 {code} ({i}/{total})...")
            )
        )
        
        progress_bar.progress(1.0)
        status_text.text("✅ 分析完成！")
        
        # 显示结果
        success_count = sum(1 for r in results if r.get("success"))
        fail_count = len(results) - success_count
        
        if fail_count > 0:
            st.warning(f"分析完成：成功 {success_count} 只，失败 {fail_count} 只")
            for r in results:
                if not r.get("success"):
                    st.error(f"❌ {r.get('stock_code')}: {r.get('error')}")
        else:
            st.success(f"✅ 全部 {success_count} 只股票分析完成！")
        
        st.rerun()
    
    st.divider()
    
    # === 分析列表 ===
    st.subheader("📋 我的分析列表")
    
    # 获取分析列表
    analyses = service.get_user_analyses(user_id, limit=200)
    
    if not analyses:
        st.info("暂无分析记录，请在上方输入股票代码开始分析")
        return
    
    # 转换为DataFrame
    df_data = []
    fields = service.get_analysis_template()
    
    for a in analyses:
        row = {
            "ID": a["id"],
            "股票代码": a["stock_code"],
            "股票名称": a.get("stock_name", ""),
            "分析日期": a["analysis_date"][:10] if a["analysis_date"] else "",
            "Token": a["tokens_used"],
            "费用": f"¥{a['cost']:.3f}" if a["cost"] else "¥0.000"
        }
        # 添加模板字段
        for f in fields:
            if f in a.get("data", {}):
                row[f] = a["data"].get(f, "")
        df_data.append(row)
    
    df = pd.DataFrame(df_data)
    
    # 显示表格
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "ID": st.column_config.NumberColumn("ID", width="small"),
            "股票代码": st.column_config.TextColumn("股票代码", width="small"),
            "分析日期": st.column_config.TextColumn("分析日期", width="small"),
            "Token": st.column_config.NumberColumn("Token", width="small"),
            "费用": st.column_config.TextColumn("费用", width="small"),
        }
    )
    
    # === 批量操作 ===
    st.subheader("🔧 批量操作")
    
    # 多选
    selected_ids = st.multiselect(
        "选择要操作的股票",
        options=[a["id"] for a in analyses],
        format_func=lambda x: f"{next(a['stock_code'] for a in analyses if a['id']==x)}"
    )
    
    if selected_ids:
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("🔄 重新分析选中", use_container_width=True):
                for aid in selected_ids:
                    result = service.reanalyze_stock(aid, user_id)
                    if result.get("success"):
                        st.success(f"✅ 更新成功: {result.get('stock_code')}")
                    else:
                        st.error(f"❌ 更新失败: {result.get('error')}")
                st.rerun()
        
        with col2:
            if st.button("🗑️ 删除选中", use_container_width=True):
                for aid in selected_ids:
                    if service.delete_analysis(aid, user_id):
                        st.success(f"✅ 已删除")
                st.rerun()
        
        with col3:
            if st.button("📊 导出选中", use_container_width=True):
                # 导出为CSV
                selected_data = [a for a in analyses if a["id"] in selected_ids]
                export_df = pd.DataFrame(selected_data)
                csv = export_df.to_csv(index=False)
                st.download_button(
                    "下载CSV",
                    data=csv,
                    file_name=f"stock_analysis_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv"
                )
    
    st.divider()
    
   # === 查看详情 ===
    st.subheader("📄 查看分析详情")

    # 选择要查看的分析
    analysis_options = {f"{a['stock_code']} ({a['analysis_date'][:10]})": a["id"] for a in analyses}
    selected_label = st.selectbox("选择要查看的分析", list(analysis_options.keys()))

    if selected_label:
        aid = analysis_options[selected_label]
        analysis = next(a for a in analyses if a["id"] == aid)
        
        # 使用两列布局展示结构化数据
        with st.expander("📊 分析数据", expanded=True):
            data = analysis.get("data", {})
            # 按模板顺序显示
            fields = service.get_analysis_template()
            # 将数据分成两列
            cols = st.columns(2)
            for i, field in enumerate(fields):
                value = data.get(field, "")
                with cols[i % 2]:
                    # 使用 markdown 加粗显示字段名，值保持原样
                    st.markdown(f"**{field}**：{value}")
        
        # 显示完整报告（使用 markdown 渲染）
        with st.expander("📝 完整报告"):
            raw = analysis.get("raw_report", "暂无报告")
            # 如果报告内容包含 Markdown 语法，直接渲染
            st.markdown(raw)
        
        # 操作按钮
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 重新分析"):
                result = service.reanalyze_stock(aid, user_id)
                if result.get("success"):
                    st.success("✅ 更新成功")
                    st.rerun()
                else:
                    st.error(f"❌ 更新失败: {result.get('error')}")
        with col2:
            if st.button("🗑️ 删除"):
                if service.delete_analysis(aid, user_id):
                    st.success("✅ 已删除")
                    st.rerun()