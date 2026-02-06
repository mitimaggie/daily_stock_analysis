import google.generativeai as genai

# 把下面的 API_KEY 替换成你截图里那个 ...QilM
genai.configure(api_key="AIzaSyDhQJzTxEQkYkUNrcJJsqkyCF2gD_4QilM")

print("--- 你当前可以使用的模型列表 ---")
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"模型 ID: {m.name}")
except Exception as e:
    print(f"获取失败，错误原因: {e}")