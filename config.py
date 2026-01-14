import os
import sys
from urllib.parse import urlparse

# ==================== 业务配置 ====================
TARGET_URL = "https://shop.lululemon.com/c/women-we-made-too-much/n16o10z8mhd?icid=lp-story:women; "

SCROLL_COUNT = 10
WAIT_TIME = 10
HEADLESS = True

# ==================== 动态路径生成逻辑 ====================
def get_project_name(url):
    try:
        parsed = urlparse(url)
        domain = parsed.netloc
        if domain.startswith("www."):
            domain = domain[4:]
        if domain.startswith("shop."):
            domain = domain[5:]

        project_name = domain.split('.')[0]
        return project_name if project_name else "default_task"
    except:
        return "default_task"

# 1. 获取项目名
PROJECT_NAME = get_project_name(TARGET_URL)

# 2. 确定 Base Data 目录
if os.path.exists("/opt/airflow"):
    BASE_ROOT_DIR = "/opt/airflow/data"
    print("[Config] 运行环境: Airflow 容器")
else:
    # 定位到 data 文件夹
    BASE_ROOT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
    BASE_ROOT_DIR = os.path.abspath(BASE_ROOT_DIR)
    print(f"[Config] 运行环境: 本地 Windows")

# 3. 拼接具体项目路径 (data/gap/)
BASE_DATA_DIR = os.path.join(BASE_ROOT_DIR, PROJECT_NAME)

print(f"[Config] 当前任务工作目录: {BASE_DATA_DIR}")

# 4. 定义具体文件路径 (全部基于 BASE_DATA_DIR)
HAR_PATH = os.path.join(BASE_DATA_DIR, "site.har")
RAW_DATA_DIR = os.path.join(BASE_DATA_DIR, "raw")
RAW_JSON_PATH = os.path.join(BASE_DATA_DIR, "raw_data.json")
RESULT_EXCEL = os.path.join(BASE_DATA_DIR, f"{PROJECT_NAME}_result.xlsx")
GENERATED_SCRAPER_PATH = os.path.join(BASE_DATA_DIR, "generated_scraper.py")


# ==================== LLM 配置 ====================
def get_llm_config():
    config = {
        'LLM_API_KEY': '',
        'LLM_BASE_URL': 'https://api.deepseek.com',
        'LLM_MODEL': 'deepseek-reasoner'
    }

    try:
        from airflow.models import Variable
        config['LLM_API_KEY'] = Variable.get("LLM_API_KEY", default_var="")
        config['LLM_BASE_URL'] = Variable.get("LLM_BASE_URL", default_var=config['LLM_BASE_URL'])
        config['LLM_MODEL'] = Variable.get("LLM_MODEL", default_var=config['LLM_MODEL'])
        print("[Config] 配置来源: Airflow Variables")
    except (ImportError, Exception):

        config['LLM_API_KEY'] = os.environ.get("LLM_API_KEY", "")
        config['LLM_BASE_URL'] = os.environ.get("LLM_BASE_URL", config['LLM_BASE_URL'])
        config['LLM_MODEL'] = os.environ.get("LLM_MODEL", config['LLM_MODEL'])

        if os.environ.get("LLM_API_KEY"):
            print("[Config] 配置来源: 环境变量")
        else:
            local_config_path = os.path.join(os.path.dirname(__file__), "local_config.json")
            if os.path.exists(local_config_path):
                try:
                    import json
                    with open(local_config_path, 'r') as f:
                        local_config = json.load(f)
                    config.update(local_config)
                    print("[Config] 配置来源: local_config.json")
                except:
                    pass
            else:
                print("[Config] 使用默认配置")

    return config


LLM_CONFIG = get_llm_config()
LLM_API_KEY = LLM_CONFIG['LLM_API_KEY']
LLM_BASE_URL = LLM_CONFIG['LLM_BASE_URL']
LLM_MODEL = LLM_CONFIG['LLM_MODEL']


# ==================== 工具函数 ====================
def ensure_dirs():
    os.makedirs(BASE_DATA_DIR, exist_ok=True)
    os.makedirs(RAW_DATA_DIR, exist_ok=True)
    print(f"[Config] 已创建任务目录: {BASE_DATA_DIR}")

if __name__ == "__main__":
    ensure_dirs()
    print(f"Target Project: {PROJECT_NAME}")
    print(f"HAR Save Path: {HAR_PATH}")