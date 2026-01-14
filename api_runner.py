import os
import json
import re
import subprocess
import sys
import requests
import config
from openai import OpenAI
from strategy_selector import StrategySelector

class ApiRunner:
    def __init__(self):
        self.client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)

    def _get_context_and_sample(self, entry):
        req = entry['request']
        res = entry['response']
        headers = {h['name']: h['value'] for h in req['headers']
                   if not h['name'].startswith(':') and h['name'].lower() not in
                   ['content-length', 'host', 'connection', 'accept-encoding', 'content-type']}

        context = {
            "url": req['url'].split('?')[0],
            "headers": headers,
            "params": {p['name']: p['value'] for p in req['queryString']},
            "method": req['method']
        }

        text = res.get('content', {}).get('text', '')
        print(f"[*] [ApiRunner] 原始响应大小: {len(text) / 1024:.2f} KB")

        def prune_structure(data, depth=0):
            if depth > 15: return "..."

            if isinstance(data, dict):
                return {k: prune_structure(v, depth + 1) for k, v in data.items()}

            elif isinstance(data, list):
                if not data: return []
                return [prune_structure(data[0], depth + 1)]

            else:
                return data

        try:
            full_json = json.loads(text)
            skeleton_json = prune_structure(full_json)
            sample_fragment = json.dumps(skeleton_json, ensure_ascii=False)

            if len(sample_fragment) > 8000:
                print(f"[*] [ApiRunner] 样本仍过大 ({len(sample_fragment)} chars)，进行末尾截断...")
                sample_fragment = sample_fragment[:8000]
            else:
                print(f"[*] [ApiRunner] 结构瘦身成功，样本大小: {len(sample_fragment)} chars")

        except json.JSONDecodeError:
            print("[!] 响应非标准 JSON，回退至原始截断")
            sample_fragment = text[:4000]
        except Exception as e:
            print(f"[!] 样本处理异常: {e}，回退至原始截断")
            sample_fragment = text[:4000]

        return context, sample_fragment

    def _generate_pagination_script(self, context, sample):
        prompt = f"""
                编写一个 Python 爬虫脚本 `generated_scraper.py`。

                【目标】
                1. 使用 `requests.Session()` 和 Headers: {json.dumps(context['headers'])}
                2. 初始 URL: {context['url']}
                3. 初始参数: {json.dumps(context['params'])}
                4. 参考样本结构: {sample}

                【通用翻页算法逻辑 】
                - 识别步长: 检查参数中的 `limit`, `count`, `pageSize`。如果没有，默认设为 20。
                - 识别偏移: 检查参数中的 `offset`, `start`, `anchor`, `page`。
                - 循环控制: 
                    - 每一轮请求后，解析 JSON。
                    - 不要只判断根节点。递归搜索 JSON 树，找到包含最多 Dict 的 List（这通常是商品列表）。
                    - 停止条件: 只有当该 List 长度为 0，或者连续两页的 List 内容完全一致时才停止。最大页数 30 页。
                    - 步长递增: 如果参数是 offset，则 `offset += pageSize`；如果是 page，则 `page += 1`。

                【输出要求】
                - 必须打印每页抓取状态: `print(f"Page {{n}} fetched: {{len(items)}} items found.")`
                - 确保文件存至: `{config.RAW_DATA_DIR.replace('\\', '/')}/page_n.json`
                - 只输出 Python 代码，包裹在 ```python ``` 中。
                """

        try:
            response = self.client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1
            )
            code = re.search(r'```python\s*(.*?)\s*```', response.choices[0].message.content, re.DOTALL)
            return code.group(1) if code else None
        except:
            return None

    def run(self, entry=None):
        print("==================================================")
        print("[*] [ApiRunner] 启动采集流程")

        if not entry:
            selector = StrategySelector()
            if selector.load_har():
                res = selector.select()
                entry = res['data'] if res and res['mode'] == 'API' else None

        if not entry: return print("[!] 未锁定目标 API")
        context, sample = self._get_context_and_sample(entry)

        if os.path.exists(config.RAW_DATA_DIR):
            for f in os.listdir(config.RAW_DATA_DIR):
                if f.endswith('.json'): os.remove(os.path.join(config.RAW_DATA_DIR, f))

        script_content = self._generate_pagination_script(context, sample)
        if script_content:
            with open(config.GENERATED_SCRAPER_PATH, 'w', encoding='utf-8') as f:
                f.write(script_content)

            try:
                print("[*] [System] 正在执行翻页脚本，请稍后...")
                subprocess.run([sys.executable, config.GENERATED_SCRAPER_PATH], check=True)

                files = [f for f in os.listdir(config.RAW_DATA_DIR) if f.endswith('.json')]
                if files:
                    print(f"[√] 采集完成，共获取 {len(files)} 个分页文件。")
                    return True
            except Exception as e:
                print(f"[!] 脚本执行崩溃: {e}")

        print("[!] 切换至单页兜底模式...")
        return self._execute_fast_request(context)

    def _execute_fast_request(self, context):
        os.makedirs(config.RAW_DATA_DIR, exist_ok=True)
        try:
            resp = requests.request(method=context['method'], url=context['url'],
                                    headers=context['headers'], params=context['params'], timeout=15)
            if resp.status_code == 200:
                with open(os.path.join(config.RAW_DATA_DIR, "fallback_page.json"), 'w', encoding='utf-8') as f:
                    json.dump(resp.json(), f, ensure_ascii=False)
                return True
        except:
            return False

if __name__ == "__main__":
    ApiRunner().run()