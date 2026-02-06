import os
from anytree import Node, RenderTree

def build_clean_tree(path, parent=None):
    # 【关键】在这里填入你不想看到的文件夹名字
    # 比如 .venv (库文件), .git (版本控制), __pycache__ (缓存)
    ignore = {'.git', '.venv', 'venv', '__pycache__', '.vscode', '.idea'}
    
    basename = os.path.basename(path)
    if basename in ignore or basename.startswith('.'):
        return None

    # 创建当前节点
    node = Node(basename, parent=parent)

    # 如果是文件夹，继续往下找
    if os.path.isdir(path):
        try:
            # 排序：让文件夹显示在文件前面，更有逻辑
            items = sorted(os.listdir(path))
            for item in items:
                item_path = os.path.join(path, item)
                build_clean_tree(item_path, parent=node)
        except PermissionError:
            pass
    return node

# 1. 自动定位当前文件夹
# 如果你只想打印当前目录，用 "."
# 如果想打印特定文件夹，把 "." 换成路径，比如 "D:/MyProject"
root = build_clean_tree(".")

# 2. 打印出你要的那种带连线的结构
if root:
    for pre, fill, node in RenderTree(root):
        print(f"{pre}{node.name}")