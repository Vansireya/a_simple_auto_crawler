import os
import json
import re
import config
from bs4 import BeautifulSoup

class HtmlRunner:
    def __init__(self):
        self.raw_dir = config.RAW_DATA_DIR
        self.har_path = config.HAR_PATH

    def _extract_from_html(self, html_content, url):
        extracted_data = {}
        soup = BeautifulSoup(html_content, 'html.parser')

        # --- 策略 1: Next.js ---
        # 特征: <script id="__NEXT_DATA__" type="application/json">
        next_data = soup.find('script', {'id': '__NEXT_DATA__'})
        if next_data:
            try:
                data = json.loads(next_data.string)
                extracted_data['next_js'] = data
                print("    [+] 命中 Next.js 数据结构")
            except:
                pass

        # --- 策略 2: JSON-LD (最通用的 SEO 数据，包含商品信息) ---
        # 特征: <script type="application/ld+json">
        ld_scripts = soup.find_all('script', {'type': 'application/ld+json'})
        if ld_scripts:
            ld_list = []
            for s in ld_scripts:
                try:
                    # 有些 JSON-LD 包含换行符，需要清理
                    clean_text = s.string.strip()
                    data = json.loads(clean_text)
                    ld_list.append(data)
                except:
                    pass
            if ld_list:
                extracted_data['json_ld'] = ld_list
                print(f"    [+] 命中 JSON-LD 数据 ({len(ld_list)} 个块)")

        # --- 策略 3: Shopify / 通用 JS 变量 (Muji, 独立站) ---
        # 特征: var meta = {...}; 或 window.Shopify = {...};
        meta_match = re.search(r'var\s+meta\s*=\s*(\{.*?\});', html_content, re.DOTALL)
        if meta_match:
            try:
                # 尝试解析 JS 对象为 JSON
                json_str = meta_match.group(1)
                data = json.loads(json_str)
                extracted_data['shopify_meta'] = data
                print("    [+] 命中 Shopify Meta 数据")
            except:
                pass

        # 3.2 提取 Nuxt.js / Redux State
        nuxt_match = re.search(r'window\.__NUXT__\s*=\s*(\{.*?\});', html_content, re.DOTALL)
        if not nuxt_match:
            nuxt_match = re.search(r'window\.__PRELOADED_STATE__\s*=\s*(\{.*?\});', html_content, re.DOTALL)

        if nuxt_match:
            try:
                extracted_data['app_state'] = json.loads(nuxt_match.group(1))
                print("    [+] 命中 App State 数据")
            except:
                pass

        return extracted_data

    def run(self, entry=None):
        print("==================================================")
        print("[*] [HtmlRunner] 启动全能 HTML 数据挖掘")
        print("==================================================")

        # 1. 确定要扫描的目标
        targets = []

        if entry:
            print("[*] 针对单一目标进行深度挖掘...")
            targets.append(entry)
        else:
            print(f"[*] 扫描 HAR 文件: {self.har_path}")
            try:
                with open(self.har_path, 'r', encoding='utf-8', errors='ignore') as f:
                    har = json.load(f)
                    all_entries = har['log']['entries']
                    # 过滤出可能是页面的 HTML (大于 50KB)
                    for e in all_entries:
                        mime = e['response']['content'].get('mimeType', '').lower()
                        text_len = e['response']['content'].get('size', 0)
                        if 'html' in mime and text_len > 50000:  # 只看大于 50KB 的
                            targets.append(e)
            except Exception as e:
                print(f"[!] HAR 读取失败: {e}")
                return

        print(f"[*] 待分析 HTML 页面数: {len(targets)}")

        # 2. 准备输出目录
        if os.path.exists(self.raw_dir):
            for f in os.listdir(self.raw_dir):
                if f.endswith('.json'): os.remove(os.path.join(self.raw_dir, f))
        else:
            os.makedirs(self.raw_dir, exist_ok=True)

        # 3. 执行挖掘
        saved_count = 0
        for i, t in enumerate(targets):
            url = t['request']['url']
            content = t['response']['content'].get('text', '')

            if not content: continue

            print(f"[-] 分析页面 {i + 1}: {url[:60]}...")

            # 核心提取
            data = self._extract_from_html(content, url)

            if data:
                # 构造一个统一的 JSON 结构
                wrapper = {
                    "source_url": url,
                    "extraction_type": "html_mining",
                    "data": data  # 这里面包含了 next_js, json_ld, shopify 等 key
                }

                filename = f"page_{saved_count + 1}.json"
                save_path = os.path.join(self.raw_dir, filename)

                with open(save_path, 'w', encoding='utf-8') as f:
                    json.dump(wrapper, f, ensure_ascii=False, indent=2)

                print(f"    [√] 数据已提取并保存: {filename} ({len(json.dumps(wrapper))} bytes)")
                saved_count += 1
            else:
                print("    [x] 未发现结构化数据")

        print("-" * 50)
        print(f"[*] 挖掘结束，共生成 {saved_count} 个数据文件。")
        if saved_count > 0:
            return True
        return False


if __name__ == "__main__":
    runner = HtmlRunner()
    runner.run()