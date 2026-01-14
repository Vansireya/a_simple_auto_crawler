import json
import os
import config
from har_recorder import HarRecorder
from strategy_selector import StrategySelector
from api_runner import ApiRunner
from html_runner import HtmlRunner
from processor import DataProcessor


def main():
    print("=== AUTO CRAWLER AI EDITION STARTED ===")

    HarRecorder().run()

    selector = StrategySelector()
    if not selector.load_har(): return
    strategy = selector.select()

    if not strategy:
        print("[!] 无法确定抓取策略，程序终止")
        return

    success = False
    if strategy['mode'] == "API":
        success = ApiRunner().run(strategy['data'])
    elif "HTML" in strategy['mode']:
        success = HtmlRunner().run(entry=strategy['data'])

    if not success:
        print("[!] 采集阶段未获得有效数据，程序终止")
        return
    print(f"[*] [Main] 采集完成，准备启动 AI 处理...")


    DataProcessor().run()
    print("=== TASK COMPLETED ===")

if __name__ == "__main__":
    main()