import os

# 定义需要读取的根目录文件
ROOT_FILES = ['main.py', 'webui.py', 'analyzer_service.py', 'pyproject.toml']

# 定义需要递归读取的文件夹
TARGET_DIRS = ['src', 'bot', 'data_provider', 'web']

# 定义需要忽略的文件或文件夹
IGNORE_DIRS = {'__pycache__', 'sources', 'logs', 'data', 'docs', 'tests', '.git', '.github', 'docker'}
IGNORE_EXTS = {'.pyc', '.png', '.jpg', '.gif', '.db', '.log', '.md'}

def read_file_content(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"

def pack_project():
    print("User: 这里是项目的核心代码内容：\n")
    
    # 1. 读取根目录的关键文件
    for filename in ROOT_FILES:
        if os.path.exists(filename):
            print(f"\n#File: {filename}")
            print("-" * 20)
            print(read_file_content(filename))
            print("-" * 20)

    # 2. 递归读取核心文件夹
    for target_dir in TARGET_DIRS:
        if not os.path.exists(target_dir):
            continue
            
        for root, dirs, files in os.walk(target_dir):
            # 过滤文件夹
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            
            for file in files:
                ext = os.path.splitext(file)[1]
                if ext in IGNORE_EXTS:
                    continue
                
                # 拼接路径
                file_path = os.path.join(root, file)
                # 转换为统一的 Linux 风格路径分隔符 (方便 AI 理解)
                display_path = file_path.replace('\\', '/')
                
                print(f"\n#File: {display_path}")
                print("-" * 20)
                print(read_file_content(file_path))
                print("-" * 20)

if __name__ == "__main__":
    pack_project()
