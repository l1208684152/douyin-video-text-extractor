# 抖音视频博主数据采集工具
# 版本：1.0.0
# 日期：2026-04-18
# 作者：沉默机器/芒临团队

# 导入必要的库
import wmi
import hashlib
import requests
import json
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright, Page, BrowserContext, Mouse
import pandas as pd
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import random
import re
from typing import Optional, List, Dict, Any
import queue
import tempfile
import shutil
from openpyxl import Workbook, load_workbook
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.drawing.image import Image
import urllib.parse
from io import BytesIO
from tkinter import scrolledtext

# ==============================================================================
# 免责声明文本
# ==============================================================================
DISCLAIMER_TEXT = """
免责声明 (EULA - End User License Agreement)

【版权声明】
1. 版权所有 (C) 2026 [沉默机器/芒临团队]（以下简称“著作权人”），联系方式：l1208684152@163.com
2. 本软件（含代码、UI设计、功能逻辑、文档等全部内容）受《中华人民共和国著作权法》及相关国际条约保护，著作权人享有完整的著作权。
3. 使用许可：
   a.仅授权用户个人非商业使用本软件，禁止任何形式的商业盈利活动（包括但不限于倒卖软件、利用软件采集的数据进行商业售卖等）；
   b.未经著作权人书面许可，禁止复制、修改、拆解、分发、传播本软件的全部或部分内容，禁止移除或篡改软件中的版权标识、免责声明、授权系统等核心模块；
   c.禁止反向工程、反编译、破解本软件的授权机制或功能限制。
4. 侵权责任：违反上述版权条款的，著作权人将依法追究其法律责任，包括但不限于要求停止侵权、赔偿损失、承担诉讼费用等。

【工具性质与使用规范】
1. 工具定位：本软件是“抖音平台浏览辅助工具”，仅用于帮助用户更高效地查询和整理公开可见的视频信息，**不提供自动化采集、批量抓取等功能**，所有操作需用户手动完成。
2. 平台规则遵守：用户必须严格遵守抖音平台《用户协议》《robots协议》及相关规定，**禁止使用本工具进行任何违反平台规则的行为**，包括但不限于高频访问、绕过反爬机制等。
3. 数据使用限制：用户通过本工具获取的平台数据，仅可用于个人学习、研究目的，**禁止用于商业竞争、广告营销等任何商业用途**。

【免责条款】
1. 软件用途：本工具仅作为技术辅助手段，旨在帮助用户更高效地在抖音平台上查询和整理公开可见的视频信息。
2. 用户责任：用户承诺并保证，在使用本软件时，将严格遵守《抖音网站用户协议》、《中华人民共和国网络安全法》、《中华人民共和国反不正当竞争法》等相关法律法规及平台规则。
3. 禁止行为：用户不得利用本软件从事任何非法、侵权或违反平台规则的行为，包括但不限于：
    a.对抖音平台服务器进行高频、批量、自动化的恶意爬取或数据抓取；
    b.采集、存储、使用、传播任何受知识产权保护的内容（如视频图片、详细描述、品牌Logo等）用于商业用途或非法目的；
    c.利用采集的数据进行恶意竞争、虚假宣传、敲诈勒索等活动；
    d.绕过或试图绕过平台的访问限制或安全措施。
4. 风险承担：如用户违反上述条款，导致任何第三方（包括但不限于抖音平台、博主、其他用户）提出索赔、投诉或进行法律诉讼，或导致用户自身的抖音账号被封禁、IP被限制等处罚，由此产生的一切法律责任、经济损失和后果，均由用户自行承担。
5. 开发者免责：本软件的开发者不对用户的任何违规使用行为承担任何连带责任。开发者仅对软件本身的功能性缺陷负责修复，但不对用户因使用软件而导致的任何间接损失负责。
6. 协议生效与终止：用户点击“我已阅读并同意”按钮，即表示已充分阅读、理解并接受本声明的全部内容。若用户违反本协议，开发者有权随时终止软件使用许可，无需承担任何责任。
7. 无担保声明：本软件按现状提供，开发者不提供任何明示或默示的担保，包括但不限于适销性、特定用途适用性的担保。
"""

# ==============================================================================
# 授权系统核心配置
# ==============================================================================
SECRET_KEY = "S123789"

VALIDITY_MAP = {
    "00": 999999999,  # 永久激活
    "01": 2592000,  # 月激活 (30天)
    "02": 7776000,  # 季度激活 (90天)
    "03": 31536000  # 年度激活 (365天)
}

# ==============================================================================
# 反爬措施类
# ==============================================================================
class AntiCrawler:
    """反爬措施类，负责模拟人工行为"""
    
    def __init__(self):
        self.min_delay = 1.5
        self.max_delay = 3.0
        self.scroll_delay = 0.8
        self.scroll_step = 1200
        self.scroll_retry = 3
        self.scroll_wait_after = 2.5
    
    def random_delay(self, action: str) -> None:
        """随机延迟，模拟人工操作间隔"""
        delay = random.uniform(self.min_delay, self.max_delay)
        print(f"[反爬] {action}后延迟 {delay:.2f} 秒")
        time.sleep(delay)
    
    def simulate_mouse_move(self, page: Page, elem_selector: str) -> bool:
        """模拟鼠标移动到目标元素"""
        try:
            elem = page.query_selector(elem_selector)
            if not elem:
                return False
            start_x = random.randint(50, 150)
            start_y = random.randint(50, 150)
            target_x = elem.bounding_box()["x"] + elem.bounding_box()["width"] / 2 + random.randint(-10, 10)
            target_y = elem.bounding_box()["y"] + elem.bounding_box()["height"] / 2 + random.randint(-5, 5)
            
            # 模拟鼠标移动路径
            page.mouse.move(start_x, start_y)
            time.sleep(random.uniform(0.3, 0.6))
            page.mouse.move((start_x + target_x) / 2, (start_y + target_y) / 2)
            time.sleep(random.uniform(0.2, 0.4))
            page.mouse.move(target_x, target_y)
            print(f"[反爬] 模拟鼠标移动到目标元素")
            return True
        except Exception as e:
            print(f"[反爬] 鼠标模拟失败：{str(e)}")
            return False
    
    def scroll_to_load(self, page: Page) -> bool:
        """滚动页面以加载更多内容"""
        try:
            print("[滚动加载] 开始滚动（确保所有视频动态加载）...")
            time.sleep(3)
            
            # 记录初始视频数量
            initial_videos = len(page.query_selector_all("li.wqW3g_Kl.WPzYSlFQ.OguQAD1e"))
            print(f"[滚动加载] 初始视频数量：{initial_videos}")
            
            # 尝试使用不同的滚动方法，避免页面弹回顶部
            new_videos_found = 0
            
            # 方法1：使用JavaScript滚动，可能更可靠
            print("[滚动加载] 使用JavaScript滚动方法...")
            
            for i in range(8):  # 尝试8次滚动
                print(f"[滚动加载] 第{i+1}次滚动...")
                
                # 使用JavaScript平滑滚动到指定位置
                scroll_position = (i + 1) * 1500  # 每次滚动1500像素
                page.evaluate(f"window.scrollTo({{top: {scroll_position}, behavior: 'smooth'}})")
                
                # 等待滚动完成
                time.sleep(random.uniform(2, 3))
                
                # 检查是否有新视频加载
                current_videos = len(page.query_selector_all("li.wqW3g_Kl.WPzYSlFQ.OguQAD1e"))
                print(f"[滚动加载] 当前视频数量：{current_videos}，新增：{current_videos - initial_videos}")
                
                if current_videos > initial_videos:
                    new_videos_found = current_videos - initial_videos
                    initial_videos = current_videos
                    # 继续滚动，尝试加载更多
                    time.sleep(2)
                
            # 方法2：滚动到页面底部
            print("[滚动加载] 滚动到页面底部...")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(5)  # 给足够的时间加载
            
            # 最终检查视频数量
            final_videos = len(page.query_selector_all("li.wqW3g_Kl.WPzYSlFQ.OguQAD1e"))
            print(f"[滚动加载] 滚动完成（最终视频数量：{final_videos}，新增：{final_videos - (initial_videos - new_videos_found)}")
            
            # 如果还是没有新视频，尝试方法3：模拟鼠标拖动
            if final_videos == initial_videos - new_videos_found:
                print("[滚动加载] 尝试模拟鼠标拖动滚动...")
                
                # 模拟鼠标拖动
                page.mouse.move(500, 300)
                page.mouse.down()
                
                for _ in range(3):
                    page.mouse.move(500, 800)
                    time.sleep(0.5)
                
                page.mouse.up()
                time.sleep(3)
                
                # 再次检查
                final_videos = len(page.query_selector_all("li.wqW3g_Kl.WPzYSlFQ.OguQAD1e"))
                print(f"[滚动加载] 鼠标拖动后视频数量：{final_videos}")
            
            return True
        except Exception as e:
            print(f"[滚动加载] 滚动失败：{str(e)}")
            return False
    
    def random_user_agent(self) -> str:
        """随机生成用户代理"""
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Firefox/121.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Firefox/120.0"
        ]
        return random.choice(user_agents)

# ==============================================================================
# 数据导出类
# ==============================================================================
class DataExporter:
    """数据导出类，负责保存和导出数据"""
    
    def save_to_excel(self, data: List[Dict[str, Any]], filename: str) -> bool:
        """将数据保存到Excel文件"""
        try:
            df = pd.DataFrame(data)
            df.to_excel(filename, index=False, engine='openpyxl')
            print(f"🎉 数据已成功保存至：{filename}")
            return True
        except Exception as e:
            print(f"❌ 保存失败：{str(e)}")
            return False
    
    def insert_images(self, excel_path: str) -> bool:
        """在Excel中插入图片"""
        try:
            df = pd.read_excel(excel_path, engine='openpyxl')
            if "视频封面链接" not in df.columns:
                print("❌ 导入失败：Excel无「视频封面链接」列")
                return False
            
            # 让用户选择保存位置
            filename = os.path.basename(excel_path).replace(".xlsx", "")
            default_filename = f"{filename}_带图片_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            save_path = filedialog.asksaveasfilename(
                title="保存带图片的Excel文件",
                defaultextension=".xlsx",
                initialfile=default_filename,
                filetypes=[("Excel文件", "*.xlsx"), ("所有文件", "*.*")]
            )
            
            if not save_path:
                print("⚠️ 未选择保存路径，取消操作")
                return False
            
            if "视频封面" not in df.columns:
                img_link_col_idx = df.columns.get_loc("视频封面链接")
                df.insert(img_link_col_idx + 1, "视频封面", "")
            
            df.to_excel(save_path, index=False, engine='openpyxl')
            
            wb = load_workbook(save_path)
            ws = wb.active
            
            img_link_col_idx = df.columns.get_loc("视频封面链接") + 1
            img_col_idx = img_link_col_idx + 1
            ws.column_dimensions[chr(64 + img_link_col_idx)].width = 60
            ws.column_dimensions[chr(64 + img_col_idx)].width = 15
            
            headers = {
                'User-Agent': AntiCrawler().random_user_agent(),
                'Referer': 'https://www.douyin.com/'
            }
            
            success = 0
            fail = 0
            print(f"开始处理图片嵌入，共{len(df)}条数据...")
            
            for row_idx in range(len(df)):
                excel_row = row_idx + 2
                img_url = df.iloc[row_idx]["视频封面链接"]
                
                if img_url in ["未知", "", None] or not str(img_url).startswith(('http://', 'https://')):
                    print(f"第{excel_row - 1}条：无有效图片链接，跳过")
                    fail += 1
                    continue
                
                try:
                    response = requests.get(img_url, headers=headers, timeout=15, stream=True)
                    response.raise_for_status()
                    
                    img_buffer = BytesIO()
                    for chunk in response.iter_content(chunk_size=8192):
                        img_buffer.write(chunk)
                    img_buffer.seek(0)
                    
                    img = Image(img_buffer)
                    original_width = img.width
                    target_width = 100
                    img.width = target_width
                    img.height = int(img.height * (target_width / original_width))
                    
                    ws.row_dimensions[excel_row].height = img.height - 10
                    
                    cell_pos = f"{chr(64 + img_col_idx)}{excel_row}"
                    ws.add_image(img, cell_pos)
                    
                    success += 1
                    print(f"第{excel_row - 1}条：图片嵌入成功（{str(img_url)[:50]}...）")
                    
                except Exception as e:
                    print(f"第{excel_row - 1}条：图片嵌入失败 - {str(e)[:60]}")
                    fail += 1
                    continue
            
            wb.save(save_path)
            wb.close()
            
            print(f"🎉 图片嵌入完成！成功{success}张 | 失败{fail}张")
            return True
        except Exception as e:
            print(f"❌ 图片嵌入失败：{str(e)}")
            return False

# ==============================================================================
# 抖音爬虫类
# ==============================================================================
class DouyinSpider:
    """抖音视频博主数据采集类"""
    
    def __init__(self):
        self.anti_crawler = AntiCrawler()
        self.data_exporter = DataExporter()
        self.user_data_dir = os.path.join(os.path.dirname(__file__), "douyin_user_data")
        self.debug_port = 9222
        self.browser_ws_endpoint = f"ws://localhost:{self.debug_port}"
        self.is_browser_running = False
        self.is_collecting = False
        self.is_paused = False
        self.browser = None
        self.context = None
        self.page = None
        self.mouse = None
        self.playwright = None
        self.total_data = []
        self.current_count = 0
        self.daily_limit = 0
        self.today_collected = 0
    
    def launch_browser(self) -> bool:
        """启动浏览器"""
        try:
            if not os.path.exists(self.user_data_dir):
                os.makedirs(self.user_data_dir)
                print(f"[登录状态] 创建用户数据目录：{self.user_data_dir}")
            else:
                print(f"[登录状态] 加载用户数据目录：{self.user_data_dir}")
            
            print("开始尝试连接浏览器...")
            
            # 先检查调试端口是否可访问
            debugger_url = f"http://localhost:{self.debug_port}/json/version"
            response = requests.get(debugger_url, timeout=10)
            response.raise_for_status()
            data = response.json()
            websocket_url = data.get("webSocketDebuggerUrl")
            
            if not websocket_url:
                raise Exception("未获取到 WebSocket 调试地址，请检查浏览器是否正确启动。")
            
            print(f"[浏览器连接] 获取到 WebSocket URL：{websocket_url}")
            
            # 启动Playwright并连接（支持Edge浏览器）
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.connect_over_cdp(
                endpoint_url=websocket_url
            )
            print(f"[浏览器连接] 成功连接到浏览器实例！")
            
            if self.browser.contexts:
                self.context = self.browser.contexts[0]
                print(f"[浏览器连接] 复用了浏览器中已存在的上下文。")
            else:
                self.context = self.browser.new_context()
                print(f"[浏览器连接] 浏览器中无现有上下文，已创建一个新的上下文。")
            
            if self.context.pages:
                self.page = self.context.pages[0]
                print(f"[浏览器连接] 复用了上下文中已存在的页面。")
            else:
                self.page = self.context.new_page()
                print(f"[浏览器连接] 上下文中无现有页面，已创建一个新的页面。")
            
            self.page.wait_for_load_state("networkidle", timeout=30000)
            print(f"[浏览器连接] 成功导航到抖音页面。")
            
            self.mouse = self.page.mouse
            self.is_browser_running = True
            
            self.check_login_status()
            print(f"✅ 浏览器准备就绪（连接模式）")
            return True
        except Exception as e:
            print(f"❌ 浏览器连接失败：{str(e)}")
            # 确保清理资源
            if hasattr(self, 'playwright') and self.playwright:
                try:
                    self.playwright.stop()
                except:
                    pass
            self.is_browser_running = False
            return False
    
    def stop_browser(self) -> None:
        """停止浏览器"""
        try:
            if self.is_browser_running:
                if self.is_collecting:
                    self.is_collecting = False
                    self.is_paused = False
                    print("停止浏览器前，先终止当前采集任务...")
                    if self.total_data:
                        self.save_data()
                
                if self.context:
                    self.context.close()
                    self.context = None
                    print("✅ 浏览器上下文已关闭。")
                
                if self.browser:
                    self.browser.close()
                    self.browser = None
                    print("✅ 浏览器实例已关闭。")
                
                if self.playwright:
                    self.playwright.stop()
                    self.playwright = None
                    print("✅ Playwright 实例已停止。")
                
                self.page = None
                self.mouse = None
                self.is_browser_running = False
                
                print("✅ 浏览器已成功关闭（登录状态已保存）")
        except Exception as e:
            print(f"❌ 关闭浏览器时发生错误：{str(e)}")
    
    def check_login_status(self) -> bool:
        """检查登录状态"""
        try:
            print("[登录状态] 正在检查...")
            logged_in_selectors = [
                ".user-avatar",
                ".nickname",
                "a[href*='user']"
            ]
            for selector in logged_in_selectors:
                if self.page.wait_for_selector(selector, timeout=3000):
                    print(f"[登录状态] 检测到已登录元素：{selector}")
                    return True
        except Exception:
            print("[登录状态] 未检测到已登录元素，检查是否有“请登录”按钮...")
        
        try:
            login_btn = self.page.query_selector("a[href*='login']:has-text('登录')")
            is_logged_in = not bool(login_btn)
            if not is_logged_in:
                print("[登录状态] 检测到'登录'按钮，用户未登录。")
            else:
                print("[登录状态] 未检测到'登录'按钮，暂时认为已登录。")
            return is_logged_in
        except Exception as e:
            print(f"[登录状态] 检查失败：{str(e)}。暂时假设已登录。")
            return True
    
    def _check_connection(self) -> bool:
        """检查浏览器连接状态"""
        if not self.is_browser_running:
            print("❌ 浏览器未运行")
            return False
        try:
            # 尝试执行一个简单的操作来检查连接
            self.page.title()
            return True
        except Exception as e:
            print(f"❌ 浏览器连接已断开：{str(e)}")
            return False
    
    def collect_videos(self, scroll_count: int = 10) -> List[Dict[str, Any]]:
        """采集视频数据"""
        try:
            # 先检查浏览器连接状态
            if not self._check_connection():
                print("⚠️ 请先启动浏览器并连接")
                return []
            
            self.is_collecting = True
            self.total_data = []
            self.current_count = 0
            video_links = set()  # 用于去重的视频链接集合
            
            print("开始采集抖音博主视频数据...")
            print("请在浏览器中手动滚动页面，加载更多视频...")
            print("加载完成后，程序将自动开始采集...")
            
            # 等待用户手动滚动（每2秒检查一次连接状态）
            wait_time = 10
            check_interval = 2
            for i in range(int(wait_time / check_interval)):
                time.sleep(check_interval)
                if not self._check_connection():
                    print("⚠️ 浏览器连接已断开，停止采集")
                    self.is_collecting = False
                    return self.total_data
                print(f"等待用户滚动... ({wait_time - (i+1)*check_interval}秒)")
            
            # 再次确认连接状态
            if not self._check_connection():
                print("⚠️ 浏览器连接已断开，停止采集")
                self.is_collecting = False
                return self.total_data
            
            # 提取视频数据
            videos = self.extract_videos()
            if not videos:
                print("没有找到视频元素，可能需要登录或页面结构已变化")
                self.is_collecting = False
                return self.total_data
            
            print(f"找到 {len(videos)} 个视频")
            
            # 处理视频数据，进行去重
            new_videos_count = 0
            for video in videos:
                video_link = video.get("视频链接", "")
                if video_link and video_link not in video_links:
                    video_links.add(video_link)
                    self.total_data.append(video)
                    self.current_count += 1
                    self.today_collected += 1
                    new_videos_count += 1
                    print(f"✅ 采集到视频：{video['视频标题']}")
            
            print(f"去重后采集 {new_videos_count} 个视频")
            
            # 检查是否达到每日限制
            if self.daily_limit > 0 and self.today_collected >= self.daily_limit:
                print(f"[反爬] 今日采集已达上限 {self.daily_limit} 条，自动停止")
            
            print(f"\n=== 采集完成！共采集 {len(self.total_data)} 条视频数据（去重后）===")
            self.is_collecting = False
            return self.total_data
        except Exception as e:
            print(f"❌ 采集过程中发生错误：{str(e)}")
            self.is_collecting = False
            return self.total_data
    
    def extract_videos(self) -> List[Dict[str, Any]]:
        """提取视频数据"""
        videos = []
        try:
            # 抖音博主主页视频元素选择器（支持多种页面版本）
            video_selectors = [
                "li.wqW3g_Kl.WPzYSlFQ.OguQAD1e",  # 旧版本
                "li.FAPmDwBp.S3VjtEWW.E00pJ8bR"   # 新版本
            ]
            
            video_elements = []
            for selector in video_selectors:
                elements = self.page.query_selector_all(selector)
                if elements:
                    video_elements = elements
                    print(f"✅ 使用选择器: {selector}，找到 {len(elements)} 个视频")
                    break
            
            if not video_elements:
                print("❌ 未找到视频元素，尝试通用选择器...")
                video_elements = self.page.query_selector_all("li[class*='video']")
            
            for i, element in enumerate(video_elements):
                try:
                    # 提取视频链接（支持多种class）
                    link_selectors = [
                        "a.uz1VJwFY.TyuBARdT.IdxE71f8",  # 旧版本
                        "a.Z3VQe4ky.XKCfI_gm.CzeVtwuw"   # 新版本
                    ]
                    link_elem = None
                    for selector in link_selectors:
                        link_elem = element.query_selector(selector)
                        if link_elem:
                            break
                    if not link_elem:
                        link_elem = element.query_selector("a[href*='/video/']")
                    
                    video_link = link_elem.get_attribute("href") if link_elem else "未知"
                    if video_link.startswith("/"):
                        video_link = f"https://www.douyin.com{video_link}"
                    
                    # 提取视频封面
                    img_elem = element.query_selector("img")
                    cover_link = img_elem.get_attribute("src") if img_elem else "未知"
                    
                    # 提取视频标题（支持多种class）
                    title_selectors = [
                        "p.EtttsrEw",
                        "p.eJFBAbdI.H4IE9Xgd",
                        "p._ovpgIXn",
                        "p.xFJDpWP1.i8ELc0lC"
                    ]
                    title_elem = None
                    for selector in title_selectors:
                        title_elem = element.query_selector(selector)
                        if title_elem:
                            break
                    title = title_elem.text_content().strip() if title_elem else "未知"
                    
                    # 提取点赞数（支持多种class）
                    like_selectors = [
                        "span.BgCg_ebQ",
                        "span.U2k2aXSX"
                    ]
                    like_elem = None
                    for selector in like_selectors:
                        like_elem = element.query_selector(selector)
                        if like_elem:
                            break
                    likes = like_elem.text_content().strip() if like_elem else "0"
                    
                    # 提取是否置顶
                    is_pinned = "否"
                    pinned_elem = element.query_selector(".semi-tag-content")
                    if pinned_elem and "置顶" in pinned_elem.text_content():
                        is_pinned = "是"
                    
                    video_data = {
                        "序号": len(videos) + 1,
                        "视频标题": title,
                        "视频链接": video_link,
                        "视频封面链接": cover_link,
                        "点赞数": likes,
                        "是否置顶": is_pinned,
                        "采集时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    videos.append(video_data)
                except Exception as e:
                    print(f"❌ 提取视频数据失败：{str(e)}")
                    continue
            
            return videos
        except Exception as e:
            print(f"❌ 提取视频元素失败：{str(e)}")
            return videos
    
    def save_data(self) -> bool:
        """保存采集的数据"""
        if not self.total_data:
            print("⚠️ 没有可保存的数据")
            return False
        
        default_filename = f"抖音视频数据_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        save_path = filedialog.asksaveasfilename(
            title="保存视频数据文件",
            defaultextension=".xlsx",
            initialfile=default_filename,
            filetypes=[("Excel文件", "*.xlsx"), ("所有文件", "*.*")]
        )
        
        if save_path:
            return self.data_exporter.save_to_excel(self.total_data, save_path)
        return False

# ==============================================================================
# 授权系统类
# ==============================================================================
class Authorization:
    """授权系统类"""
    
    def __init__(self, secret_key: str):
        self.secret_key = secret_key
    
    def get_device_unique_id(self) -> str:
        """获取设备唯一标识"""
        try:
            c = wmi.WMI()
            cpu_serial = c.Win32_Processor()[0].ProcessorId.strip()
            disk_serial = c.Win32_LogicalDisk(DriveType=3)[0].VolumeSerialNumber.strip()
            unique_str = f"{cpu_serial}_{disk_serial}"
            return hashlib.md5(unique_str.encode()).hexdigest()[:16]
        except Exception as e:
            print(f"获取设备ID失败: {e}")
            return f"error_{hashlib.md5(str(e).encode()).hexdigest()[:8]}"
    
    def get_reliable_network_time(self) -> int:
        """获取可靠的网络时间"""
        from email.utils import parsedate_to_datetime
        def force_ipv4():
            import socket
            original_getaddrinfo = socket.getaddrinfo
            def new_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
                return original_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
            socket.getaddrinfo = new_getaddrinfo
        
        force_ipv4()
        
        baidu_api = {
            "name": "百度",
            "url": "https://www.baidu.com",
            "parser": lambda resp: parsedate_to_datetime(resp.headers['Date']).timestamp()
        }
        
        try:
            print(f"正在从 {baidu_api['name']} 获取网络时间...")
            response = requests.get(baidu_api["url"], timeout=8)
            response.raise_for_status()
            
            timestamp = baidu_api["parser"](response)
            formatted_time = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
            print(f"✅ 成功从 {baidu_api['name']} 获取网络时间：{formatted_time}")
            return int(timestamp)
        except Exception as e:
            print(f"❌ 网络时间获取失败: {e}")
            local_timestamp = int(time.time())
            formatted_local_time = datetime.fromtimestamp(local_timestamp).strftime('%Y-%m-%d %H:%M:%S')
            print(f"⚠️ 使用本地时间：{formatted_local_time}")
            return local_timestamp
    
    def check_auth_code(self, device_id: str, input_auth_code: str) -> tuple:
        """校验授权码是否有效"""
        if len(input_auth_code) != 38 or input_auth_code[20] != '_':
            return False, "授权码格式错误"
        
        received_signature = input_auth_code[:20]
        try:
            received_expire_timestamp = float(input_auth_code[21:])
        except ValueError:
            return False, "过期时间戳无效"
        
        data_to_hash = f"{device_id}_{received_expire_timestamp}_{self.secret_key}"
        correct_signature = hashlib.sha256(data_to_hash.encode()).hexdigest()[:20]
        
        if received_signature != correct_signature:
            return False, "授权码无效或已被篡改"
        
        current_time = self.get_reliable_network_time() or time.time()
        if received_expire_timestamp < current_time:
            return False, "授权码已过期"
        
        return True, received_expire_timestamp
    
    def check_authorization(self) -> tuple:
        """检查授权状态"""
        auth_file = "auth_status.ini"
        if os.path.exists(auth_file):
            try:
                config = {}
                with open(auth_file, "r") as f:
                    for line in f:
                        if '=' in line:
                            key, value = line.strip().split("=", 1)
                            config[key] = value
                
                saved_device_id = config.get("device_id")
                saved_expire_timestamp = float(config.get("expire_timestamp", 0))
                
                current_device_id = self.get_device_unique_id()
                if saved_device_id != current_device_id:
                    return False, "授权文件与当前设备不匹配"
                
                data_to_hash = f"{current_device_id}_{saved_expire_timestamp}_{self.secret_key}"
                correct_signature = hashlib.sha256(data_to_hash.encode()).hexdigest()[:20]
                saved_auth_code = config.get("auth_code", "")
                if not saved_auth_code or not saved_auth_code.startswith(correct_signature):
                    return False, "授权文件已被篡改"
                
                current_time = self.get_reliable_network_time() or time.time()
                if current_time > saved_expire_timestamp:
                    return False, "授权已过期"
                
                return True, saved_expire_timestamp
            except Exception as e:
                return False, f"授权文件损坏：{str(e)}"
        else:
            return False, "未找到授权文件"
    
    def activate(self, device_id: str, input_auth_code: str) -> tuple:
        """激活软件"""
        is_valid, result = self.check_auth_code(device_id, input_auth_code)
        if not is_valid:
            return False, result
        
        with open("auth_status.ini", "w") as f:
            f.write(f"device_id={device_id}\n")
            f.write(f"auth_code={input_auth_code}\n")
            f.write(f"activate_time={time.time()}\n")
            f.write(f"expire_timestamp={result}\n")
        
        return True, "激活成功"

# ==============================================================================
# 免责声明窗口类
# ==============================================================================
class DisclaimerApp(tk.Tk):
    """免责声明窗口"""
    
    def __init__(self):
        super().__init__()
        self.title("用户许可协议与免责声明")
        self.geometry("800x500")
        self.resizable(False, False)
        self.after(0, lambda: self.eval('tk::PlaceWindow . center'))
        
        # 标题
        title_label = tk.Label(self, text="重要声明，请仔细阅读", font=("Helvetica", 14, "bold"), fg="red")
        title_label.pack(pady=10)
        
        # 带滚动条的文本框
        self.text_area = scrolledtext.ScrolledText(self, wrap=tk.WORD, width=70, height=20, font=("SimSun", 10))
        self.text_area.insert(tk.END, DISCLAIMER_TEXT)
        self.text_area.config(state=tk.DISABLED)
        self.text_area.pack(padx=15, pady=5, fill=tk.BOTH, expand=True)
        
        # 按钮框架
        button_frame = tk.Frame(self)
        button_frame.pack(pady=10)
        
        # “同意”按钮
        accept_btn = tk.Button(button_frame, text="我已阅读并同意", command=self.accept, width=20, height=2, bg="#90EE90")
        accept_btn.pack(side=tk.LEFT, padx=20)
        
        # “不同意”按钮
        decline_btn = tk.Button(button_frame, text="我不同意", command=self.decline, width=20, height=2, bg="#FFB6C1")
        decline_btn.pack(side=tk.LEFT, padx=20)
        
        self.main_app = None
    
    def accept(self):
        """用户同意，关闭声明窗口，启动主程序"""
        self.destroy()
        root = tk.Tk()
        self.main_app = SpiderGUI(root)
        if self.main_app:
            self.main_app.log("✅ 用户已阅读并同意《免责声明》。")
        root.mainloop()
    
    def decline(self):
        """用户不同意，退出程序"""
        messagebox.showwarning("无法继续", "您必须同意本声明才能使用本软件。程序将退出。")
        self.destroy()

# ==============================================================================
# 主界面类
# ==============================================================================
class SpiderGUI:
    """主界面类"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("抖音视频博主数据采集工具")
        self.root.geometry("1050x750")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
        # 授权状态变量
        self.is_authorized = False
        self.expire_timestamp = 0.0
        self.activate_time = 0.0
        
        # 爬虫实例
        self.spider = DouyinSpider()
        self.authorization = Authorization(SECRET_KEY)
        
        # 其他状态变量
        self.task_queue = queue.Queue()
        self.scroll_count = 10
        
        # 创建界面组件
        self.create_widgets()
        
        # 启动时自动检查授权状态
        self.check_authorization_on_startup()
        
        # 启动周期性授权检查
        self.root.after(60 * 1000, self.periodic_authorization_check)
        
        # 启动任务处理器
        self.process_tasks()
    
    def create_widgets(self):
        """创建界面组件"""
        # 授权码区域
        self.auth_frame = ttk.LabelFrame(self.root, text="软件授权", padding=(10, 5))
        self.auth_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(self.auth_frame, text="设备ID:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.device_id_var = tk.StringVar(value=self.authorization.get_device_unique_id())
        self.device_id_label = ttk.Label(self.auth_frame, textvariable=self.device_id_var, foreground="red",
                                         font=('Helvetica', 10, 'bold'))
        self.device_id_label.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        ttk.Label(self.auth_frame, text="(复制此ID向卖家购买授权码)").grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        
        ttk.Label(self.auth_frame, text="授权码:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        self.auth_code_var = tk.StringVar()
        self.auth_code_entry = ttk.Entry(self.auth_frame, textvariable=self.auth_code_var, width=35)
        self.auth_code_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)
        self.activate_btn = ttk.Button(self.auth_frame, text="激活软件", command=self.activate_software)
        self.activate_btn.grid(row=1, column=2, padx=5, pady=5, sticky=tk.W)
        
        self.auth_status_var = tk.StringVar(value="未授权（功能受限）")
        self.auth_status_label = ttk.Label(self.auth_frame, textvariable=self.auth_status_var, foreground="orange")
        self.auth_status_label.grid(row=1, column=3, padx=5, pady=5, sticky=tk.W)
        
        # 采集参数配置区域
        self.config_frame = ttk.LabelFrame(self.root, text="采集参数配置", padding=(10, 5))
        self.config_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(self.config_frame, text="登录状态：").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.login_status_var = tk.StringVar(value="未登录（首次启动需手动登录一次）")
        ttk.Label(self.config_frame, textvariable=self.login_status_var, foreground="orange").grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        
        ttk.Label(self.config_frame, text="滚动次数：").grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        self.scroll_count_var = tk.StringVar(value="10")
        self.scroll_count_entry = ttk.Entry(self.config_frame, textvariable=self.scroll_count_var, width=10)
        self.scroll_count_entry.grid(row=0, column=3, padx=5, pady=5)
        ttk.Label(self.config_frame, text="（每滚动一次会加载更多视频）").grid(row=0, column=4, padx=5, pady=5, sticky=tk.W)
        
        # 控制按钮区域
        self.btn_frame = ttk.Frame(self.root)
        self.btn_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.launch_browser_btn = ttk.Button(self.btn_frame, text="启动浏览器", command=self.launch_browser)
        self.launch_browser_btn.pack(side=tk.LEFT, padx=5)
        self.stop_browser_btn = ttk.Button(self.btn_frame, text="停止浏览器", command=self.stop_browser, state=tk.DISABLED)
        self.stop_browser_btn.pack(side=tk.LEFT, padx=5)
        self.start_collect_btn = ttk.Button(self.btn_frame, text="开始采集视频数据", command=self.start_collect, state=tk.DISABLED)
        self.start_collect_btn.pack(side=tk.LEFT, padx=5)
        self.pause_collect_btn = ttk.Button(self.btn_frame, text="暂停采集", command=self.pause_collect, state=tk.DISABLED)
        self.pause_collect_btn.pack(side=tk.LEFT, padx=5)
        self.resume_collect_btn = ttk.Button(self.btn_frame, text="继续采集", command=self.resume_collect, state=tk.DISABLED)
        self.resume_collect_btn.pack(side=tk.LEFT, padx=5)
        self.manual_save_btn = ttk.Button(self.btn_frame, text="手动保存数据", command=self.save_data, state=tk.DISABLED)
        self.manual_save_btn.pack(side=tk.LEFT, padx=5)
        self.insert_img_btn = ttk.Button(self.btn_frame, text="导入表格插入图片", command=self.import_excel_insert_img)
        self.insert_img_btn.pack(side=tk.LEFT, padx=5)
        
        # 进度显示区域
        self.progress_frame = ttk.Frame(self.root)
        self.progress_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(self.progress_frame, text="采集进度：").pack(side=tk.LEFT, padx=5)
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(self.progress_frame, variable=self.progress_var, maximum=100, length=700)
        self.progress_bar.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.progress_label = ttk.Label(self.progress_frame, text="0/0 条 (0%) | 今日已采：0条")
        self.progress_label.pack(side=tk.LEFT, padx=5)
        
        # 状态显示区域
        self.status_frame = ttk.Frame(self.root)
        self.status_frame.pack(fill=tk.X, padx=10, pady=2)
        ttk.Label(self.status_frame, text="当前状态：").pack(side=tk.LEFT, padx=5)
        self.status_var = tk.StringVar(value="就绪 - 功能1：采集视频数据 | 功能2：导入表格插图片")
        ttk.Label(self.status_frame, textvariable=self.status_var, foreground="blue").pack(side=tk.LEFT, padx=5)
        
        # 日志区域
        self.log_frame = ttk.LabelFrame(self.root, text="操作日志", padding=(10, 5))
        self.log_frame.pack(fill=tk.BOTH, padx=10, pady=5, expand=True)
        self.log_text = tk.Text(self.log_frame, width=80, height=20, state=tk.DISABLED)
        self.scrollbar = ttk.Scrollbar(self.log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=self.scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    
    def check_authorization_on_startup(self):
        """启动时检查授权状态"""
        is_valid, result = self.authorization.check_authorization()
        if is_valid:
            self.is_authorized = True
            self.expire_timestamp = result
            self.log("授权文件验证成功！")
            self.update_auth_status()
            self.update_buttons_state()
        else:
            self.log(f"未授权：{result}")
            self.update_auth_status(f"未授权：{result}", "red")
    
    def activate_software(self):
        """激活软件"""
        input_auth_code = self.auth_code_var.get().strip()
        device_id = self.authorization.get_device_unique_id()
        
        is_valid, result = self.authorization.activate(device_id, input_auth_code)
        if not is_valid:
            messagebox.showerror("激活失败", f"授权码无效！{result}")
            return
        
        self.is_authorized = True
        # 重新检查授权状态以获取过期时间戳
        _, self.expire_timestamp = self.authorization.check_authorization()
        self.activate_time = time.time()
        
        messagebox.showinfo("激活成功", "软件激活成功！所有功能已解锁。")
        self.log("软件激活成功！")
        self.update_auth_status()
        self.update_buttons_state()
    
    def update_auth_status(self, custom_msg=None, color=None):
        """更新授权状态显示"""
        if custom_msg:
            self.auth_status_var.set(custom_msg)
            self.auth_status_label.config(foreground=color)
            return
        
        if not self.is_authorized:
            self.auth_status_var.set("未授权（功能受限）")
            self.auth_status_label.config(foreground="orange")
            return
        
        current_time = self.authorization.get_reliable_network_time() or int(time.time())
        time_source = "网络时间" if current_time != int(time.time()) else "本地时间(可能不准确)"
        
        remaining_seconds = self.expire_timestamp - current_time
        
        if remaining_seconds <= 0:
            self.is_authorized = False
            self.auth_status_var.set("授权已过期")
            self.auth_status_label.config(foreground="red")
            self.update_buttons_state()
        else:
            remaining_days = int(remaining_seconds / 86400)
            remaining_hours = int((remaining_seconds % 86400) / 3600)
            status_text = f"已授权 ({time_source}, 剩余 {remaining_days}天{remaining_hours}小时)"
            self.auth_status_var.set(status_text)
            self.auth_status_label.config(foreground="green")
    
    def update_buttons_state(self):
        """根据授权状态更新按钮状态"""
        # 核心功能按钮，未授权时禁用
        core_buttons = [self.launch_browser_btn, self.start_collect_btn, self.insert_img_btn]
        if self.is_authorized:
            for btn in core_buttons:
                btn.config(state=tk.NORMAL)
        else:
            for btn in core_buttons:
                btn.config(state=tk.DISABLED)
        
        # 其他按钮状态
        self.stop_browser_btn.config(state=tk.NORMAL if self.spider.is_browser_running else tk.DISABLED)
        self.manual_save_btn.config(state=tk.NORMAL if self.spider.total_data else tk.DISABLED)
        
        if self.spider.is_browser_running and not self.spider.is_collecting:
            self.start_collect_btn.config(state=tk.NORMAL if self.is_authorized else tk.DISABLED)
            self.pause_collect_btn.config(state=tk.DISABLED)
            self.resume_collect_btn.config(state=tk.DISABLED)
        elif self.spider.is_collecting:
            self.start_collect_btn.config(state=tk.DISABLED)
            self.pause_collect_btn.config(state=tk.NORMAL if not self.spider.is_paused else tk.DISABLED)
            self.resume_collect_btn.config(state=tk.NORMAL if self.spider.is_paused else tk.DISABLED)
        else:
            self.start_collect_btn.config(state=tk.NORMAL if self.is_authorized else tk.DISABLED)
            self.pause_collect_btn.config(state=tk.DISABLED)
            self.resume_collect_btn.config(state=tk.DISABLED)
    
    def launch_browser(self):
        """启动浏览器"""
        if not self.is_authorized:
            messagebox.showwarning("未授权", "软件未授权或已过期，无法使用此功能！")
            return
        
        if self.spider.is_browser_running:
            messagebox.showinfo("提示", "浏览器已连接，无需重复操作")
            return
        
        self.log("开始尝试连接浏览器...")
        self.update_status("正在连接浏览器...", "orange")
        self.task_queue.put(("launch_browser",))
    
    def stop_browser(self):
        """停止浏览器"""
        if not self.spider.is_browser_running:
            return
        
        if self.spider.is_collecting:
            self.spider.is_collecting = False
            self.spider.is_paused = False
            self.log("停止浏览器前，先终止当前采集任务...")
            if self.spider.total_data:
                self.save_data()
        
        self.task_queue.put(("stop_browser",))
    
    def start_collect(self):
        """开始采集"""
        if not self.is_authorized:
            messagebox.showwarning("未授权", "软件未授权或已过期，无法使用此功能！")
            return
        
        if not self.spider.is_browser_running:
            messagebox.showinfo("提示", "请先启动浏览器")
            return
        
        if self.spider.is_collecting:
            messagebox.showinfo("提示", "正在采集数据，请不要重复操作")
            return
        
        if not self.spider.check_login_status():
            messagebox.showwarning("未登录", "请先在浏览器中完成登录")
            return
        
        try:
            self.scroll_count = int(self.scroll_count_var.get().strip())
            if self.scroll_count < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror("输入错误", "请输入有效的正整数作为滚动次数！")
            return
        
        self.log(f"=== 开始采集抖音视频数据，滚动 {self.scroll_count} 次 ===")
        self.update_status("正在采集视频数据...", "green")
        self.update_buttons_state()
        
        # 启动采集任务
        self.task_queue.put(("collect_videos", self.scroll_count))
    
    def pause_collect(self):
        """暂停采集"""
        if self.spider.is_collecting and not self.spider.is_paused:
            self.spider.is_paused = True
            self.update_status("已暂停采集", "orange")
            self.log("已手动暂停采集")
            self.update_buttons_state()
    
    def resume_collect(self):
        """继续采集"""
        if self.spider.is_collecting and self.spider.is_paused:
            if not self.spider.check_login_status():
                messagebox.showwarning("登录失效", "请重新登录后再继续")
                return
            
            self.spider.is_paused = False
            self.update_status("继续采集视频数据...", "green")
            self.log("恢复采集...")
            self.update_buttons_state()
    
    def save_data(self):
        """保存数据"""
        if self.spider.save_data():
            messagebox.showinfo("保存成功", f"共采集{len(self.spider.total_data)}条视频数据")
        else:
            messagebox.showinfo("保存取消", "未保存数据")
    
    def import_excel_insert_img(self):
        """导入表格并插入图片"""
        if not self.is_authorized:
            messagebox.showwarning("未授权", "软件未授权或已过期，无法使用此功能！")
            return
        
        import_path = filedialog.askopenfilename(
            title="选择已采集的Excel文件",
            filetypes=[("Excel文件", "*.xlsx"), ("所有文件", "*.*")]
        )
        
        if not import_path:
            self.log("⚠️ 未选择Excel文件，取消操作")
            return
        
        if self.spider.data_exporter.insert_images(import_path):
            messagebox.showinfo("处理完成", "图片嵌入任务完成！")
        else:
            messagebox.showerror("处理失败", "图片嵌入失败")
    
    def process_tasks(self):
        """处理任务队列"""
        try:
            if not self.task_queue.empty():
                task = self.task_queue.get()
                task_type = task[0]
                
                if task_type == "launch_browser":
                    if self.spider.launch_browser():
                        self.update_status("已连接到浏览器 - 可点击「开始采集视频数据」", "green")
                        self.update_buttons_state()
                        self.spider.check_login_status()
                    else:
                        self.update_status("浏览器连接失败！", "red")
                        messagebox.showerror("连接失败", "请确保浏览器已通过 --remote-debugging-port=9222 启动")
                        self.update_buttons_state()
                
                elif task_type == "stop_browser":
                    self.spider.stop_browser()
                    self.update_status("就绪 - 下次启动将自动恢复登录状态", "blue")
                    self.update_buttons_state()
                
                elif task_type == "collect_videos":
                    scroll_count = task[1]
                    videos = self.spider.collect_videos(scroll_count)
                    self.update_status(f"采集完成（共{len(videos)}条视频）", "purple")
                    self.update_buttons_state()
                    messagebox.showinfo("采集完成", f"共采集{len(videos)}条视频数据")
                
                self.task_queue.task_done()
        except Exception as e:
            self.log(f"任务处理出错：{str(e)}")
        
        self.root.after(100, self.process_tasks)
    
    def log(self, msg):
        """记录日志"""
        self.root.after(0, lambda: self._update_log(msg))
    
    def _update_log(self, msg):
        """更新日志界面"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"{time.strftime('%H:%M:%S')} - {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
    
    def update_status(self, status, color="blue"):
        """更新状态显示"""
        self.status_var.set(status)
        self.root.after(0, lambda: self.status_frame.children["!label2"].configure(foreground=color))
    
    def periodic_authorization_check(self):
        """周期性检查授权状态"""
        if not self.is_authorized:
            return
        
        current_time = self.authorization.get_reliable_network_time() or time.time()
        if int(current_time) > int(self.expire_timestamp):
            self.log("授权已在运行期间过期！")
            self.is_authorized = False
            self.update_auth_status("授权已过期", "red")
            self.update_buttons_state()
            messagebox.showwarning("授权过期", "您的软件授权已在运行期间过期，请重启程序或联系卖家续费。")
        else:
            self.update_auth_status()
        
        self.root.after(600 * 1000, self.periodic_authorization_check)
    
    def on_close(self):
        """关闭窗口时的处理"""
        if self.spider.is_browser_running:
            if messagebox.askyesno("确认关闭", "浏览器正在运行，确定要关闭窗口吗？"):
                self.spider.stop_browser()
                time.sleep(1)
                self.root.destroy()
        else:
            self.root.destroy()

# ==============================================================================
# 主程序入口
# ==============================================================================
if __name__ == "__main__":
    # 1. 启动免责声明窗口
    disclaimer_window = DisclaimerApp()
    disclaimer_window.mainloop()
