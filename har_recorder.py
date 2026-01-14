import time
import os
import random
import config
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


class HarRecorder:
    def __init__(self, target_url=None):
        self.target_url = target_url if target_url else config.TARGET_URL

    def _add_stealth_scripts(self, context):
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

    def _close_popups(self, page):
        print("    -> [清理] 正在暴力移除屏蔽层...")
        try:
            page.evaluate("""
                () => {
                    const selectors = [
                        '#onetrust-consent-sdk', 
                        '.onetrust-pc-dark-filter',
                        '#onetrust-banner-sdk',
                        '[id^="onetrust"]',
                        '.modal-backdrop',
                        '.v-modal'
                    ];

                    selectors.forEach(s => {
                        document.querySelectorAll(s).forEach(el => el.remove());
                    });

                    // 2. 强制恢复身体滚动条
                    document.body.style.setProperty('overflow', 'auto', 'important');
                    document.documentElement.style.setProperty('overflow', 'auto', 'important');
                }
            """)
            # 物理 Escape 键
            page.keyboard.press("Escape")
        except Exception as e:
            print(f"    [!] 清理异常: {e}")
    def _get_scroll_height(self, page):
        return page.evaluate("""
            () => {
                return document.body ? 
                       Math.max(document.body.scrollHeight, document.documentElement.scrollHeight) : 
                       document.documentElement.scrollHeight;
            }
        """)

    def _smart_scroll(self, page):
        print(f"[*] [Recorder] 启动物理模拟滚动...")

        for i in range(config.SCROLL_COUNT):
            print(f"    -> 🔄 滚动进度: {i + 1}/{config.SCROLL_COUNT}")
            try:
                page.mouse.wheel(0, 1200)

                time.sleep(random.uniform(2.5, 3.5))

                if i % 3 == 0:
                    page.mouse.click(10, 10)
            except Exception as e:
                print(f"    [!] 滚动异常: {e}")

    def run(self):
        os.makedirs(os.path.dirname(config.HAR_PATH), exist_ok=True)
        if os.path.exists(config.HAR_PATH):
            try:
                os.remove(config.HAR_PATH)
            except:
                pass

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=["--start-maximized", "--disable-blink-features=AutomationControlled",
                      "--ignore-certificate-errors"]
            )

            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                record_har_path=config.HAR_PATH,
                record_har_content="embed",
                ignore_https_errors=True,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )

            self._add_stealth_scripts(context)
            page = context.new_page()
            page.set_default_timeout(60000)

            try:
                print(f"[*] [Recorder] 正在访问: {self.target_url}")
                # 1. 访问页面
                try:
                    page.goto(self.target_url, wait_until="commit", timeout=45000)
                except Exception as e:
                    print(f"    [!] 页面响应过慢 (Commit阶段): {e}")

                # 2. 关键修改：不要因为 domcontentloaded 超时就崩溃
                try:
                    print("    -> 等待 DOM 解析...")
                    page.wait_for_load_state("domcontentloaded", timeout=20000)
                except:
                    print("    [!] DOM 解析超时，但不中断，尝试继续后续操作...")

                time.sleep(5)
                self._close_popups(page)
                self._smart_scroll(page)

                print(f"[*] [Recorder] 等待 5s 写入磁盘...")
                page.wait_for_timeout(5000)

            except Exception as e:
                print(f"[!] 运行异常: {e}")
            finally:
                context.close()
                browser.close()

                if os.path.exists(config.HAR_PATH):
                    size = os.path.getsize(config.HAR_PATH) / (1024 * 1024)
                    print(f"[√] HAR 已保存: {config.HAR_PATH} ({size:.2f} MB)")
                else:
                    print("[X] HAR 生成失败")


if __name__ == "__main__":
    HarRecorder().run()