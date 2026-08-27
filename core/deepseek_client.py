"""
DeepSeek API客户端封装（使用 Responses API）
支持对话、联网搜索、上下文管理
"""
import os
import logging
from typing import List, Dict, Any, Optional
from openai import OpenAI
import tiktoken

logger = logging.getLogger(__name__)


class DeepSeekClient:
    """DeepSeek API客户端（基于 Responses API）"""
    
    # 使用官方支持的模型
    DEFAULT_MODEL = "deepseek-v4-flash"
    SUPPORTED_MODELS = [
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "deepseek-v4-flash-vision-exp"
    ]
    MAX_CONTEXT_TOKENS = 50000
    
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY is required")
        
        self.model = model or self.DEFAULT_MODEL
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://api.deepseek.com"
        )
        self.encoding = tiktoken.get_encoding("cl100k_base")
        self._conversation_history = []
        
    def count_tokens(self, text: str) -> int:
        return len(self.encoding.encode(text))
    
    def count_messages_tokens(self, messages: List[Dict]) -> int:
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += self.count_tokens(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        total += self.count_tokens(item["text"])
        return total
    
    def trim_context(self, messages: List[Dict], max_tokens: int = None) -> List[Dict]:
        max_tokens = max_tokens or self.MAX_CONTEXT_TOKENS
        current_tokens = self.count_messages_tokens(messages)
        
        if current_tokens <= max_tokens:
            return messages
        
        system_msg = None
        other_msgs = []
        for msg in messages:
            if msg.get("role") == "system":
                system_msg = msg
            else:
                other_msgs.append(msg)
        
        while other_msgs and self.count_messages_tokens(
            [system_msg] + other_msgs if system_msg else other_msgs
        ) > max_tokens:
            if len(other_msgs) > 1:
                other_msgs.pop(0)
            else:
                break
        
        result = []
        if system_msg:
            result.append(system_msg)
        result.extend(other_msgs)
        
        logger.info(f"上下文裁剪: {current_tokens} -> {self.count_messages_tokens(result)} tokens")
        return result
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: str = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        enable_search: bool = False,
        stream: bool = False,
        trim_to: int = None
    ) -> Dict[str, Any]:
        """
        发送聊天请求（使用 Responses API）
        
        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            model: 模型名称
            max_tokens: 最大输出token
            temperature: 温度参数
            enable_search: 是否启用联网搜索
            stream: 是否流式输出（暂未实现）
            trim_to: 裁剪上下文到的token数
        
        Returns:
            {
                "content": "回复内容",
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "model": "模型名称",
                "search_enabled": bool
            }
        """
        model = model or self.model
        # 确保模型名称是官方支持的
        if model not in self.SUPPORTED_MODELS:
            logger.warning(f"模型 {model} 不在支持列表中，将回退到默认模型 {self.DEFAULT_MODEL}")
            model = self.DEFAULT_MODEL
        
        # 裁剪上下文（如果指定）
        if trim_to:
            messages = self.trim_context(messages, trim_to)
        else:
            messages = self.trim_context(messages, self.MAX_CONTEXT_TOKENS)
        
        # 提取系统指令（如果有）
        instructions = None
        input_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                instructions = msg.get("content", "")
            else:
                input_messages.append(msg)
        
        # 如果没有显式的系统指令，但第一条消息是系统角色，已提取；否则 input_messages 包含所有非系统消息
        # 构建请求参数（Responses API 格式）
        params = {
            "model": model,
            "input": input_messages,      # 消息列表
            "max_output_tokens": max_tokens,
            "temperature": temperature,
        }
        
        if instructions:
            params["instructions"] = instructions
        
        # 启用搜索：通过 tools 参数
        if enable_search:
            params["tools"] = [{"type": "web_search"}]
            logger.info("🔍 启用智能搜索 (web_search)")
        
        # 流式输出暂不支持，但保留参数
        if stream:
            logger.warning("流式输出暂未实现，将忽略 stream 参数")
        
        try:
            # 调用 Responses API
            response = self.client.responses.create(**params)
            
            # 提取输出文本
            content = response.output_text if hasattr(response, 'output_text') else ""
            
            # 提取 usage（如果存在）
            usage = getattr(response, 'usage', None)
            if usage:
                prompt_tokens = getattr(usage, 'prompt_tokens', 0)
                completion_tokens = getattr(usage, 'completion_tokens', 0)
                total_tokens = getattr(usage, 'total_tokens', 0)
            else:
                # 如果无 usage 信息，估算
                total_tokens = self.count_tokens(content) + 1000
                prompt_tokens = 0
                completion_tokens = 0
            
            logger.info(f"✅ API调用成功, 模型: {response.model}")
            if enable_search:
                # 检查响应中是否包含搜索标记（某些版本可能没有）
                search_used = getattr(response, 'search_used', None)
                if search_used is not None:
                    logger.info(f"✅ 联网搜索已使用: {search_used}")
                else:
                    logger.info("✅ 搜索请求已发送 (响应中未返回搜索标记)")
            
            return {
                "content": content,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens
                },
                "model": response.model,
                "search_enabled": enable_search,
            }
        except Exception as e:
            logger.error(f"DeepSeek API调用失败: {e}")
            raise
    
    def chat_with_history(
        self,
        user_message: str,
        system_prompt: str = None,
        history: List[Dict] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        带历史上下文的对话
        
        Args:
            user_message: 用户消息
            system_prompt: 系统提示词
            history: 历史对话列表（如果不传，则使用 self._conversation_history）
            **kwargs: 其他参数传递给 chat
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        if history is not None:
            messages.extend(history)
        else:
            messages.extend(self._conversation_history)
        
        messages.append({"role": "user", "content": user_message})
        
        result = self.chat(messages, **kwargs)
        
        # 更新内部历史
        self._conversation_history.append({"role": "user", "content": user_message})
        self._conversation_history.append({"role": "assistant", "content": result["content"]})
        
        return result
    
    def clear_history(self):
        self._conversation_history = []
    
    def get_history(self) -> List[Dict]:
        return self._conversation_history.copy()
    
    def delete_history_item(self, index: int) -> bool:
        if index < 0 or index >= len(self._conversation_history):
            return False
        if index % 2 != 0:
            index -= 1
        del self._conversation_history[index:index+2]
        return True