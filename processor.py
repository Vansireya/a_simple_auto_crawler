import json
import re
import os
import pandas as pd
import config
from openai import OpenAI


class DataProcessor:
    def __init__(self):
        self.client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL, timeout=180.0)

    def _analyze_json_vitals(self, data):
        report = []

        def walk(obj, path="root", depth=0):
            if depth > 7: return
            if isinstance(obj, list) and len(obj) > 0:
                report.append(f"PATH: {path} | TYPE: List | LEN: {len(obj)}")
                if isinstance(obj[0], dict):
                    keys_sample = list(obj[0].keys())[:15]
                    report.append(f"  -> KEYS: {keys_sample}")
                walk(obj[0], f"{path}[0]", depth + 1)
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(v, (dict, list)): walk(v, f"{path}.{k}", depth + 1)

        walk(data)
        return "\n".join(report)

    def _get_value_by_path(self, data, path):
        parts = path.replace('root.', '').split('.')
        curr = data
        try:
            for p in parts:
                if '[' in p:
                    name, idx = p.split('[')
                    curr = curr.get(name) if isinstance(curr, dict) else curr
                    if curr and isinstance(curr, list) and len(curr) > int(idx.replace(']', '')):
                        curr = curr[int(idx.replace(']', ''))]
                    else:
                        return None
                else:
                    curr = curr.get(p) if isinstance(curr, dict) else None
            return curr
        except:
            return None

    def _generate_parser_code(self, vitals, full_data):
        paths = re.findall(r'PATH: (root\S+)', vitals)
        best_path = "root"
        max_score = -1

        for p in paths:
            val = self._get_value_by_path(full_data, p)
            if isinstance(val, list) and len(val) > 0:
                try:
                    score = len(val)
                    sample_str = str(val[0]).lower()
                    business_keywords = ['price', 'article', 'sku', 'product', 'name', 'color', 'brand', 'item']
                    if any(k in sample_str for k in business_keywords):
                        score += 1000
                    if len(val) < 5:
                        score -= 500
                    if score > max_score:
                        max_score = score
                        best_path = p
                except:
                    continue

        target_list = self._get_value_by_path(full_data, best_path)
        mini_sample = {
            "target_path": best_path,
            "sample_structure": target_list[:1] if isinstance(target_list, list) else "Not Found"
        }

        print(f"[*] 锁定核心路径 [{best_path}] (Score: {max_score})")

        prompt = f"""
        任务：编写 Python 函数 `parse_json(data)`。
        【结构路径综合报告】：
        {vitals}
        【数据样本】：
        {json.dumps(mini_sample, indent=2, ensure_ascii=False)}

        【核心指令】：
        1. 寻找核心：对比路径报告，定位那个在所有样本中都存在的、包含商品实体的 List 节点。使用 .get() 逐层安全访问。
        2. 扁平化处理 (Flattening)：
           - 若商品节点下包含 `variants`, `skus`, `items` 等子列表，必须遍历该子列表。
           - 返回的列表中，每一个元素应当是一个具体的 SKU (特定颜色/尺码)。
           - 父级字段(如商品名)应复制给每个子 SKU。
        3. 字段映射 (Mapping)：
           - 必须提取(若存在) ID/SKU、名称、价格(current/original)、图片URL、规格(color/size)、库存。
           - 商业发现：提取折扣率、品牌、评分、销量、标签等字段。
           - 排除干扰：不要提取 UI 配置、HEX 颜色码、开关等。
        4. 数值安全 (Type Safety):
           - 提取价格、库存、销量等数值时，必须处理 None 值。
           - 严禁直接对可能是 None 的字段进行数学比较（如 `> 0`），防止 TypeError。
        5. 鲁棒性：使用 .get()，忽略空值，字段名用下划线风格。
        6. 只输出 Python 代码，包裹在 ```python ``` 中。
        """

        response = self.client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        code = re.search(r'```python\s*(.*?)\s*```', response.choices[0].message.content, re.DOTALL)
        return code.group(1) if code else response.choices[0].message.content

    def run(self):
        print("==================================================")
        print("[*] [Processor] 启动权重分析与清洗...")

        if not os.path.exists(config.RAW_DATA_DIR):
            print(f"[!] 目录不存在: {config.RAW_DATA_DIR}")
            return

        all_pages = []
        files = [f for f in sorted(os.listdir(config.RAW_DATA_DIR)) if f.endswith('.json')]

        if not files:
            print(f"[!] 目录 {config.RAW_DATA_DIR} 中没有找到 JSON 文件")
            return

        print(f"[*] 发现 {len(files)} 个数据文件，开始加载...")
        for f_name in files:
            try:
                with open(os.path.join(config.RAW_DATA_DIR, f_name), 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if data: all_pages.append(data)
            except Exception as e:
                print(f"[!] 文件 {f_name} 加载失败: {e}")

        if not all_pages: return

        # 选取最大的文件作为样本，增加命中率
        main_page = max(all_pages, key=lambda x: len(json.dumps(x)))
        vitals = self._analyze_json_vitals(main_page)

        print("--------------------------------------------------")
        # 截断过长的 vitals 显示，避免刷屏
        print(vitals[:1000] + "..." if len(vitals) > 1000 else vitals)
        print("--------------------------------------------------")

        parser_code = self._generate_parser_code(vitals, main_page)
        exec_scope = {"json": json, "re": re}

        try:
            exec(parser_code, exec_scope)
            if 'parse_json' not in exec_scope:
                raise ValueError("生成的代码中未找到 parse_json 函数")

            parse_func = exec_scope['parse_json']
            final_data = []

            for i, page in enumerate(all_pages):
                try:
                    items = parse_func(page)
                    if items and isinstance(items, list):
                        # 过滤掉非字典项和空项
                        valid_items = [it for it in items if isinstance(it, dict) and len(it) > 2]
                        final_data.extend(valid_items)
                        print(f"    -> 提取进度: {i + 1}/{len(all_pages)} | 获得实体: {len(valid_items)}")
                except Exception as e:
                    print(f"    -> [Warn] 页面 {i + 1} 解析微小错误: {e}")

            if final_data:
                df = pd.DataFrame(final_data)
                df.dropna(axis=1, how='all', inplace=True)

                # 将复杂对象转字符串，防止去重报错
                for col in df.columns:
                    if df[col].apply(lambda x: isinstance(x, (list, dict))).any():
                        df[col] = df[col].astype(str)

                before_len = len(df)
                df.drop_duplicates(inplace=True)
                print(f"    [!] 去重操作: {before_len} -> {len(df)}")

                df.to_excel(config.RESULT_EXCEL, index=False)
                print(f"[√] 清洗完成: 最终导出 {len(df)} 条记录至 Excel")
            else:
                print("[!] 未能提取到任何有效数据。")

        except Exception as e:
            print(f"[!] 执行出错: {e}")
            print(f"--- 生成代码预览 ---\n{parser_code}\n-------------------")


if __name__ == "__main__":
    DataProcessor().run()