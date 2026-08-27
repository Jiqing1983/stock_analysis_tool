"""
股票分析服务
"""
import json
import logging
import re
from typing import List, Dict, Any, Optional
from datetime import datetime

from .deepseek_client import DeepSeekClient
from database.db_manager import db_manager
from database.models import StockAnalysis, User, ModelConfig, ModelTrainingLog

logger = logging.getLogger(__name__)


class StockAnalysisService:
    """股票分析服务"""
    
    # 默认分析模板字段
    DEFAULT_FIELDS = [
        "股票名称", "股票代码", "综合评分", "赔率", 
        "目标价格", "现价", "分析日期", "推荐评级", 
        "分析摘要", "风险提示"
    ]
    
    def __init__(self, deepseek_client: DeepSeekClient = None):
        self.client = deepseek_client or DeepSeekClient()
        self._analysis_template = None
    
    def get_analysis_template(self) -> List[str]:
        """获取分析模板字段列表"""
        if self._analysis_template:
            return self._analysis_template
        
        with db_manager.get_session() as session:
            config = session.query(ModelConfig).filter_by(
                config_key="analysis_template"
            ).first()
            
            if config:
                try:
                    fields = json.loads(config.config_value)
                    if isinstance(fields, list):
                        self._analysis_template = fields
                        return fields
                except:
                    pass
            
            self._analysis_template = self.DEFAULT_FIELDS
            return self._analysis_template
    
    def set_analysis_template(self, fields: List[str], updated_by: str = "admin"):
        """设置分析模板"""
        with db_manager.get_session() as session:
            config = session.query(ModelConfig).filter_by(
                config_key="analysis_template"
            ).first()
            
            if config:
                config.config_value = json.dumps(fields, ensure_ascii=False)
                config.updated_by = updated_by
            else:
                config = ModelConfig(
                    config_key="analysis_template",
                    config_value=json.dumps(fields, ensure_ascii=False),
                    description="股票分析输出字段模板",
                    updated_by=updated_by
                )
                session.add(config)
            
            self._analysis_template = fields
    
    def get_training_context(self) -> List[Dict[str, str]]:
        """获取当前激活的训练对话历史（作为上下文）"""
        with db_manager.get_session() as session:
            log = session.query(ModelTrainingLog).filter_by(
                status='active'
            ).order_by(
                ModelTrainingLog.created_at.desc()
            ).first()
            if log and log.messages:
                return log.messages
        return []
    
    def parse_stock_codes(self, input_text: str) -> List[str]:
        """
        解析股票代码
        支持逗号、分号、空格、换行等分隔符
        """
        if not input_text:
            return []
        
        # 使用正则分割
        codes = re.split(r'[,;，；\s\n]+', input_text.strip())
        # 过滤空字符串
        codes = [c.strip() for c in codes if c.strip()]
        return codes
    
    def _get_train_settings(self) -> Dict[str, Any]:
        """
        从数据库读取模型训练页面的参数设置。
        若未保存则返回默认值。
        """
        default_settings = {
            "model": "deepseek-v4-flash",
            "max_tokens": 4096,
            "temperature": 0.7,
            "enable_search": True,
            "system_prompt": "你是一位专业的股票分析师，拥有丰富的金融市场分析经验。请基于可获得的信息，对股票进行客观、全面的分析。"
        }
        try:
            with db_manager.get_session() as session:
                config = session.query(ModelConfig).filter_by(
                    config_key="train_settings"
                ).first()
                if config:
                    saved = json.loads(config.config_value)
                    # 只更新存在的键，保留默认值
                    default_settings.update(saved)
        except Exception as e:
            logger.warning(f"读取训练参数配置失败: {e}")
        return default_settings
    
    def analyze_stock(
        self,
        stock_code: str,
        user_id: int,
        system_prompt: str = None,
        enable_search: bool = None  # 可选，若为None则使用保存的设置
    ) -> Dict[str, Any]:
        """
        分析单只股票，自动注入训练上下文，并使用保存的训练参数
        """
        try:
            # 1. 读取训练参数设置
            train_settings = self._get_train_settings()
            model_name = train_settings["model"]
            max_tokens = train_settings["max_tokens"]
            temperature = train_settings["temperature"]
            # 如果调用时未显式指定 enable_search，则使用保存的设置
            if enable_search is None:
                enable_search = train_settings.get("enable_search", True)
            # 如果调用时传入了 system_prompt，优先使用传入的，否则使用保存的
            if system_prompt is None:
                system_prompt = train_settings.get("system_prompt", self._get_default_system_prompt())
            
            # 2. 获取训练上下文
            training_history = self.get_training_context()
            logger.info(f"分析 {stock_code}, 训练上下文消息数: {len(training_history)}")
            
            # 3. 处理系统提示（优先从训练历史中提取，覆盖上面读到的 system_prompt）
            sys_prompt = system_prompt
            filtered_history = []
            for msg in training_history:
                if msg.get("role") == "system":
                    sys_prompt = msg.get("content", sys_prompt)
                    logger.info(f"使用训练历史的系统提示: {sys_prompt[:50]}...")
                else:
                    filtered_history.append(msg)
            
            # 4. 构建分析提示词（传入是否有上下文）
            prompt = self._build_analysis_prompt(stock_code, has_training_context=bool(training_history))
            
            # 5. 组装 messages
            messages = []
            messages.append({"role": "system", "content": sys_prompt})
            if filtered_history:
                messages.extend(filtered_history)
            messages.append({"role": "user", "content": prompt})
            
            logger.info(f"最终消息数: {len(messages)} (包含 {len(filtered_history)} 条历史)")
            logger.info(f"使用模型: {model_name}, max_tokens={max_tokens}, temperature={temperature}, enable_search={enable_search}")
            
            # 6. 调用 API（使用从数据库读取的参数）
            result = self.client.chat(
                messages=messages,
                model=model_name,
                enable_search=enable_search,
                trim_to=50000,
                max_tokens=max_tokens,
                temperature=temperature
            )
            
            # 7. 解析分析结果
            analysis_data = self._parse_analysis_result(result["content"], stock_code)
            
            tokens_used = result["usage"]["total_tokens"]
            cost = tokens_used / 1000 * 0.01  # 0.01 元/1000 token
            
            # 8. 保存到数据库
            with db_manager.get_session() as session:
                analysis = StockAnalysis(
                    user_id=user_id,
                    stock_code=stock_code,
                    stock_name=analysis_data.get("股票名称", stock_code),
                    analysis_data=analysis_data,
                    tokens_used=tokens_used,
                    cost=cost,
                    raw_report=result["content"],
                    analysis_date=datetime.utcnow()
                )
                session.add(analysis)
                
                # 更新用户 token 使用量
                user = session.query(User).filter_by(id=user_id).first()
                if user:
                    user.total_tokens_used += tokens_used
                    user.balance -= cost
            
            return {
                "success": True,
                "analysis": analysis_data,
                "raw_report": result["content"],
                "tokens_used": tokens_used,
                "cost": cost
            }
            
        except Exception as e:
            logger.error(f"分析股票 {stock_code} 失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "stock_code": stock_code
            }
    
    def analyze_stocks_batch(
        self,
        stock_codes: List[str],
        user_id: int,
        system_prompt: str = None,
        enable_search: bool = None,
        on_progress: callable = None
    ) -> List[Dict[str, Any]]:
        """批量分析股票，每分析一个保存一个"""
        results = []
        total = len(stock_codes)
        
        for i, code in enumerate(stock_codes):
            if on_progress:
                on_progress(i + 1, total, code)
            
            result = self.analyze_stock(
                stock_code=code,
                user_id=user_id,
                system_prompt=system_prompt,
                enable_search=enable_search
            )
            results.append(result)
        
        return results
    
    def reanalyze_stock(self, analysis_id: int, user_id: int) -> Dict[str, Any]:
        """重新分析股票（更新已有分析）"""
        with db_manager.get_session() as session:
            analysis = session.query(StockAnalysis).filter_by(
                id=analysis_id,
                user_id=user_id
            ).first()
            
            if not analysis:
                return {"success": False, "error": "分析记录不存在"}
            
            stock_code = analysis.stock_code
        
        # 执行新分析
        new_result = self.analyze_stock(
            stock_code=stock_code,
            user_id=user_id
        )
        
        if new_result["success"]:
            # 更新原有记录
            with db_manager.get_session() as session:
                analysis = session.query(StockAnalysis).filter_by(id=analysis_id).first()
                if analysis:
                    analysis.analysis_data = new_result["analysis"]
                    analysis.raw_report = new_result["raw_report"]
                    analysis.tokens_used = new_result["tokens_used"]
                    analysis.cost = new_result["cost"]
                    analysis.analysis_date = datetime.utcnow()
        
        return new_result
    
    def delete_analysis(self, analysis_id: int, user_id: int) -> bool:
        """删除分析记录"""
        with db_manager.get_session() as session:
            analysis = session.query(StockAnalysis).filter_by(
                id=analysis_id,
                user_id=user_id
            ).first()
            
            if analysis:
                session.delete(analysis)
                return True
            return False
    
    def get_user_analyses(
        self,
        user_id: int,
        sort_by: str = "analysis_date",
        sort_desc: bool = True,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """获取用户的分析列表"""
        with db_manager.get_session() as session:
            query = session.query(StockAnalysis).filter_by(user_id=user_id)
            
            # 排序
            if sort_by == "analysis_date":
                order_col = StockAnalysis.analysis_date
            elif hasattr(StockAnalysis, sort_by):
                order_col = getattr(StockAnalysis, sort_by)
            else:
                order_col = StockAnalysis.analysis_date
            
            if sort_desc:
                query = query.order_by(order_col.desc())
            else:
                query = query.order_by(order_col.asc())
            
            analyses = query.offset(offset).limit(limit).all()
            
            # 获取模板字段
            fields = self.get_analysis_template()
            
            result = []
            for a in analyses:
                item = {
                    "id": a.id,
                    "stock_code": a.stock_code,
                    "stock_name": a.stock_name,
                    "analysis_date": a.analysis_date.isoformat(),
                    "tokens_used": a.tokens_used,
                    "cost": a.cost,
                    "data": a.to_dict(fields),
                    "raw_report": a.raw_report
                }
                result.append(item)
            
            return result
    
    def _build_analysis_prompt(self, stock_code: str, has_training_context: bool = False) -> str:
        """
        构建分析提示词，明确要求输出格式与模型设置中的表头一致。
        """
        # 获取当前的分析模板字段（表头设置）
        fields = self.get_analysis_template()
        # 构建字段输出格式说明，例如：
        # 字段1：值
        # 字段2：值
        fields_format = "\n".join([f"{f}：..." for f in fields])
        
        base_prompt = f"""请对股票 {stock_code} 进行分析

    **重要：请务必严格遵循我们之前的对话中确立的分析框架、风格和判断逻辑（如果有训练上下文）。**  
    **综合结论需基于上述所有分析得出，输出的最后必须包含以下字段顺序和名称，每个字段一行，冒号后跟具体内容：**

    {fields_format}

    股票代码：{stock_code}
    分析日期：（当前日期）

    请确保每个字段都有实际分析内容，不要缺失。
    """
        
        # 如果存在训练上下文，在开头添加更强指令
        if has_training_context:
            base_prompt = "请严格遵循我们之前对话中确立的分析框架、风格和判断逻辑，对股票进行分析。\n\n" + base_prompt
        
        return base_prompt

    def _get_default_system_prompt(self) -> str:
        """获取默认系统提示词"""
        return """你是一位专业的股票分析师，拥有丰富的金融市场分析经验。
请基于可获得的信息，对股票进行客观、全面的分析。
分析要数据驱动，避免主观臆断。
对于不确定的信息，请明确说明。
"""
    
    def _parse_analysis_result(self, content: str, stock_code: str) -> Dict[str, Any]:
        """解析AI返回的分析结果，提取各字段的值"""
        result = {}
        fields = self.get_analysis_template()
        
        # 简单解析：寻找"字段名：值"模式
        for field in fields:
            # 尝试多种匹配模式
            patterns = [
                rf'{field}[：:]\s*([^\n]+)',
                rf'{field}\s*[：:]\s*([^\n]+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    result[field] = match.group(1).strip()
                    break
            
            if field not in result:
                result[field] = ""
        
        # 确保必填字段
        if "股票代码" not in result or not result["股票代码"]:
            result["股票代码"] = stock_code
        
        if "分析日期" not in result or not result["分析日期"]:
            result["分析日期"] = datetime.now().strftime("%Y-%m-%d")
        
        return result