from openai import OpenAI

# 初始化客户端，base_url 保持不变
client = OpenAI(
    api_key="sk-8ef2599247544901beb75eb3bb4e0769",
    base_url="https://api.deepseek.com"
)

# 使用 responses.create，并在 tools 中声明 web_search
response = client.responses.create(
    model="deepseek-v4-flash",
    instructions="你是一位专业的股票分析师。",
    input="今天焦点科技(002315)的股价是多少？",
    tools=[{"type": "web_search"}]  # <-- 关键：启用联网搜索
)

# 打印回答
print(response.output_text)

# 打印 token 使用量
print(response.usage)