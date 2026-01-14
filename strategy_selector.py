import json
import re
import config
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import os

class StrategySelector:
    def __init__(self):
        self.har_data = None
        self.main_domain = None

    def load_har(self):
        all_entries = []
        target_dir = os.path.dirname(config.HAR_PATH)
        try:
            if not os.path.exists(target_dir): return False
            har_files = [f for f in os.listdir(target_dir) if f.endswith('.har')]
            if not har_files: return False

            for filename in har_files:
                file_path = os.path.join(target_dir, filename)
                print(f"[*] Loading: {filename}")
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    try:
                        data = json.load(f)
                        all_entries.extend(data.get('log', {}).get('entries', []))
                    except:
                        pass

            self.har_data = {'log': {'entries': all_entries}}
            print(f"[*] Total entries loaded: {len(all_entries)}")
            return True
        except Exception as e:
            print(f"[!] Load Error: {e}")
            return False

    def _get_domain_info(self, url):
        try:
            parsed = urlparse(url)
            netloc = parsed.netloc.lower()
            parts = netloc.split('.')
            return ".".join(parts[-2:]) if len(parts) >= 2 else netloc, netloc
        except:
            return "", ""

    def _extract_html_info(self, entries):
        price_dna = set()
        main_entry = None
        max_len = 0

        for entry in entries:
            res = entry['response']
            mime = res.get('content', {}).get('mimeType', '').lower()
            text = res.get('content', {}).get('text', '')
            if 'html' in mime and len(text) > max_len:
                max_len = len(text)
                main_entry = entry

        if not main_entry: return set()

        self.main_domain, _ = self._get_domain_info(main_entry['request']['url'])
        print(f"[*] Target Domain: [{self.main_domain}]")

        try:
            soup = BeautifulSoup(main_entry['response']['content']['text'], 'html.parser')
            for tag in soup(['script', 'style', 'head']): tag.decompose()
            regex = re.compile(r'[\$€£¥]?\s?(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)')
            for node in soup.find_all(string=True):
                for m in regex.findall(node):
                    clean = re.sub(r'[^\d.,]', '', m).replace(',', '')
                    if len(clean) >= 3: price_dna.add(clean)
        except:
            pass
        return price_dna

    def _analyze_fingerprint(self, entries, price_dna):
        STATIC_EXT = ['.css', '.js', '.woff', '.png', '.jpg', '.gif', '.svg', '.ico', '.webp', '.jpeg']

        DOMAIN_BLACKLIST = [
            'images.lululemon.com', 'scene7.com', 'analytics', 'logging', 'sentry',
            'adtech', 'doubleclick', 'google-analytics'
        ]

        BLACK_KEYS = ['akam', 'demdex', 'pixel', 'telemetry', 'track', 'google', 'facebook']
        TRAP_KEYS = ['swatches', 'media', 'region', 'lang', 'header', 'footer', 'nav', 'menu', 'inventory',
                     'autocomplete', 'suggestion', 'filter', 'adtech', 'cdn','static']
        WHITE_KEYS = ['product', 'products', 'list', 'query', 'collection', 'items', 'search', 'catalog', 'category',
                      'results']

        candidates = []

        for entry in entries:
            url = entry['request']['url'].lower()
            res = entry['response']
            mime = res.get('content', {}).get('mimeType', '').lower()
            text = res.get('content', {}).get('text', '')
            size_kb = len(text) / 1024
            curr_main, curr_full = self._get_domain_info(url)

            # --- 0. 绝对过滤 ---
            if len(text) < 1000: continue
            if url.split('?')[0].endswith(tuple(STATIC_EXT)): continue

            # [Fix] 绝对过滤 HTML
            if 'html' in mime: continue
            if any(d in url for d in DOMAIN_BLACKLIST): continue
            if any(k in url for k in BLACK_KEYS): continue

            # --- 评分模型 (0.0 - 100.0) ---
            confidence = 0.0

            # 1. 基础类型 (+15%)
            if 'json' in mime: confidence += 15

            # 2. 域名校验 (+10%)
            if self.main_domain and curr_main == self.main_domain:
                confidence += 10
                if 'api' in curr_full or 'graphql' in url: confidence += 5

            # 3. URL 关键词特征
            if any(k in url for k in WHITE_KEYS): confidence += 30
            if any(k in url for k in TRAP_KEYS): confidence -= 40
            if any(p in url for p in ['page', 'limit', 'size', 'offset', 'cursor', 'p=']): confidence += 15

            # 修正: 分类接口若无 products 字眼，大概率是菜单树
            if 'categories' in url and 'products' not in url: confidence -= 25

            # 4. 体积权重
            size_bonus = min(size_kb / 10.0, 20.0)
            confidence += size_bonus

            # 5. 价格指纹
            if price_dna:
                hits = sum(1 for p in price_dna if p in text)
                if hits > 0: confidence += 25

            final_score = max(0.0, min(100.0, confidence))

            if final_score > 40:
                candidates.append({"entry": entry, "score": final_score, "url": url, "size": size_kb})

        if not candidates: return None
        candidates.sort(key=lambda x: x['score'], reverse=True)

        print("\n--- API 候选 Top 3 ---")
        for i, c in enumerate(candidates[:3]):
            print(f"[{i + 1}] Confidence: {c['score']:.1f}% | Size: {c['size']:.1f}KB | URL: {c['url'][:80]}...")

        # 只有高分才返回，否则返回 None 让上层逻辑去 fallback 到 SSR
        if candidates[0]['score'] >= 60:
            return candidates[0]
        return None

    def _analyze_ssr_html(self, entries):
        # 遍历所有 entry，寻找含有 SSR 数据的 HTML
        for e in entries:
            mime = e['response']['content'].get('mimeType', '').lower()
            if 'html' not in mime: continue

            txt = e['response']['content'].get('text', '')
            if len(txt) < 5000: continue

            # 特征匹配
            if '__NEXT_DATA__' in txt:
                return {"mode": "HTML_NEXTJS", "data": e}  # 返回 entry 对象

            # Shopify 特征
            if 'window.Shopify' in txt or 'var meta =' in txt and 'product' in txt:
                return {"mode": "HTML_SHOPIFY", "data": e}

            if 'gapGlobal' in txt or 'window.universal_variable' in txt:
                return {"mode": "HTML_GENERIC", "data": e}

        # 如果都没命中，尝试返回最大的那个 HTML 文件作为 Generic 兜底
        best_entry = None
        max_size = 0
        for e in entries:
            mime = e['response']['content'].get('mimeType', '').lower()
            txt = e['response']['content'].get('text', '')
            if 'html' in mime and len(txt) > max_size:
                max_size = len(txt)
                best_entry = e

        if best_entry:
            return {"mode": "HTML_GENERIC", "data": best_entry}

        return None

    def select(self):
        if not self.load_har(): return None
        entries = self.har_data.get('log', {}).get('entries', [])

        price_dna = self._extract_html_info(entries)

        # 1. 优先寻找纯净 API
        best_fp = self._analyze_fingerprint(entries, price_dna)

        # 阈值判断：只有分数够高才认为是 API
        if best_fp and best_fp['score'] >= 60:
            print(f"[*] 锁定最佳 API: {best_fp['url'][:80]}")
            return {"mode": "API", "data": best_fp['entry']}

        print("[!] 未找到高置信度 API，正在扫描 SSR/HTML 数据...")

        # 2. 降级 SSR / HTML 解析
        ssr_res = self._analyze_ssr_html(entries)
        if ssr_res:
            print(f"[*] 锁定 SSR 数据源: {ssr_res['mode']}")
            return ssr_res

        print("[X] 策略匹配失败")
        return None


if __name__ == "__main__":
    StrategySelector().select()