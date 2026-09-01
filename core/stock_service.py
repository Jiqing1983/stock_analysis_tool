"""
股票分析服务 - 支持并发，无 UI 交互，保证线程安全
"""
import json
import logging
import re
from typing import List, Dict, Any, Optional
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from .deepseek_client import DeepSeekClient
from database.db_manager import db_manager
from database.models import StockAnalysis, User, ModelConfig, ModelTrainingLog

logger = logging.getLogger(__name__)


class StockAnalysisService:
    DEFAULT_FIELDS = [
        "股票名称", "股票代码", "综合评分", "赔率", 
        "目标价格", "现价", "分析日期", "推荐评级", 
        "分析摘要", "风险提示"
    ]
    
    def __init__(self, deepseek_client: DeepSeekClient = None):
        self.client = deepseek_client or DeepSeekClient()
        self._analysis_template = None
    
    def get_analysis_template(self) -> List[str]:
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
        if not input_text:
            return []
        codes = re.split(r'[,;，；\s\n]+', input_text.strip())
        return [c.strip() for c in codes if c.strip()]
    
    def _get_train_settings(self) -> Dict[str, Any]:
        default_settings = {
            "model": "deepseek-v4-flash",
            "max_tokens": 100000,
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
                    default_settings.update(saved)
                    if "max_tokens" not in saved:
                        default_settings["max_tokens"] = 100000
        except Exception as e:
            logger.warning(f"读取训练参数配置失败: {e}")
        return default_settings
    
    def analyze_stock(
        self,
        stock_code: str,
        user_id: int,
        system_prompt: str = None,
        enable_search: bool = True
    ) -> Dict[str, Any]:
        """
        分析单只股票，纯计算，无 UI 交互
        """
        try:
            training_history = self.get_training_context()
            train_settings = self._get_train_settings()
            
            sys_prompt = system_prompt or train_settings.get("system_prompt", self._get_default_system_prompt())
            filtered_history = []
            for msg in training_history:
                if msg.get("role") == "system":
                    sys_prompt = msg.get("content", sys_prompt)
                else:
                    filtered_history.append(msg)
            
            prompt = self._build_analysis_prompt(stock_code, has_training_context=bool(training_history))
            
            messages = []
            messages.append({"role": "system", "content": sys_prompt})
            if filtered_history:
                messages.extend(filtered_history)
            messages.append({"role": "user", "content": prompt})
            
            model_name = train_settings.get("model", "deepseek-v4-flash")
            max_tokens = train_settings.get("max_tokens", 100000)
            temperature = train_settings.get("temperature", 0.7)
            
            result = self.client.chat(
                messages=messages,
                model=model_name,
                enable_search=enable_search,
                trim_to=50000,
                max_tokens=max_tokens,
                temperature=temperature
            )
            
            analysis_data = self._parse_analysis_result(result["content"], stock_code)
            tokens_used = result["usage"]["total_tokens"]
            cost = tokens_used / 1000 * 0.01
            
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
                user = session.query(User).filter_by(id=user_id).first()
                if user:
                    user.total_tokens_used += tokens_used
                    user.balance -= cost
                session.commit()
            
            return {
                "success": True,
                "analysis": analysis_data,
                "raw_report": result["content"],
                "tokens_used": tokens_used,
                "cost": cost,
                "stock_code": stock_code
            }
            
        except Exception as e:
            logger.error(f"分析股票 {stock_code} 失败: {e}", exc_info=True)
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
        enable_search: bool = True,
        max_workers: int = 2
    ) -> List[Dict[str, Any]]:
        """
        并发批量分析股票，返回结果列表，顺序与输入一致
        """
        results = [None] * len(stock_codes)
        total = len(stock_codes)
        if total == 0:
            return []
        if total == 1:
            return [self.analyze_stock(stock_codes[0], user_id, system_prompt, enable_search)]
        
        def analyze_one(idx, code):
            return idx, self.analyze_stock(code, user_id, system_prompt, enable_search)
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(analyze_one, i, code): i for i, code in enumerate(stock_codes)}
            for future in as_completed(futures):
                idx, result = future.result()
                results[idx] = result
        return results
    
    def reanalyze_stock(self, analysis_id: int, user_id: int) -> Dict[str, Any]:
        with db_manager.get_session() as session:
            analysis = session.query(StockAnalysis).filter_by(
                id=analysis_id,
                user_id=user_id
            ).first()
            if not analysis:
                return {"success": False, "error": "分析记录不存在"}
            stock_code = analysis.stock_code

        try:
            training_history = self.get_training_context()
            train_settings = self._get_train_settings()
            sys_prompt = train_settings.get("system_prompt", self._get_default_system_prompt())
            
            filtered_history = []
            for msg in training_history:
                if msg.get("role") == "system":
                    sys_prompt = msg.get("content", sys_prompt)
                else:
                    filtered_history.append(msg)

            prompt = self._build_analysis_prompt(stock_code, has_training_context=bool(training_history))

            messages = []
            messages.append({"role": "system", "content": sys_prompt})
            if filtered_history:
                messages.extend(filtered_history)
            messages.append({"role": "user", "content": prompt})

            result = self.client.chat(
                messages=messages,
                model=train_settings.get("model", "deepseek-v4-flash"),
                enable_search=train_settings.get("enable_search", True),
                trim_to=50000,
                max_tokens=train_settings.get("max_tokens", 100000),
                temperature=train_settings.get("temperature", 0.7)
            )

            analysis_data = self._parse_analysis_result(result["content"], stock_code)
            tokens_used = result["usage"]["total_tokens"]
            cost = tokens_used / 1000 * 0.01

            with db_manager.get_session() as session:
                analysis = session.query(StockAnalysis).filter_by(id=analysis_id).first()
                if analysis:
                    analysis.analysis_data = analysis_data
                    analysis.raw_report = result["content"]
                    analysis.tokens_used = tokens_used
                    analysis.cost = cost
                    analysis.analysis_date = datetime.utcnow()
                    user = session.query(User).filter_by(id=user_id).first()
                    if user:
                        user.total_tokens_used += tokens_used
                        user.balance -= cost
                    session.commit()

            return {
                "success": True,
                "analysis": analysis_data,
                "raw_report": result["content"],
                "tokens_used": tokens_used,
                "cost": cost
            }

        except Exception as e:
            logger.error(f"重新分析股票 {stock_code} 失败: {e}", exc_info=True)
            return {"success": False, "error": str(e), "stock_code": stock_code}
    
    def delete_analysis(self, analysis_id: int, user_id: int) -> bool:
        with db_manager.get_session() as session:
            analysis = session.query(StockAnalysis).filter_by(
                id=analysis_id,
                user_id=user_id
            ).first()
            if analysis:
                session.delete(analysis)
                session.commit()
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
        with db_manager.get_session() as session:
            query = session.query(StockAnalysis).filter_by(user_id=user_id)
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
        fields = self.get_analysis_template()
        fields_format = "\n".join([f"{f}：..." for f in fields])
        base_prompt = f"""请对股票 {stock_code} 进行分析

**重要：请务必严格遵循我们之前的对话中确立的分析框架、风格和判断逻辑（如果有训练上下文）。**  
**综合结论需基于上述所有分析得出，输出的最后必须包含以下字段顺序和名称，每个字段一行，冒号后跟具体内容：**

{fields_format}

股票代码：{stock_code}
分析日期：（当前日期）

请确保每个字段都有实际分析内容，不要缺失。
"""
        if has_training_context:
            base_prompt = "请严格遵循我们之前对话中确立的分析框架、风格和判断逻辑，对股票进行分析。\n\n" + base_prompt
        return base_prompt
    
    def _get_default_system_prompt(self) -> str:
        return """你是一位专业的股票分析师，拥有丰富的金融市场分析经验。
请基于可获得的信息，对股票进行客观、全面的分析。
分析要数据驱动，避免主观臆断。
对于不确定的信息，请明确说明。
"""
    
    def _parse_analysis_result(self, content: str, stock_code: str) -> Dict[str, Any]:
        """解析AI返回的分析结果，提取各字段的值，并清洗数值字段"""
        result = {}
        fields = self.get_analysis_template()
        
        for field in fields:
            if field == "分析日期":
                continue
            patterns = [
                rf'{field}[：:]\s*([^\n]+)',
                rf'{field}\s*[：:]\s*([^\n]+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    value = match.group(1).strip()
                    # 对数值字段进行清洗
                    if field in ["目标价格", "现价", "综合评分", "赔率"]:
                        value = self._clean_numeric_value(value)
                    result[field] = value
                    break
            if field not in result:
                result[field] = ""
        
        result["股票代码"] = stock_code
        result["分析日期"] = datetime.now().strftime("%Y-%m-%d")
        return result

    def _clean_numeric_value(self, value: str) -> str:
        """清洗数值字段，只保留数字和点"""
        if not value:
            return ""
        match = re.search(r'(\d+\.?\d*)', value)
        if match:
            return match.group(1)
        return value
    def update_stock_prices(self, stock_codes: List[str], on_progress: callable = None) -> Dict[str, float]:
        """
        批量更新股票的最新价格（使用简化提示词）
        返回: {股票代码: 最新价格}
        """
        results = {}
        total = len(stock_codes)
        
        for i, code in enumerate(stock_codes):
            if on_progress:
                on_progress(i + 1, total, code)
            
            try:
                # ✅ 使用经过测试验证的简化提示词（方法2）
                prompt = f"股票{code}的最新价格是多少？只返回数字，不要任何其他文字。"
                
                result = self.client.chat(
                    messages=[
                        {"role": "user", "content": prompt}
                    ],
                    enable_search=True,
                    max_tokens=1000,
                    temperature=0.1
                )
                
                content = result.get("content", "").strip()
                logger.info(f"股票 {code} API返回: '{content}'")
                
                # 解析价格
                import re
                match = re.search(r'(\d+\.?\d*)', content)
                if match:
                    price = float(match.group(1))
                    if price > 0:
                        results[code] = price
                        logger.info(f"✅ 股票 {code} 价格: {price}")
                    else:
                        results[code] = None
                        logger.warning(f"⚠️ 股票 {code} 价格无效: {price}")
                else:
                    results[code] = None
                    logger.warning(f"⚠️ 无法解析股票 {code} 的价格: '{content}'")
                    
            except Exception as e:
                logger.error(f"获取股票 {code} 价格失败: {e}")
                results[code] = None
        
        return results