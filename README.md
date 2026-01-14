# 工作流程

1. **录制阶段**：`har_recorder.py` 生成网站交互记录或手动获取 har 文件
2. **分析阶段**：`strategy_selector.py` 判断数据获取方式
3. **采集阶段**：
   - API 模式 → `api_runner.py` 生成并执行翻页脚本
   - HTML 模式 → `html_runner.py` 挖掘页面数据
4. **处理阶段**：`processor.py` 调用 LLM 解析数据并导出为 excel 文件

# 核心模块功能

## config.py：管理项目路径、LLM 配置和全局参数
- **基础路径**：检测运行环境（Airflow 容器或本地），确定 data 文件夹位置
- **项目文件夹**：提取域名（如 nike）在 data 下创建 nike 文件夹
- **生成的具体文件路径（示例）**：
  - `data/nike/site.har` — 录制的网络请求文件
  - `data/nike/raw/` — 存储原始 JSON 数据的文件夹
  - `data/nike/generated_scraper.py` — 动态生成的爬虫脚本
  - `data/nike/nike_result.xlsx` — 最终输出的 Excel 结果

## main.py：协调整个爬虫流程的执行顺序

### har_recorder.py：使用 Playwright 录制网站浏览过程，生成 HAR 文件
使用 Playwright 启动浏览器，访问目标网站并模拟用户滚动操作，同时移除弹窗等干扰元素，录制完整的网络请求到 HAR 文件。

### strategy_selector.py：分析 HAR 文件，确定最佳抓取策略
1. 加载并合并所有 HAR 文件
2. 从主 HTML 中提取价格特征作为数据指纹
3. 分析所有请求，根据以下特征评分：
   - MIME 类型（JSON 高分，HTML 过滤）
   - 域名匹配度（寻找主域名，域名含 api 加分）
   - URL 关键词（没有黑名单/白名单/陷阱名单）
   - 响应体积
   - 价格指纹匹配
4. 返回最佳策略：得分超过 60% 设定为 API 模式，剩下为 SSR/HTML 模式

### api_runner.py：处理通过 API 接口获取数据的网站
1. 从选中的 API 请求中提取上下文（URL、headers、参数）
2. 对响应 JSON 进行结构瘦身，生成样本，防止给大模型一次喂太大文件
3. 调用 LLM 生成翻页爬虫脚本
4. 执行生成的脚本，保存分页数据
5. 失败时降级为单页请求

### html_runner.py：从 SSR 页面中提取结构化数据
扫描大型 HTML 文件，使用多种策略（Next.js 数据、JSON-LD、Shopify 变量等）提取嵌入的结构化数据，转化为统一格式保存。

## processor.py：解析原始数据，清洗并导出 Excel
1. 分析 JSON 结构，寻找商品列表路径，便于大模型理解
2. 调用 LLM 生成数据解析器代码

   ```python
   prompt = """
   任务：编写 Python 函数 'parse_json(data)'。
   【数据结构】：
   {vitals}
   【数据样本】：
   {json.dumps(mini_sample_indent=2, ensure_ascii=False)}
   【核心指令】：
   1. 寻找核心：对比路径信息，定位那个在所有样本中都存在的、包含商品实体的 List 节点。使用 .get() 逐层安全访问。
   2. 扁平化处理（Flattening）：
      - 若商品节点包含 `'variants'`、`'skus'`、`'items'` 等子列表，必须遍历该子列表。
      - 返回的列表中，每一个元素应当是一个具体的 SKU（特定颜色/尺码）。
      - 父级字段（如商品名）应复制给每个子 SKU。
   3. 字段映射（Mapping）：
      - 必须提取（若存在）ID/SKU、名称、价格（current/original）、图片 URL、规格（color/size）、库存。
      - 商品类别：提取折扣率、品牌、评分、销量、标签等字段。
      - 排序优先级：不要提取 UI 配置、HEX 颜色、开关等。
   4. 数值安全（Type Safety）：
      - 提取价格、库存、销量等数值时，必须处理 None 值。
      - 严禁直接对可能为 None 的字段进行数学比较（如 <> 0），防止 TypeError。
   5. 属性校验：使用 .get()，忽略空值，字段名用下划线风格。
   6. 只输出 Python 代码，包裹在 `"""` 中。
   """
