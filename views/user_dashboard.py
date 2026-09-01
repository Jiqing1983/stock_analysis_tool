"""
用户分析主页面 - 稳定并发版
"""
import streamlit as st
import pandas as pd
from datetime import datetime

from core.stock_service import StockAnalysisService
from core.token_manager import TokenManager
from database.db_manager import db_manager
from database.models import StockAnalysis


def show(user_id: int):
    st.title("📊 股票分析")
    
    if "analyzing" not in st.session_state:
        st.session_state.analyzing = False
    if "analysis_task" not in st.session_state:
        st.session_state.analysis_task = None
    
    if st.session_state.analyzing and st.session_state.analysis_task is None:
        st.session_state.analyzing = False
    
    service = StockAnalysisService()
    token_manager = TokenManager()
    
    user_info = token_manager.get_user_info(user_id)
    if user_info:
        col1, col2 = st.columns(2)
        with col1:
            st.metric("📊 已用Token", f"{user_info['total_tokens_used']:,}")
        with col2:
            # 仅当会员有效时显示，否则留空
            if user_info.get('is_member_active'):
                st.metric("💎 会员状态", "✅ 有效")
    
    st.divider()
    
    # === 输入区域 ===
    st.subheader("📝 输入股票代码")
    
    with st.form("analysis_form"):
        stock_input = st.text_area(
            "请输入股票代码（多个用逗号、分号、空格分隔）",
            placeholder="例如：600036, 000001, 601318",
            height=80,
            help="支持A股代码，多个股票请用分隔符分开",
            disabled=st.session_state.analyzing
        )
        
        codes = service.parse_stock_codes(stock_input) if stock_input else []
        if codes:
            estimated_tokens = len(codes) * 10000
            estimated_cost = estimated_tokens / 1000 * 0.01
            st.info(f"预计分析 {len(codes)} 只股票，费用约 ¥{estimated_cost:.2f}")
        
        submitted = st.form_submit_button(
            "🚀 开始分析",
            use_container_width=True,
            disabled=st.session_state.analyzing
        )
    
    if submitted and stock_input and not st.session_state.analyzing:
        st.session_state.analyzing = True
        st.session_state.analysis_task = "batch"
        st.session_state.batch_codes = codes
        st.rerun()
    
    if st.session_state.analyzing:
        task = st.session_state.analysis_task
        try:
            if task == "batch":
                codes = st.session_state.get("batch_codes", [])
                if codes:
                    with st.spinner(f"正在分析 {len(codes)} 只股票，预计需要 {len(codes)*30} 秒..."):
                        results = service.analyze_stocks_batch(
                            stock_codes=codes,
                            user_id=user_id,
                            enable_search=True,
                            max_workers=2
                        )
                    success_count = sum(1 for r in results if r.get("success"))
                    fail_count = len(results) - success_count
                    if fail_count > 0:
                        st.warning(f"分析完成：成功 {success_count} 只，失败 {fail_count} 只")
                        for r in results:
                            if not r.get("success"):
                                st.error(f"❌ {r.get('stock_code')}: {r.get('error')}")
                    else:
                        st.success(f"✅ 全部 {success_count} 只股票分析完成！")
            
            elif task == "single_reanalyze":
                aid = st.session_state.get("single_reanalyze_id")
                if aid:
                    with st.spinner("正在重新分析..."):
                        result = service.reanalyze_stock(aid, user_id)
                    if result.get("success"):
                        st.success("✅ 更新成功")
                    else:
                        st.error(f"❌ 更新失败: {result.get('error')}")
            
            elif task == "batch_reanalyze":
                ids = st.session_state.get("batch_reanalyze_ids", [])
                if ids:
                    total = len(ids)
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    for idx, aid in enumerate(ids):
                        progress_bar.progress((idx + 1) / total)
                        status_text.text(f"正在重新分析 {idx+1}/{total}...")
                        result = service.reanalyze_stock(aid, user_id)
                        if result.get("success"):
                            st.success(f"✅ 更新成功: {result.get('stock_code')}")
                        else:
                            st.error(f"❌ 更新失败: {result.get('error')}")
                    progress_bar.progress(1.0)
                    status_text.text("✅ 批量重新分析完成！")
                    st.success("✅ 批量重新分析完成！")
        
        except Exception as e:
            st.error(f"分析过程中发生错误: {e}")
        finally:
            st.session_state.analyzing = False
            st.session_state.analysis_task = None
            for key in ["batch_codes", "single_reanalyze_id", "batch_reanalyze_ids"]:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()
    
    # === 分析列表 ===
    st.divider()
    st.subheader("📋 我的分析列表")
    
    analyses = service.get_user_analyses(user_id, limit=200)
    
    # 调试：如果列表为空，显示调试信息
    if not analyses:
        # 检查数据库中是否有该用户的记录
        with db_manager.get_session() as session:
            count = session.query(StockAnalysis).filter_by(user_id=user_id).count()
            if count > 0:
                st.info(f"⚠️ 数据库中有 {count} 条记录，但未能正确显示。请刷新页面或联系管理员。")
                # 尝试直接查询显示
                records = session.query(StockAnalysis).filter_by(user_id=user_id).limit(10).all()
                for r in records:
                    st.write(f"ID: {r.id}, 股票: {r.stock_code}, 日期: {r.analysis_date}")
            else:
                st.info("📭 暂无分析记录，请在上方输入股票代码开始分析")
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
        for f in fields:
            if f in a.get("data", {}):
                row[f] = a["data"].get(f, "")
        df_data.append(row)
    
    df = pd.DataFrame(df_data)
    
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
    
    selected_ids = st.multiselect(
        "选择要操作的股票",
        options=[a["id"] for a in analyses],
        format_func=lambda x: f"{next(a['stock_code'] for a in analyses if a['id']==x)}",
        disabled=st.session_state.analyzing
    )
    
    if selected_ids:
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button(
                "🔄 重新分析选中",
                use_container_width=True,
                disabled=st.session_state.analyzing
            ):
                st.session_state.analyzing = True
                st.session_state.analysis_task = "batch_reanalyze"
                st.session_state.batch_reanalyze_ids = selected_ids
                st.rerun()
        with col2:
            if st.button(
                "🗑️ 删除选中",
                use_container_width=True,
                disabled=st.session_state.analyzing
            ):
                for aid in selected_ids:
                    if service.delete_analysis(aid, user_id):
                        st.success(f"✅ 已删除")
                st.rerun()
        with col3:
            if st.button(
                "📊 导出选中",
                use_container_width=True,
                disabled=st.session_state.analyzing
            ):
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
    
    analysis_options = {f"{a['stock_code']} ({a['analysis_date'][:10]})": a["id"] for a in analyses}
    selected_label = st.selectbox(
        "选择要查看的分析",
        list(analysis_options.keys()),
        disabled=st.session_state.analyzing
    )
    
    if selected_label:
        aid = analysis_options[selected_label]
        analysis = next(a for a in analyses if a["id"] == aid)
        
        with st.expander("📊 分析数据", expanded=True):
            data = analysis.get("data", {})
            fields = service.get_analysis_template()
            cols = st.columns(2)
            for i, field in enumerate(fields):
                value = data.get(field, "")
                with cols[i % 2]:
                    st.markdown(f"**{field}**：{value}")
        
        with st.expander("📝 完整报告"):
            raw = analysis.get("raw_report", "暂无报告")
            st.markdown(raw)
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button(
                "🔄 重新分析",
                use_container_width=True,
                disabled=st.session_state.analyzing
            ):
                st.session_state.analyzing = True
                st.session_state.analysis_task = "single_reanalyze"
                st.session_state.single_reanalyze_id = aid
                st.rerun()
        with col2:
            if st.button(
                "🗑️ 删除",
                use_container_width=True,
                disabled=st.session_state.analyzing
            ):
                if service.delete_analysis(aid, user_id):
                    st.success("✅ 已删除")
                    st.rerun()