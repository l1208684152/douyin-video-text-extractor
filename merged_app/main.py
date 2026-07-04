# -*- coding: utf-8 -*-
"""
抖音视频文案处理一体化工具
合并功能：视频信息采集 → 文案提取(下载+音频识别) → AI文案修正
"""

import sys
import os
import json
import subprocess
import threading
import tempfile
import shutil
import time
import re
import random
import hashlib
from io import BytesIO
from datetime import datetime

# ══════════════════════════════════════════════════════════════════════════════
# 第一部分: 常规库导入
# ══════════════════════════════════════════════════════════════════════════════

import requests
import pandas as pd
import ffmpeg
import yt_dlp
import numpy as np

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QTextEdit, QProgressBar, QFileDialog,
    QMessageBox, QComboBox, QGroupBox, QGridLayout, QSplitter,
    QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer

# ══════════════════════════════════════════════════════════════════════════════
# 第三部分: 全局配置
# ══════════════════════════════════════════════════════════════════════════════

USE_WHISPER = True
WHISPER_MODEL_SIZE = "large-v3-turbo"  # tiny/base/small/medium/large/large-v3-turbo

FFMPEG_AVAILABLE = False
FFMPEG_EXE = None
try:
    import imageio_ffmpeg
    FFMPEG_AVAILABLE = True
    FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    pass

PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    pass

# ══════════════════════════════════════════════════════════════════════════════
# 第四部分: 全局辅助函数
# ══════════════════════════════════════════════════════════════════════════════

def log_to_file(msg: str):
    """输出到控制台（可扩展为写日志文件）"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def clean_url(url: str) -> str:
    """清理视频链接"""
    cleaned = str(url).strip().replace('`', '')
    cleaned = re.sub(r'\s+', '', cleaned)
    return cleaned


def find_video_url_column(df: pd.DataFrame):
    """在 DataFrame 中查找视频链接列（排除封面/图片链接列）"""
    for col in df.columns:
        lower = col.lower()
        # 排除封面、图片相关的列
        if any(kw in col for kw in ['封面', 'cover', '图片', 'image', 'img']):
            continue
        if ('视频' in col and '链接' in col) or ('video' in lower and ('url' in lower or 'link' in lower)):
            return col
    for col in df.columns:
        lower = col.lower()
        if any(kw in col for kw in ['封面', 'cover', '图片', 'image', 'img']):
            continue
        if '链接' in col or 'url' in lower or 'link' in lower:
            return col
    return None


def is_video_page_url(url: str) -> bool:
    """判断是否为视频页面链接（非封面/图片链接）"""
    cleaned = clean_url(url)
    if not cleaned.startswith('http'):
        return False
    # 封面图片域名
    if any(d in cleaned for d in ['douyinpic.com', 'pstatp.com', 'ixigua.com/image']):
        return False
    # 图片扩展名
    if cleaned.endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif')):
        return False
    return True


# ══════════════════════════════════════════════════════════════════════════════
# 第五部分: 工作线程
# ══════════════════════════════════════════════════════════════════════════════

class BrowserDownloadThread(QThread):
    """通过浏览器下载视频"""
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(list)

    def __init__(self, video_urls, temp_dir, video_save_dir=None, debug_port=9222):
        super().__init__()
        self.video_urls = video_urls
        self.temp_dir = temp_dir
        self.video_save_dir = video_save_dir or temp_dir
        self.debug_port = debug_port
        self.abort = False

    def run(self):
        downloaded = []
        total = len(self.video_urls)
        max_retries = 3
        if not PLAYWRIGHT_AVAILABLE:
            self.progress_signal.emit(0, "Playwright 未安装，尝试使用 yt-dlp...")
            self._use_ytdlp_fallback()
            return

        for i, url in enumerate(self.video_urls):
            if self.abort:
                break
            video_path = None
            for attempt in range(1, max_retries + 1):
                if self.abort:
                    break
                try:
                    self.progress_signal.emit(int((i + 1) / total * 100),
                        f"正在处理第 {i+1} 个视频{f'(重试 {attempt}/{max_retries})' if attempt > 1 else ''}...")
                    video_path = self._download_one(url, i)
                    if video_path:
                        downloaded.append((url, video_path))
                        self.progress_signal.emit(int((i + 1) / total * 100), f"第 {i+1} 个下载成功")
                        break
                    elif attempt < max_retries:
                        delay = 2 ** attempt
                        self.progress_signal.emit(int((i + 1) / total * 100),
                            f"第 {i+1} 个下载失败，{delay}s 后重试...")
                        time.sleep(delay)
                except Exception as e:
                    if attempt < max_retries:
                        time.sleep(2 ** attempt)
                    else:
                        self.progress_signal.emit(int((i + 1) / total * 100), f"错误: {str(e)[:80]}")
            if not video_path:
                downloaded.append((url, None))
                self.progress_signal.emit(int((i + 1) / total * 100), f"第 {i+1} 个下载失败(已重试{max_retries}次)")
        self.finished_signal.emit(downloaded)

    def _download_one(self, url: str, index: int):
        video_id = url.split('/')[-1].split('?')[0]
        output_path = os.path.join(self.video_save_dir, f"video_{index}_{video_id}.mp4")
        video_path = None

        try:
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(
                    f"http://localhost:{self.debug_port}", timeout=10000
                )
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.new_page()

                captured_url = [None]

                def on_response(response):
                    if captured_url[0] is None:
                        r_url = response.url
                        if any(d in r_url for d in ['douyinvod', 'v3-dy', 'amemv']) or r_url.endswith('.mp4'):
                            if any(k in r_url.lower() for k in ['sign', 'token', 'play']):
                                captured_url[0] = r_url

                page.on("response", on_response)
                try:
                    page.goto(url, timeout=30000, wait_until="domcontentloaded")
                except:
                    page.goto(f"https://www.douyin.com/video/{video_id}", timeout=15000,
                              wait_until="domcontentloaded", ignore_https_errors=True)

                page.wait_for_timeout(5000)

                # 方法1: video 元素
                try:
                    video_el = page.query_selector("video")
                    if video_el:
                        src = video_el.get_attribute("src")
                        if src and not src.startswith("blob:"):
                            if src.startswith("//"):
                                src = "https:" + src
                            self._download_file(src, output_path)
                            if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
                                video_path = output_path
                except:
                    pass

                # 方法2: JS 提取
                if not video_path:
                    try:
                        result = page.evaluate("""
                            () => {
                                const h = document.documentElement.outerHTML;
                                const m = h.match(/"playAddr"\\s*:\\s*"([^"]+)"/);
                                if (m) { let u = m[1].replace(/\\\\u002F/g, '/'); if (u.startsWith('//')) u = 'https:' + u; return u; }
                                const og = document.querySelector('meta[property="og:video"]');
                                if (og) return og.content;
                                return null;
                            }
                        """)
                        if result and result.startswith("http"):
                            self._download_file(result, output_path)
                            if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
                                video_path = output_path
                    except:
                        pass

                # 方法3: 抖音 API
                if not video_path:
                    try:
                        api_result = page.evaluate(f"""
                            async () => {{
                                const r = await fetch('https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id={video_id}&aid=6383&device_platform=webapp',
                                    {{ headers: {{ 'Referer': 'https://www.douyin.com/video/{video_id}' }} }});
                                const d = await r.json();
                                const urls = d?.aweme_detail?.video?.play_addr?.url_list;
                                return urls ? JSON.stringify({{url: urls[0]}}) : JSON.stringify({{error: 'no url'}});
                            }}
                        """)
                        data = json.loads(api_result)
                        if 'url' in data:
                            self._download_file(data['url'], output_path)
                            if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
                                video_path = output_path
                    except:
                        pass

                # 方法4: 网络捕获
                if not video_path and captured_url[0]:
                    self._download_file(captured_url[0], output_path)
                    if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
                        video_path = output_path

                page.close()
        except Exception as e:
            self.progress_signal.emit(0, f"浏览器错误: {str(e)[:80]}")

        return video_path if video_path and os.path.exists(video_path) and os.path.getsize(video_path) > 10000 else None

    def _download_file(self, url, output_path):
        if url.startswith("blob:"):
            return
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.douyin.com/',
        }
        try:
            resp = requests.get(url, headers=headers, stream=True, timeout=30)
            if resp.status_code == 200:
                with open(output_path, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if self.abort:
                            break
                        f.write(chunk)
        except:
            pass

    def _use_ytdlp_fallback(self):
        cookies_file = os.path.join(os.path.dirname(__file__), 'cookies.txt')
        downloaded = []
        for i, url in enumerate(self.video_urls):
            if self.abort:
                break
            try:
                output_dir = os.path.join(self.temp_dir, f"video_{i}")
                os.makedirs(output_dir, exist_ok=True)
                ydl_opts = {
                    'format': 'best', 'quiet': True, 'no_warnings': True,
                    'outtmpl': os.path.join(output_dir, 'video.%(ext)s'),
                }
                if os.path.exists(cookies_file):
                    ydl_opts['cookiefile'] = cookies_file
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                found = None
                for root, _, files in os.walk(output_dir):
                    for f in files:
                        if f.endswith(('.mp4', '.flv', '.avi', '.mov')):
                            found = os.path.join(root, f)
                            break
                downloaded.append((url, found))
                self.progress_signal.emit(int((i + 1) / len(self.video_urls) * 100),
                                          f"yt-dlp 下载{'成功' if found else '失败'}: 第 {i+1} 个")
            except Exception as e:
                downloaded.append((url, None))
                self.progress_signal.emit(int((i + 1) / len(self.video_urls) * 100), f"错误: {str(e)[:80]}")
        self.finished_signal.emit(downloaded)


class ExtractAudioThread(QThread):
    """提取音频"""
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(list)

    def __init__(self, video_files, temp_dir):
        super().__init__()
        self.video_files = video_files
        self.temp_dir = temp_dir
        self.abort = False

    def run(self):
        audio_files = []
        total = len(self.video_files)
        for i, (url, video_path) in enumerate(self.video_files):
            if self.abort:
                break
            if not video_path or not os.path.exists(video_path) or os.path.getsize(video_path) < 1000:
                audio_files.append((url, None))
                continue
            try:
                audio_path = os.path.join(self.temp_dir, f"audio_{i}.wav")
                extracted = False

                if FFMPEG_AVAILABLE and FFMPEG_EXE:
                    try:
                        cmd = [FFMPEG_EXE, '-i', video_path, '-ac', '1', '-ar', '16000',
                               '-f', 'wav', '-y', audio_path]
                        result = subprocess.run(cmd, capture_output=True, timeout=60)
                        if result.returncode == 0 and os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
                            audio_files.append((url, audio_path))
                            extracted = True
                    except:
                        pass

                if not extracted:
                    try:
                        (ffmpeg.input(video_path).output(audio_path, ac=1, ar=16000, format='wav')
                         .overwrite_output().run(capture_stdout=True, capture_stderr=True))
                        if os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
                            audio_files.append((url, audio_path))
                            extracted = True
                    except:
                        pass

                if not extracted:
                    audio_files.append((url, None))

                self.progress_signal.emit(int((i + 1) / total * 100),
                                          f"音频提取: {i+1}/{total} {'成功' if extracted else '失败'}")
            except:
                audio_files.append((url, None))

        self.finished_signal.emit(audio_files)


class TranscribeThread(QThread):
    """语音转文字 — 多子进程并行，模型只加载一次，断点续传"""
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(list)

    def __init__(self, audio_files, input_file="", save_file="", workers=0):
        super().__init__()
        self.audio_files = audio_files
        self.input_file = input_file
        self.save_file = save_file
        self.abort = False
        # 自动检测 workers 数量：默认 min(2, CPU/2)
        import multiprocessing
        cpu = multiprocessing.cpu_count()
        self.workers = workers if workers > 0 else min(2, max(1, cpu // 2))

    @staticmethod
    def _whisper_worker_script():
        return (
            "import sys, json, warnings\n"
            "warnings.filterwarnings('ignore')\n"
            "sys.stdout.reconfigure(encoding='utf-8')\n"
            "import whisper\n"
            "model = whisper.load_model(sys.argv[1])\n"
            "sys.stderr.write('MODEL_READY\\n')\n"
            "sys.stderr.flush()\n"
            "for line in sys.stdin:\n"
            "    line = line.strip()\n"
            "    if line == 'DONE' or not line:\n"
            "        break\n"
            "    parts = line.split('|', 1)\n"
            "    task_url = parts[0] if len(parts) > 1 else ''\n"
            "    path = parts[1] if len(parts) > 1 else line\n"
            "    try:\n"
            "        r = model.transcribe(path, language='zh', fp16=False,"
            "            initial_prompt='请将以下中文语音转换为简体中文文字。')\n"
            "        print(json.dumps({'url': task_url, 'ok': True, 'text': r['text'].strip()}, ensure_ascii=False), flush=True)\n"
            "    except Exception as e:\n"
            "        print(json.dumps({'url': task_url, 'ok': False, 'error': str(e)}, ensure_ascii=False), flush=True)\n"
        )

    def _save_progress(self, results):
        """增量保存识别结果到 Excel"""
        if not self.save_file or not self.input_file:
            return
        try:
            df = pd.read_csv(self.input_file, encoding='utf-8') if self.input_file.endswith('.csv') else pd.read_excel(self.input_file)
            col = find_video_url_column(df)
            if col and '视频文案' not in df.columns:
                df['视频文案'] = ''
            if col:
                for i, url in enumerate(df[col]):
                    if pd.notna(url):
                        cleaned = clean_url(url)
                        if cleaned in results and results[cleaned]:
                            df.at[i, '视频文案'] = results[cleaned]
            if self.save_file.endswith('.csv'):
                df.to_csv(self.save_file, index=False, encoding='utf-8-sig')
            else:
                df.to_excel(self.save_file, index=False)
        except:
            pass

    def _start_worker(self, worker_id):
        """启动一个 whisper 子进程"""
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        return subprocess.Popen(
            [sys.executable, '-c', self._whisper_worker_script(), WHISPER_MODEL_SIZE],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace',
            env=env, bufsize=1
        )

    def _transcribe_batch_parallel(self, valid_audio):
        """并行子进程批量处理"""
        total = len(valid_audio)
        results = {}
        n_workers = min(self.workers, total)

        self.progress_signal.emit(0, f"[Whisper] 启动 {n_workers} 个并行子进程, 加载 {WHISPER_MODEL_SIZE}...")

        workers = []
        for w in range(n_workers):
            proc = self._start_worker(w)
            workers.append(proc)

        # 等待所有 worker 就绪
        deadline = time.time() + 600
        for w, proc in enumerate(workers):
            while time.time() < deadline:
                if self.abort:
                    for p in workers:
                        p.kill()
                    return results
                line = proc.stderr.readline()
                if 'MODEL_READY' in line:
                    break

        self.progress_signal.emit(0, f"[Whisper] {n_workers} 个 worker 就绪, 开始并行识别...")

        # 分发任务到各 worker 的 stdin（worker 会顺序处理）
        # stdin 格式: url|audio_path，worker 输出时带回 url 避免竞态
        completed = 0
        task_num = 0
        lock = threading.Lock()

        def read_stdout(proc, idx):
            nonlocal completed
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                try:
                    data = json.loads(line.strip())
                    url = data.get('url', '')
                    if url and data.get('ok'):
                        results[url] = data['text']
                    with lock:
                        completed += 1
                        self.progress_signal.emit(int(completed / total * 100),
                            f"已完成 {completed}/{total} 个")
                        if completed % 5 == 0:
                            self._save_progress(results)
                except:
                    pass

        readers = []
        for w in range(n_workers):
            t = threading.Thread(target=read_stdout, args=(workers[w], w), daemon=True)
            t.start()
            readers.append(t)

        for url, audio_path in valid_audio:
            if self.abort:
                break
            w = task_num % n_workers
            abspath = os.path.abspath(audio_path)
            workers[w].stdin.write(f"{url}|{abspath}\n")
            workers[w].stdin.flush()
            task_num += 1

        # 发送 DONE 关闭子进程（先于 reader.join！）
        for proc in workers:
            try:
                proc.stdin.write('DONE\n')
                proc.stdin.flush()
            except:
                pass

        # 等待 reader 线程收集完所有结果
        for reader in readers:
            reader.join(timeout=600)

        # 清理子进程
        for proc in workers:
            try:
                proc.stdin.close()
                proc.wait(timeout=10)
            except:
                proc.kill()

        return results

    def run(self):
        transcriptions = []
        total = len(self.audio_files)

        if USE_WHISPER:
            valid = []
            for url, audio_path in self.audio_files:
                if audio_path and os.path.exists(audio_path) and os.path.getsize(audio_path) >= 1000:
                    valid.append((url, audio_path))

            if valid:
                results = self._transcribe_batch_parallel(valid)
                for url, audio_path in self.audio_files:
                    transcriptions.append((url, results.get(url, "")))
                # 最终保存
                self._save_progress({clean_url(url): text for url, text in transcriptions})
            else:
                for url, _ in self.audio_files:
                    transcriptions.append((url, ""))
        else:
            self.progress_signal.emit(0, "Whisper 已禁用, 使用 Google SpeechRecognition...")
            try:
                import speech_recognition as sr
                r = sr.Recognizer()
                for i, (url, audio_path) in enumerate(self.audio_files):
                    if self.abort:
                        break
                    if not audio_path or not os.path.exists(audio_path):
                        transcriptions.append((url, ""))
                        continue
                    try:
                        with sr.AudioFile(audio_path) as source:
                            audio = r.record(source)
                        text = r.recognize_google(audio, language="zh-CN")
                        transcriptions.append((url, text))
                    except:
                        transcriptions.append((url, ""))
                    self.progress_signal.emit(int((i + 1) / total * 100), f"备选: {i+1}/{total}")
            except:
                for url, _ in self.audio_files:
                    transcriptions.append((url, ""))

        ok = sum(1 for _, t in transcriptions if t)
        self.progress_signal.emit(100, f"识别完成: {ok}/{total} 个有内容")
        self.finished_signal.emit(transcriptions)


# ══════════════════════════════════════════════════════════════════════════════
# AI 服务商预设配置
# ══════════════════════════════════════════════════════════════════════════════

AI_PROVIDERS = {
    "LM Studio (本地)": {
        "url": "http://localhost:1234/v1/chat/completions",
        "models": ["(自行查看 LM Studio 中加载的模型名)"],
        "need_key": False,
        "desc": "本地运行，无需 API Key，隐私安全"
    },
    "Ollama (本地)": {
        "url": "http://localhost:11434/v1/chat/completions",
        "models": ["qwen2.5:7b", "qwen2.5:14b", "llama3.1:8b", "gemma3:12b",
                   "deepseek-r1:7b", "deepseek-r1:14b", "mistral:7b"],
        "need_key": False,
        "desc": "本地运行，一行命令部署，模型丰富 (ollama list 查看)"
    },
    "OpenAI": {
        "url": "https://api.openai.com/v1/chat/completions",
        "models": ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo(旧)"],
        "need_key": True,
        "desc": "云端 API，需申请 API Key (platform.openai.com), 推荐 4.1 系列"
    },
    "DeepSeek": {
        "url": "https://api.deepseek.com/v1/chat/completions",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat(旧)", "deepseek-reasoner(旧)"],
        "need_key": True,
        "desc": "2026.7.24 旧名停用, 请用 v4-flash(快)/v4-pro(推理)"
    },
    "通义千问 (阿里云)": {
        "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "models": ["qwen-plus", "qwen-max", "qwen-turbo", "qwen-long"],
        "need_key": True,
        "desc": "阿里云百炼平台，需申请 API Key (dashscope.console.aliyun.com)"
    },
    "智谱AI (GLM)": {
        "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "models": ["glm-4-flash", "glm-4", "glm-4-plus", "glm-4-long"],
        "need_key": True,
        "desc": "清华智谱，需申请 API Key (open.bigmodel.cn)"
    },
    "Moonshot (Kimi)": {
        "url": "https://api.moonshot.cn/v1/chat/completions",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
        "need_key": True,
        "desc": "月之暗面 Kimi，需申请 API Key (platform.moonshot.cn)"
    },
    "零一万物 (Yi)": {
        "url": "https://api.lingyiwanwu.com/v1/chat/completions",
        "models": ["yi-large", "yi-medium", "yi-lightning", "yi-vision"],
        "need_key": True,
        "desc": "零一万物大模型，需申请 API Key (platform.lingyiwanwu.com)"
    },
    "自定义 (OpenAI兼容)": {
        "url": "http://localhost:11434/v1/chat/completions",
        "models": [],
        "need_key": True,
        "desc": "任意兼容 OpenAI API 格式的服务，手动填入模型名"
    },
}


class CorrectionThread(QThread):
    """AI 文案修正 — 支持系统提示词 + 多条规则（每条独立源列）"""
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(object, dict)

    def __init__(self, df, rules, api_url, model_name, api_key="", system_prompt=""):
        """
        df: 源 DataFrame
        rules: [(名称, 源列, 输出列, 处理指令), ...]
        """
        super().__init__()
        self.df = df.copy()
        self.rules = rules
        self.api_url = api_url
        self.model_name = model_name
        self.api_key = api_key
        self.system_prompt = system_prompt
        self.abort = False

    def run(self):
        total_prompt = 0
        total_completion = 0

        # 确保所有输出列存在
        for _, _, out_col, _ in self.rules:
            if out_col and out_col not in self.df.columns:
                self.df[out_col] = ''

        headers = {"Connection": "keep-alive"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        total = len(self.df)
        for i in range(total):
            if self.abort:
                break

            for rule_name, src_col, out_col, instruction in self.rules:
                if self.abort:
                    break
                if not src_col or not out_col or not instruction:
                    continue
                text = str(self.df.iloc[i][src_col])
                if len(text) < 10:
                    self.progress_signal.emit(int((i + 1) / total * 100), f"跳过第 {i+1} 行 [{rule_name}] (内容太短)")
                    continue

                success = False
                for attempt in range(1, 4):
                    if self.abort:
                        break
                    try:
                        messages = []
                        if self.system_prompt:
                            messages.append({"role": "system", "content": self.system_prompt})
                        messages.append({"role": "user", "content": f"{instruction}\n\n---\n原文案:\n{text}"})

                        payload = {
                            "model": self.model_name,
                            "messages": messages,
                            "temperature": 0.3,
                            "max_tokens": 100000,
                            "stream": False
                        }
                        resp = requests.post(self.api_url, json=payload, timeout=120, headers=headers)
                        if resp.status_code == 200:
                            result = resp.json()
                            output = result['choices'][0]['message']['content'].strip()
                            usage = result.get('usage', {})
                            pt = usage.get('prompt_tokens', 0)
                            ct = usage.get('completion_tokens', 0)

                            self.df.at[i, out_col] = output
                            total_prompt += pt
                            total_completion += ct
                            success = True
                            self.progress_signal.emit(int((i + 1) / total * 100),
                                                      f"第 {i+1} 行 [{rule_name}] 完成")
                            break
                        elif resp.status_code >= 500 and attempt < 3:
                            time.sleep(3 * attempt)
                        else:
                            self.progress_signal.emit(int((i + 1) / total * 100),
                                                      f"第 {i+1} 行 [{rule_name}] HTTP {resp.status_code}")
                            break
                    except requests.exceptions.Timeout:
                        if attempt < 3:
                            self.progress_signal.emit(int((i + 1) / total * 100),
                                f"第 {i+1} 行 [{rule_name}] 超时, 重试 {attempt}/3...")
                            time.sleep(2 * attempt)
                    except requests.exceptions.ConnectionError:
                        if attempt < 3:
                            time.sleep(3 * attempt)
                    except Exception as e:
                        self.progress_signal.emit(int((i + 1) / total * 100),
                                                  f"第 {i+1} 行 [{rule_name}] 异常: {str(e)[:40]}")
                        break
                if not success:
                    self.progress_signal.emit(int((i + 1) / total * 100),
                                              f"第 {i+1} 行 [{rule_name}] 失败(已重试)")

            time.sleep(1)

        stats = {'prompt_tokens': total_prompt, 'completion_tokens': total_completion,
                 'total_tokens': total_prompt + total_completion}
        self.finished_signal.emit(self.df, stats)


# ══════════════════════════════════════════════════════════════════════════════
# 第六部分: Tab1 - 视频信息采集
# ══════════════════════════════════════════════════════════════════════════════

class CollectThread(QThread):
    """在独立线程中完成 Playwright 连接 + 视频采集"""
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(list)

    def __init__(self, debug_port, wait_seconds):
        super().__init__()
        self.debug_port = debug_port
        self.wait_seconds = wait_seconds
        self.abort = False

    def run(self):
        collected = []
        pw = None
        try:
            self.log_signal.emit("=== 开始采集视频数据 ===")
            self.progress_signal.emit(0, "正在连接浏览器...")

            if not PLAYWRIGHT_AVAILABLE:
                self.log_signal.emit("✗ Playwright 未安装")
                self.finished_signal.emit([])
                return

            debugger_url = f"http://localhost:{self.debug_port}/json/version"
            resp = requests.get(debugger_url, timeout=5)
            ws_url = resp.json().get("webSocketDebuggerUrl")
            if not ws_url:
                raise Exception("未获取到 WebSocket URL")

            pw = sync_playwright().start()
            browser = pw.chromium.connect_over_cdp(endpoint_url=ws_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()

            # --- 页面信息诊断 ---
            page_title = page.title()
            page_url = page.url
            # 提取博主名称: "酷盟官方旗舰店的抖音 - 抖音" → "酷盟官方旗舰店"
            blogger_name = page_title
            for suffix in ["的抖音 - 抖音", "的抖音—抖音", "的抖音-抖音"]:
                if suffix in blogger_name:
                    blogger_name = blogger_name.replace(suffix, "").strip()
                    break
            self.log_signal.emit(f"[调试] 当前页面标题: {page_title}")
            self.log_signal.emit(f"[调试] 当前页面 URL: {page_url}")

            # --- 等待用户手动滚动 ---
            self.log_signal.emit(f"请手动在浏览器中滚动加载视频，等待 {self.wait_seconds} 秒后自动提取...")
            for remaining in range(self.wait_seconds, 0, -5):
                if self.abort:
                    self.log_signal.emit("已取消")
                    self.finished_signal.emit([])
                    return
                time.sleep(5)
                self.progress_signal.emit(
                    int((self.wait_seconds - remaining) / self.wait_seconds * 100),
                    f"等待中... {remaining} 秒后开始提取 (可在浏览器中继续滚动)"
                )

            # --- 提取视频 ---
            self.log_signal.emit("正在提取视频数据...")

            # 新版抖音博主主页视频卡片选择器
            video_elements = page.query_selector_all("li.AhHE71Bq")
            self.log_signal.emit(f"[调试] 找到 {len(video_elements)} 个视频卡片 (li.AhHE71Bq)")

            # 备选：如果主选择器没命中，后退到通用 li 匹配
            if not video_elements:
                self.log_signal.emit("[调试] 主选择器未匹配，尝试通用 li 匹配...")
                for li in page.query_selector_all("li"):
                    try:
                        a = li.query_selector("a[href*='/video/']")
                        if a:
                            video_elements.append(li)
                    except:
                        continue
                self.log_signal.emit(f"[调试] 通用匹配找到 {len(video_elements)} 个")

            if not video_elements:
                self.log_signal.emit("✗ 未找到任何视频元素，请确认浏览器中已打开抖音博主主页且页面已加载视频")

            seen_links = set()
            for i, elem in enumerate(video_elements):
                if self.abort:
                    break
                try:
                    # 链接
                    link_el = elem.query_selector("a[href*='/video/']")
                    if not link_el:
                        continue
                    link = link_el.get_attribute("href")
                    if not link:
                        continue
                    if link.startswith("/"):
                        link = f"https://www.douyin.com{link}"

                    if link in seen_links:
                        continue
                    seen_links.add(link)

                    # 封面
                    img_el = elem.query_selector("img")
                    cover = img_el.get_attribute("src") if img_el else "未知"

                    # 短标题
                    title_el = elem.query_selector("p.EB3BkdQ8")
                    title = title_el.text_content().strip() if title_el else "未知"

                    # 完整标题 (frUrWD64 或 img alt 去博主前缀)
                    full_title = title
                    full_el = elem.query_selector("p.frUrWD64")
                    if full_el:
                        full_title = full_el.text_content().strip()
                    elif img_el:
                        alt = img_el.get_attribute("alt") or ""
                        if "：" in alt:
                            full_title = alt.split("：", 1)[1].strip() or title
                        elif ":" in alt:
                            full_title = alt.split(":", 1)[1].strip() or title

                    # 话题标签
                    tags = re.findall(r'#[\w\u4e00-\u9fff-]+', full_title)
                    tags_str = " ".join(tags) if tags else ""

                    # 点赞
                    like_el = elem.query_selector("span.HycZGr_s span.BP1CQkLg")
                    likes = like_el.text_content().strip() if like_el else "0"

                    collected.append({
                        "序号": len(collected) + 1,
                        "博主名称": blogger_name,
                        "博主页面标题": page_title,
                        "博主页面URL": page_url,
                        "视频标题": title[:100],
                        "完整标题": full_title[:200],
                        "话题标签": tags_str,
                        "视频链接": link,
                        "视频封面链接": cover,
                        "点赞数": likes,
                        "是否置顶": "否",
                        "采集时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })

                except Exception as e:
                    self.log_signal.emit(f"[调试] 提取第 {i+1} 个失败: {str(e)[:80]}")
                    continue

            self.progress_signal.emit(100, f"采集完成！共 {len(collected)} 条视频数据")

        except Exception as e:
            import traceback
            self.log_signal.emit(f"采集出错: {str(e)}")
            self.log_signal.emit(f"详细: {traceback.format_exc()}")
        finally:
            if pw:
                try:
                    pw.stop()
                except:
                    pass
            self.finished_signal.emit(collected)


class CollectorTab(QWidget):
    """Tab1: 抖音博主视频信息采集"""
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, str)
    data_ready = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.is_browser_ready = False
        self.collected_data = []
        self.collect_thread = None
        self.debug_port = 9222
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        gb_browser = QGroupBox("浏览器连接")
        gl = QGridLayout(gb_browser)
        gl.addWidget(QLabel("调试端口:"), 0, 0)
        self.port_input = QLineEdit("9222")
        self.port_input.setFixedWidth(80)
        gl.addWidget(self.port_input, 0, 1)
        self.btn_check = QPushButton("检测浏览器")
        self.btn_check.clicked.connect(self._check_browser)
        gl.addWidget(self.btn_check, 0, 2)
        self.lbl_browser_status = QLabel("未检测")
        self.lbl_browser_status.setStyleSheet("color: orange; font-weight: bold;")
        gl.addWidget(self.lbl_browser_status, 0, 3)
        gl.addWidget(QLabel("提示: 先用 msedge.exe --remote-debugging-port=9222 启动浏览器"), 1, 0, 1, 4)
        layout.addWidget(gb_browser)

        gb_collect = QGroupBox("采集设置")
        hl = QHBoxLayout(gb_collect)
        hl.addWidget(QLabel("等待秒数:"))
        self.wait_seconds = QLineEdit("30")
        self.wait_seconds.setFixedWidth(60)
        hl.addWidget(self.wait_seconds)
        hl.addWidget(QLabel("(在此期间请手动在浏览器中滚动加载视频)"))
        self.btn_collect = QPushButton("开始采集视频数据")
        self.btn_collect.clicked.connect(self._start_collect)
        self.btn_collect.setEnabled(False)
        hl.addWidget(self.btn_collect)
        self.btn_stop_collect = QPushButton("停止采集")
        self.btn_stop_collect.clicked.connect(self._stop_collect)
        self.btn_stop_collect.setEnabled(False)
        hl.addWidget(self.btn_stop_collect)
        hl.addStretch()
        layout.addWidget(gb_collect)

        gb_data = QGroupBox("采集数据预览")
        dl = QVBoxLayout(gb_data)
        self.data_count_label = QLabel("已采集: 0 条")
        dl.addWidget(self.data_count_label)
        self.data_preview = QTextEdit()
        self.data_preview.setReadOnly(True)
        self.data_preview.setMaximumHeight(120)
        dl.addWidget(self.data_preview)
        layout.addWidget(gb_data)

        gb_save = QGroupBox("保存与导出")
        sl = QHBoxLayout(gb_save)
        self.btn_save = QPushButton("保存为 Excel")
        self.btn_save.clicked.connect(self._save_excel)
        self.btn_save.setEnabled(False)
        sl.addWidget(self.btn_save)
        self.btn_insert_img = QPushButton("导出 Excel 并嵌入图片")
        self.btn_insert_img.clicked.connect(self._export_with_images)
        self.btn_insert_img.setEnabled(False)
        sl.addWidget(self.btn_insert_img)
        sl.addStretch()
        layout.addWidget(gb_save)

        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(100)
        layout.addWidget(self.log_output)

        self.log_signal.connect(self._append_log)
        self.progress_signal.connect(self._update_progress_bar)

    def _append_log(self, msg):
        self.log_output.append(msg)

    def _update_progress_bar(self, value, msg):
        self.progress_bar.setValue(value)
        self._append_log(msg)

    def _check_browser(self):
        """仅检测调试端口是否可用，不创建 Playwright 对象"""
        try:
            port = int(self.port_input.text())
            resp = requests.get(f"http://localhost:{port}/json/version", timeout=5)
            data = resp.json()
            if data.get("webSocketDebuggerUrl"):
                self.debug_port = port
                self.is_browser_ready = True
                self.lbl_browser_status.setText("可用")
                self.lbl_browser_status.setStyleSheet("color: green; font-weight: bold;")
                self.btn_collect.setEnabled(True)
                self.log_signal.emit("✓ 浏览器调试端口可用！请在浏览器中导航到博主主页，然后点击'开始采集'")
            else:
                raise Exception("未获取到 WebSocket URL")
        except Exception as e:
            self.is_browser_ready = False
            self.lbl_browser_status.setText("不可用")
            self.lbl_browser_status.setStyleSheet("color: red; font-weight: bold;")
            self.btn_collect.setEnabled(False)
            self.log_signal.emit(f"✗ 无法连接浏览器: {str(e)[:80]}")

    def _start_collect(self):
        if not self.is_browser_ready:
            QMessageBox.warning(self, "提示", "请先检测浏览器端口是否可用")
            return
        try:
            wait_sec = int(self.wait_seconds.text())
        except:
            QMessageBox.warning(self, "提示", "请输入有效的等待秒数")
            return

        self.btn_collect.setEnabled(False)
        self.btn_stop_collect.setEnabled(True)
        self.collected_data = []

        self.collect_thread = CollectThread(self.debug_port, wait_sec)
        self.collect_thread.log_signal.connect(self.log_signal)
        self.collect_thread.progress_signal.connect(self.progress_signal)
        self.collect_thread.finished_signal.connect(self._on_collect_finished)
        self.collect_thread.start()

    def _on_collect_finished(self, data):
        self.collected_data = data
        self._update_data_preview()
        self.btn_save.setEnabled(bool(data))
        self.btn_insert_img.setEnabled(bool(data))
        self.btn_collect.setEnabled(True)
        self.btn_stop_collect.setEnabled(False)

    def _stop_collect(self):
        if self.collect_thread:
            self.collect_thread.abort = True
        self.log_signal.emit("已停止采集")
        self.btn_collect.setEnabled(True)
        self.btn_stop_collect.setEnabled(False)

    def _update_data_preview(self):
        self.data_count_label.setText(f"已采集: {len(self.collected_data)} 条")
        preview_lines = []
        for item in self.collected_data[:10]:
            tags = item.get('话题标签', '')
            preview_lines.append(f"[{item['序号']}] {item['视频标题'][:30]} | 赞:{item['点赞数']} | {tags}")
        if len(self.collected_data) > 10:
            preview_lines.append(f"... 共 {len(self.collected_data)} 条")
        self.data_preview.setText("\n".join(preview_lines))

    def _save_excel(self):
        if not self.collected_data:
            QMessageBox.warning(self, "提示", "没有可保存的数据")
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存 Excel", f"抖音视频数据_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                                              "Excel (*.xlsx)")
        if path:
            df = pd.DataFrame(self.collected_data)
            df.to_excel(path, index=False)
            self.log_signal.emit(f"✓ 数据已保存到: {path}")
            self.data_ready.emit(path)  # 通知 Tab2
            QMessageBox.information(self, "成功", f"已保存 {len(self.collected_data)} 条数据")

    def _export_with_images(self):
        if not self.collected_data:
            QMessageBox.warning(self, "提示", "没有可保存的数据")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出带图片 Excel",
                                              f"抖音视频数据_带图片_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                                              "Excel (*.xlsx)")
        if not path:
            return
        try:
            from openpyxl import Workbook, load_workbook
            from openpyxl.drawing.image import Image

            df = pd.DataFrame(self.collected_data)
            if "视频封面" not in df.columns:
                idx = df.columns.get_loc("视频封面链接")
                df.insert(idx + 1, "视频封面", "")
            df.to_excel(path, index=False, engine='openpyxl')

            wb = load_workbook(path)
            ws = wb.active
            img_link_col = df.columns.get_loc("视频封面链接") + 1
            img_col = img_link_col + 1
            ws.column_dimensions[chr(64 + img_col)].width = 15

            headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.douyin.com/'}
            success = 0
            for row_idx in range(len(df)):
                img_url = df.iloc[row_idx]["视频封面链接"]
                if not str(img_url).startswith("http"):
                    continue
                try:
                    resp = requests.get(img_url, headers=headers, timeout=15, stream=True)
                    resp.raise_for_status()
                    buf = BytesIO()
                    for chunk in resp.iter_content(8192):
                        buf.write(chunk)
                    buf.seek(0)
                    img = Image(buf)
                    img.width = 100
                    img.height = int(img.height * (100 / img.width))
                    ws.row_dimensions[row_idx + 2].height = max(img.height - 10, 20)
                    ws.add_image(img, f"{chr(64 + img_col)}{row_idx + 2}")
                    success += 1
                except:
                    continue
            wb.save(path)
            wb.close()
            self.log_signal.emit(f"✓ 导出完成（嵌入 {success} 张图片）: {path}")
            QMessageBox.information(self, "成功", f"已导出并嵌入 {success} 张图片")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {str(e)}")


# ══════════════════════════════════════════════════════════════════════════════
# 第七部分: Tab2 - 视频下载+音频提取+语音转文字
# ══════════════════════════════════════════════════════════════════════════════

class ExtractorTab(QWidget):
    """Tab2: 视频下载 → 音频提取 → 语音转文字"""
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, str)
    data_ready = pyqtSignal(str)  # 输出文件路径，供 Tab3 自动加载

    def __init__(self):
        super().__init__()
        self.temp_dir = None
        self.download_thread = None
        self.extract_thread = None
        self.transcribe_thread = None
        self.is_running = False
        self._init_ui()
        self.log_signal.connect(self._append_log)
        self.progress_signal.connect(self._update_progress)

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # 模式选择
        gb_mode = QGroupBox("下载模式")
        ml = QHBoxLayout(gb_mode)
        ml.addWidget(QLabel("模式:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["浏览器下载（推荐）", "本地视频模式", "yt-dlp 在线下载"])
        ml.addWidget(self.mode_combo)
        ml.addStretch()
        layout.addWidget(gb_mode)

        # 输入文件
        gb_input = QGroupBox("输入")
        gl = QGridLayout(gb_input)
        gl.addWidget(QLabel("表格文件:"), 0, 0)
        self.file_path = QLineEdit()
        self.file_path.setReadOnly(True)
        gl.addWidget(self.file_path, 0, 1)
        btn_browse = QPushButton("浏览")
        btn_browse.clicked.connect(self._browse_file)
        gl.addWidget(btn_browse, 0, 2)

        gl.addWidget(QLabel("本地视频文件夹:"), 1, 0)
        self.local_path = QLineEdit()
        self.local_path.setReadOnly(True)
        gl.addWidget(self.local_path, 1, 1)
        btn_local = QPushButton("选择")
        btn_local.clicked.connect(self._browse_local)
        gl.addWidget(btn_local, 1, 2)

        gl.addWidget(QLabel("视频保存路径:"), 2, 0)
        self.video_save = QLineEdit()
        self.video_save.setReadOnly(True)
        gl.addWidget(self.video_save, 2, 1)
        btn_vsave = QPushButton("选择")
        btn_vsave.clicked.connect(self._browse_video_save)
        gl.addWidget(btn_vsave, 2, 2)

        gl.addWidget(QLabel("结果保存路径:"), 3, 0)
        self.save_path = QLineEdit()
        self.save_path.setReadOnly(True)
        gl.addWidget(self.save_path, 3, 1)
        btn_save = QPushButton("选择")
        btn_save.clicked.connect(self._browse_save)
        gl.addWidget(btn_save, 3, 2)
        layout.addWidget(gb_input)

        # 控制按钮
        hl = QHBoxLayout()
        self.btn_start = QPushButton("▶ 开始处理")
        self.btn_start.clicked.connect(self._start_processing)
        hl.addWidget(self.btn_start)
        self.btn_stop = QPushButton("⏹ 停止")
        self.btn_stop.clicked.connect(self._stop_processing)
        self.btn_stop.setEnabled(False)
        hl.addWidget(self.btn_stop)
        layout.addLayout(hl)

        # 进度和日志
        self.progress_bar2 = QProgressBar()
        layout.addWidget(self.progress_bar2)
        self.log_output2 = QTextEdit()
        self.log_output2.setReadOnly(True)
        self.log_output2.setMaximumHeight(120)
        layout.addWidget(self.log_output2)

        layout.addStretch()

    def _append_log(self, msg):
        self.log_output2.append(msg)

    def _update_progress(self, value, msg):
        self.progress_bar2.setValue(value)
        self.log_output2.append(msg)

    def _browse_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择表格文件", "", "Excel/CSV (*.xlsx *.xls *.csv)")
        if p:
            self.file_path.setText(p)
            base = os.path.splitext(p)[0]
            self.save_path.setText(f"{base}_已处理.xlsx")

    def _browse_local(self):
        d = QFileDialog.getExistingDirectory(self, "选择本地视频文件夹")
        if d:
            self.local_path.setText(d)

    def _browse_video_save(self):
        d = QFileDialog.getExistingDirectory(self, "选择视频保存路径")
        if d:
            self.video_save.setText(d)

    def _browse_save(self):
        p, _ = QFileDialog.getSaveFileName(self, "选择保存路径", "", "Excel (*.xlsx)")
        if p:
            self.save_path.setText(p)

    def _start_processing(self):
        file_path = self.file_path.text()
        if not file_path:
            QMessageBox.warning(self, "警告", "请选择表格文件")
            return
        if not self.save_path.text():
            QMessageBox.warning(self, "警告", "请选择结果保存路径")
            return

        try:
            if file_path.endswith('.csv'):
                df = pd.read_csv(file_path)
            else:
                df = pd.read_excel(file_path)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"读取文件失败: {e}")
            return

        col = find_video_url_column(df)
        if not col:
            QMessageBox.critical(self, "错误", "未找到视频链接列")
            return

        video_urls = [clean_url(u) for u in df[col].dropna().tolist()]
        video_urls = [u for u in video_urls if is_video_page_url(u)]
        if not video_urls:
            QMessageBox.critical(self, "错误", "没有有效的视频页面链接（已排除封面图片链接）")
            return

        # 断点续传：跳过已有文案的视频
        skipped = 0
        if '视频文案' in df.columns:
            col_idx = list(df.columns).index(col)
            done_urls = set()
            for i, url in enumerate(df[col]):
                if pd.notna(url):
                    cleaned = clean_url(url)
                    existing = str(df.at[i, '视频文案'])
                    if existing and existing != 'nan' and len(existing) > 5:
                        done_urls.add(cleaned)
            video_urls = [u for u in video_urls if u not in done_urls]
            skipped = len(done_urls)
            if skipped > 0:
                self.log_signal.emit(f"断点续传: 跳过已完成的 {skipped} 个视频")

        self.log_signal.emit(f"找到 {len(video_urls)} 个有效视频链接:")
        for i, u in enumerate(video_urls[:5]):
            self.log_signal.emit(f"  [{i+1}] {u[:80]}")
        if len(video_urls) > 5:
            self.log_signal.emit(f"  ... 共 {len(video_urls)} 个")
        self.is_running = True
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

        self.temp_dir = tempfile.mkdtemp()
        video_save_dir = self.video_save.text() or self.temp_dir
        if video_save_dir != self.temp_dir:
            os.makedirs(video_save_dir, exist_ok=True)

        mode = self.mode_combo.currentIndex()
        if mode == 1:  # 本地模式
            self._process_local(video_urls)
        else:
            self.download_thread = BrowserDownloadThread(video_urls, self.temp_dir, video_save_dir)
            self.download_thread.progress_signal.connect(self.progress_signal)
            self.download_thread.finished_signal.connect(self._on_download_done)
            self.download_thread.start()

    def _process_local(self, video_urls):
        folder = self.local_path.text()
        if not folder or not os.path.exists(folder):
            self.log_signal.emit("请先选择本地视频文件夹")
            self._reset_state()
            return

        local_videos = {}
        for f in os.listdir(folder):
            if f.endswith(('.mp4', '.flv', '.avi', '.mov', '.mkv')):
                local_videos[os.path.splitext(f)[0]] = os.path.join(folder, f)

        video_files = []
        for i, url in enumerate(video_urls):
            vid = url.split('/')[-1]
            found = None
            for name, path in local_videos.items():
                if vid in name or name in url:
                    found = path
                    break
            video_files.append((url, found))
            self.log_signal.emit(f"视频 {i+1}: {'找到' if found else '未找到'}")

        self._on_download_done(video_files)

    def _on_download_done(self, downloaded):
        if not self.is_running:
            return
        self.log_signal.emit(f"下载完成，{sum(1 for _, p in downloaded if p)} 个成功")
        self.extract_thread = ExtractAudioThread(downloaded, self.temp_dir)
        self.extract_thread.progress_signal.connect(self.progress_signal)
        self.extract_thread.finished_signal.connect(self._on_extract_done)
        self.extract_thread.start()

    def _on_extract_done(self, audio_files):
        if not self.is_running:
            return
        # 统计音频提取结果
        ok_count = sum(1 for _, p in audio_files if p and os.path.exists(p))
        self.log_signal.emit(f"音频提取完成: {ok_count}/{len(audio_files)} 个成功")
        print(f"[ExtractorTab] 音频提取完成: {ok_count}/{len(audio_files)} 成功")

        # 打印前 3 个音频路径
        for idx, (url, ap) in enumerate(audio_files[:3]):
            if ap:
                print(f"[ExtractorTab] 音频[{idx}]: {ap} (存在={os.path.exists(ap)}, 大小={os.path.getsize(ap) if os.path.exists(ap) else 'N/A'})")
            else:
                print(f"[ExtractorTab] 音频[{idx}]: None")

        self.log_signal.emit("开始语音识别...")
        print("[ExtractorTab] 启动 TranscribeThread...")
        inp = self.file_path.text()
        outp = self.save_path.text()
        self.transcribe_thread = TranscribeThread(audio_files, input_file=inp, save_file=outp)
        self.transcribe_thread.progress_signal.connect(self.progress_signal)
        self.transcribe_thread.finished_signal.connect(self._on_transcribe_done)
        self.transcribe_thread.start()

    def _on_transcribe_done(self, transcriptions):
        if not self.is_running:
            return
        # 统计
        ok = sum(1 for _, t in transcriptions if t)
        print(f"[ExtractorTab] 转录完成: {ok}/{len(transcriptions)} 个有内容")
        self.log_signal.emit(f"[调试] 转录完成: {ok}/{len(transcriptions)} 个有内容")
        # 打印前 3 条转录结果
        for idx, (url, t) in enumerate(transcriptions[:3]):
            print(f"[ExtractorTab] 转录[{idx}]: url={url[:50] if url else 'None'}, text={str(t)[:50]}")
        try:
            file_path = self.file_path.text()
            df = pd.read_csv(file_path) if file_path.endswith('.csv') else pd.read_excel(file_path)
            col = find_video_url_column(df)

            t_map = {url: text for url, text in transcriptions}
            if '视频文案' not in df.columns:
                df['视频文案'] = ''

            for i, url in enumerate(df[col]):
                if pd.notna(url):
                    cleaned = clean_url(url)
                    if cleaned in t_map:
                        df.at[i, '视频文案'] = t_map[cleaned]

            save_p = self.save_path.text()
            if save_p.endswith('.csv'):
                df.to_csv(save_p, index=False, encoding='utf-8-sig')
            else:
                df.to_excel(save_p, index=False)

            self.log_signal.emit(f"✓ 处理完成！结果保存至: {save_p}")
            self.data_ready.emit(save_p)  # 通知 Tab3
            QMessageBox.information(self, "成功", "处理完成！结果已保存")
        except Exception as e:
            self.log_signal.emit(f"保存失败: {e}")
            QMessageBox.critical(self, "错误", f"保存失败: {e}")
        finally:
            self._cleanup()
            self._reset_state()

    def _stop_processing(self):
        self.is_running = False
        for t in [self.download_thread, self.extract_thread, self.transcribe_thread]:
            if t:
                t.abort = True
                t.wait()
        self._cleanup()
        self._reset_state()
        self.log_signal.emit("已停止")

    def _cleanup(self):
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
            except:
                pass

    def _reset_state(self):
        self.is_running = False
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar2.setValue(0)

    def load_file_from(self, path):
        """供外部调用，自动加载文件"""
        self.file_path.setText(path)
        base = os.path.splitext(path)[0]
        self.save_path.setText(f"{base}_已处理.xlsx")


# ══════════════════════════════════════════════════════════════════════════════
# 第八部分: Tab3 - AI 文案修正
# ══════════════════════════════════════════════════════════════════════════════

class CorrectorTab(QWidget):
    """Tab3: AI 文案修正 — 支持系统提示词 + 多条处理规则"""
    log_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.df = None
        self.correct_thread = None
        self._init_ui()
        self._update_provider_ui()
        self.log_signal.connect(self._log)

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # ── AI 服务商配置 ──
        gb_api = QGroupBox("AI 服务商配置")
        gl = QGridLayout(gb_api)
        gl.addWidget(QLabel("服务商:"), 0, 0)
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(list(AI_PROVIDERS.keys()))
        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)
        gl.addWidget(self.provider_combo, 0, 1, 1, 3)
        self.provider_desc = QLabel("")
        self.provider_desc.setStyleSheet("color: gray; font-size: 11px;")
        gl.addWidget(self.provider_desc, 1, 0, 1, 4)
        gl.addWidget(QLabel("API 地址:"), 2, 0)
        self.api_url = QLineEdit()
        gl.addWidget(self.api_url, 2, 1, 1, 3)
        gl.addWidget(QLabel("API Key:"), 3, 0)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("本地模型无需填写")
        gl.addWidget(self.api_key, 3, 1)
        self.btn_toggle_key = QPushButton("👁")
        self.btn_toggle_key.setFixedWidth(30)
        self.btn_toggle_key.clicked.connect(self._toggle_key_visibility)
        gl.addWidget(self.btn_toggle_key, 3, 2)
        gl.addWidget(QLabel("模型名称:"), 3, 3)
        self.model_name = QComboBox()
        self.model_name.setEditable(True)
        self.model_name.setMinimumWidth(180)
        gl.addWidget(self.model_name, 4, 0, 1, 3)
        self.btn_test = QPushButton("测试连接")
        self.btn_test.clicked.connect(self._test_connection)
        gl.addWidget(self.btn_test, 4, 3)
        layout.addWidget(gb_api)

        # ── 系统提示词 ──
        gb_sys = QGroupBox("系统提示词（定义 AI 的角色和行为，选填）")
        sl_sys = QVBoxLayout(gb_sys)
        self.system_prompt = QTextEdit()
        self.system_prompt.setMinimumHeight(60)
        self.system_prompt.setMaximumHeight(120)
        self.system_prompt.setPlaceholderText("例：你是一个专业的中文文案编辑。请修正错别字、优化语法、使表达更流畅自然。只返回修正后的文案，不要解释。")
        sl_sys.addWidget(self.system_prompt)
        layout.addWidget(gb_sys)

        # ── 处理规则 ──
        gb_rules = QGroupBox("处理规则（每条规则独立指定源列和输出列）")
        rules_layout = QVBoxLayout(gb_rules)

        # 规则表格: 规则名称 | 源列 | 输出列名 | 处理指令
        self.rules_table = QTableWidget(0, 4)
        self.rules_table.setHorizontalHeaderLabels(["规则名称", "源列", "输出列名", "处理指令"])
        self.rules_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.rules_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.rules_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.rules_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.rules_table.setMinimumHeight(200)
        self.rules_table.setMaximumHeight(16777215)
        rules_layout.addWidget(self.rules_table)

        # 规则操作按钮
        hl_rules = QHBoxLayout()
        btn_add = QPushButton("+ 添加规则")
        btn_add.clicked.connect(self._add_rule)
        hl_rules.addWidget(btn_add)
        btn_remove = QPushButton("- 删除选中")
        btn_remove.clicked.connect(self._del_rule)
        hl_rules.addWidget(btn_remove)
        hl_rules.addStretch()
        rules_layout.addLayout(hl_rules)

        layout.addWidget(gb_rules)

        # ── 操作按钮 ──
        hl_btns = QHBoxLayout()
        self.btn_batch = QPushButton("▶ 批量处理全部")
        self.btn_batch.clicked.connect(self._batch_correct)
        self.btn_batch.setStyleSheet("font-weight: bold;")
        hl_btns.addWidget(self.btn_batch)
        btn_open = QPushButton("打开表格")
        btn_open.clicked.connect(self._load_file)
        hl_btns.addWidget(btn_open)
        btn_save = QPushButton("保存表格")
        btn_save.clicked.connect(self._save_file)
        hl_btns.addWidget(btn_save)
        btn_save_cfg = QPushButton("保存配置")
        btn_save_cfg.clicked.connect(self._save_config)
        hl_btns.addWidget(btn_save_cfg)
        btn_load_cfg = QPushButton("加载配置")
        btn_load_cfg.clicked.connect(self._load_config)
        hl_btns.addWidget(btn_load_cfg)
        self.file_label = QLabel("未加载文件")
        hl_btns.addWidget(self.file_label)
        hl_btns.addStretch()
        self.token_label = QLabel("总Token: 0")
        hl_btns.addWidget(self.token_label)
        layout.addLayout(hl_btns)

        # ── 进度与状态 ──
        self.progress_bar3 = QProgressBar()
        layout.addWidget(self.progress_bar3)
        self.status_label = QLabel("就绪 - 打开表格, 配置规则, 点击批量处理")
        layout.addWidget(self.status_label)

        layout.addStretch()

        # 默认添加一条规则
        self._add_rule("错别字修正", "视频文案", "修正后文案",
                       "请修正以下文案中的错别字和语法错误，只返回修正后的文案，不要解释。")

    # ═══════════════════════════════════════════════════════════
    # 规则管理
    # ═══════════════════════════════════════════════════════════

    def _add_rule(self, name="", src_col="", out_col="", instruction=""):
        row = self.rules_table.rowCount()
        self.rules_table.insertRow(row)
        self.rules_table.setItem(row, 0, QTableWidgetItem(name))
        self.rules_table.setItem(row, 1, QTableWidgetItem(src_col))
        self.rules_table.setItem(row, 2, QTableWidgetItem(out_col))
        self.rules_table.setItem(row, 3, QTableWidgetItem(instruction))

    def _del_rule(self):
        rows = set()
        for item in self.rules_table.selectedItems():
            rows.add(item.row())
        for row in sorted(rows, reverse=True):
            self.rules_table.removeRow(row)

    def _get_rules(self):
        """从表格读取所有规则: (名称, 源列, 输出列, 处理指令)"""
        rules = []
        for row in range(self.rules_table.rowCount()):
            name = self.rules_table.item(row, 0).text().strip() if self.rules_table.item(row, 0) else ""
            src_col = self.rules_table.item(row, 1).text().strip() if self.rules_table.item(row, 1) else ""
            out_col = self.rules_table.item(row, 2).text().strip() if self.rules_table.item(row, 2) else ""
            inst = self.rules_table.item(row, 3).text().strip() if self.rules_table.item(row, 3) else ""
            if src_col and out_col and inst:
                rules.append((name or out_col, src_col, out_col, inst))
        return rules

    def _save_config(self):
        """保存当前配置（服务商、模型、系统提示词、规则）到 JSON 文件"""
        data = {
            "provider": self.provider_combo.currentText(),
            "api_url": self.api_url.text().strip(),
            "api_key": self.api_key.text().strip(),
            "model_name": self.model_name.currentText().strip(),
            "system_prompt": self.system_prompt.toPlainText(),
            "rules": []
        }
        for row in range(self.rules_table.rowCount()):
            name = self.rules_table.item(row, 0).text().strip() if self.rules_table.item(row, 0) else ""
            src_col = self.rules_table.item(row, 1).text().strip() if self.rules_table.item(row, 1) else ""
            out_col = self.rules_table.item(row, 2).text().strip() if self.rules_table.item(row, 2) else ""
            inst = self.rules_table.item(row, 3).text().strip() if self.rules_table.item(row, 3) else ""
            data["rules"].append({"name": name, "source_col": src_col, "output_col": out_col, "instruction": inst})

        path, _ = QFileDialog.getSaveFileName(self, "保存配置", "ai_config.json", "JSON (*.json)")
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                self.log_signal.emit(f"✓ 配置已保存: {os.path.basename(path)}")
                QMessageBox.information(self, "成功", f"配置已保存到:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def _load_config(self):
        """从 JSON 文件加载配置"""
        path, _ = QFileDialog.getOpenFileName(self, "加载配置", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 恢复服务商
            provider = data.get("provider", "")
            if provider in [self.provider_combo.itemText(i) for i in range(self.provider_combo.count())]:
                self.provider_combo.setCurrentText(provider)
            self.api_url.setText(data.get("api_url", ""))
            self.api_key.setText(data.get("api_key", ""))
            self.model_name.setCurrentText(data.get("model_name", ""))
            self.system_prompt.setText(data.get("system_prompt", ""))

            # 恢复规则
            self.rules_table.setRowCount(0)
            for rule in data.get("rules", []):
                self._add_rule(
                    rule.get("name", ""),
                    rule.get("source_col", ""),
                    rule.get("output_col", ""),
                    rule.get("instruction", "")
                )

            self.log_signal.emit(f"✓ 配置已加载: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载失败: {e}")

    # ═══════════════════════════════════════════════════════════
    # 服务商相关
    # ═══════════════════════════════════════════════════════════

    def _log(self, msg):
        self.status_label.setText(msg)

    def _on_provider_changed(self, name):
        self._update_provider_ui()

    def _update_provider_ui(self):
        name = self.provider_combo.currentText()
        cfg = AI_PROVIDERS.get(name, {})
        self.api_url.setText(cfg.get("url", ""))
        self.provider_desc.setText(cfg.get("desc", ""))
        # 填充模型下拉
        self.model_name.clear()
        models = cfg.get("models", [])
        self.model_name.addItems(models)
        if models:
            self.model_name.setCurrentIndex(0)
        need_key = cfg.get("need_key", True)
        self.api_key.setEnabled(need_key)
        self.btn_toggle_key.setEnabled(need_key)
        if not need_key:
            self.api_key.setText("")
            self.api_key.setPlaceholderText("本地模型无需 API Key")
        else:
            self.api_key.setPlaceholderText("请输入 API Key")

    def _toggle_key_visibility(self):
        if self.api_key.echoMode() == QLineEdit.Password:
            self.api_key.setEchoMode(QLineEdit.Normal)
            self.btn_toggle_key.setText("🔒")
        else:
            self.api_key.setEchoMode(QLineEdit.Password)
            self.btn_toggle_key.setText("👁")

    def _test_connection(self):
        url = self.api_url.text().strip()
        key = self.api_key.text().strip()
        model = self.model_name.currentText().strip()
        if not url:
            QMessageBox.warning(self, "提示", "请先填写 API 地址")
            return
        headers = {"Connection": "keep-alive"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        self.log_signal.emit("正在测试连接...")
        self.btn_test.setEnabled(False)

        def run():
            try:
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": "你好，请回复'连接成功'"}],
                    "max_tokens": 20, "stream": False
                }
                resp = requests.post(url, json=payload, timeout=15, headers=headers)
                if resp.status_code == 200:
                    reply = resp.json()['choices'][0]['message']['content'].strip()
                    self.log_signal.emit(f"✓ 连接成功！回复: {reply[:40]}")
                    QMessageBox.information(self, "测试通过", f"API 连接正常！\n模型回复: {reply[:50]}")
                else:
                    self.log_signal.emit(f"✗ HTTP {resp.status_code}: {resp.text[:100]}")
                    QMessageBox.warning(self, "连接失败", f"HTTP {resp.status_code}\n{resp.text[:200]}")
            except Exception as e:
                self.log_signal.emit(f"✗ 连接失败: {str(e)[:80]}")
                QMessageBox.critical(self, "连接失败", str(e))
            finally:
                self.btn_test.setEnabled(True)
        threading.Thread(target=run, daemon=True).start()

    # ═══════════════════════════════════════════════════════════
    # 文件操作与显示
    # ═══════════════════════════════════════════════════════════

    def _load_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "打开表格", "", "Excel/CSV (*.xlsx *.xls *.csv)")
        if not p:
            return
        try:
            self.df = pd.read_csv(p, encoding='utf-8') if p.endswith('.csv') else pd.read_excel(p)
            self.file_label.setText(f"已加载: {os.path.basename(p)} ({len(self.df)} 行)")
            self.log_signal.emit(f"✓ 加载 {len(self.df)} 行, 列: {', '.join(self.df.columns)}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载失败: {e}")

    def _save_file(self):
        if self.df is None:
            return
        p, _ = QFileDialog.getSaveFileName(self, "保存表格", "", "Excel (*.xlsx);;CSV (*.csv)")
        if p:
            try:
                if p.endswith('.csv'):
                    self.df.to_csv(p, index=False, encoding='utf-8-sig')
                else:
                    self.df.to_excel(p, index=False)
                self.log_signal.emit(f"✓ 已保存: {p}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存失败: {e}")

    # ═══════════════════════════════════════════════════════════
    # 批量处理
    # ═══════════════════════════════════════════════════════════

    def _batch_correct(self):
        if self.df is None:
            QMessageBox.warning(self, "提示", "请先打开表格文件")
            return
        rules = self._get_rules()
        if not rules:
            QMessageBox.warning(self, "提示", "请至少添加一条处理规则")
            return
        # 验证所有源列存在
        for name, src_col, out_col, inst in rules:
            if src_col not in self.df.columns:
                QMessageBox.warning(self, "提示", f"规则 [{name}] 的源列 '{src_col}' 不在表格中\n可用列: {list(self.df.columns)}")
                return

        rule_desc = ", ".join([f"{n}: {s}→{o}" for n, s, o, _ in rules])
        if not QMessageBox.question(self, "确认",
                                    f"将对 {len(self.df)} 行执行 {len(rules)} 条规则:\n{rule_desc}\n\n是否继续?"):
            return

        self.btn_batch.setEnabled(False)
        sys_prompt = self.system_prompt.toPlainText().strip()

        self.correct_thread = CorrectionThread(
            self.df, rules,
            self.api_url.text(), self.model_name.currentText(),
            self.api_key.text().strip(), sys_prompt
        )
        self.correct_thread.progress_signal.connect(self._on_batch_progress)
        self.correct_thread.finished_signal.connect(self._on_batch_done)
        self.correct_thread.start()

    def _on_batch_progress(self, value, msg):
        self.progress_bar3.setValue(value)
        self.log_signal.emit(msg)

    def _on_batch_done(self, df, stats):
        self.df = df
        self.btn_batch.setEnabled(True)
        self.progress_bar3.setValue(100)
        self.token_label.setText(f"总Token: {stats['total_tokens']}")
        self.log_signal.emit(f"✓ 处理完成！总消耗 {stats['total_tokens']} tokens。请保存文件。")
        QMessageBox.information(self, "完成", f"批量处理完成！\n总消耗: {stats['total_tokens']} tokens\n请检查结果并保存文件。")

    def load_file_from(self, path):
        """供外部调用，自动加载文件"""
        try:
            self.df = pd.read_csv(path, encoding='utf-8') if path.endswith('.csv') else pd.read_excel(path)
            self.file_label.setText(f"已加载: {os.path.basename(path)} ({len(self.df)} 行)")
            self.log_signal.emit(f"✓ 自动加载 {len(self.df)} 行")
        except Exception as e:
            self.log_signal.emit(f"自动加载失败: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# 第九部分: 主窗口
# ══════════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("抖音视频文案处理一体化工具 v2.0")
        self.setGeometry(50, 50, 1100, 750)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        # 三个标签页
        self.tab1 = CollectorTab()
        self.tab2 = ExtractorTab()
        self.tab3 = CorrectorTab()

        self.tabs.addTab(self.tab1, "① 视频信息采集")
        self.tabs.addTab(self.tab2, "② 文案提取(下载+识别)")
        self.tabs.addTab(self.tab3, "③ AI文案修正")

        # 数据流转: Tab1 → Tab2, Tab2 → Tab3
        self.tab1.data_ready.connect(self._on_tab1_output)
        self.tab2.data_ready.connect(self._on_tab2_output)

        # 状态栏
        self.statusBar().showMessage(
            "就绪 | 步骤: ①采集视频链接 → ②下载视频并转为文字 → ③AI修正文案 | "
            f"Playwright: {'可用' if PLAYWRIGHT_AVAILABLE else '不可用'} | "
            "Whisper: 使用时加载"
        )

    def _on_tab1_output(self, path):
        """Tab1 输出文件后，自动切换到 Tab2 并加载"""
        if QMessageBox.question(self, "自动流转",
                                f"视频采集已完成！\n是否切换到「文案提取」标签页并自动加载文件？") == QMessageBox.Yes:
            self.tab2.load_file_from(path)
            self.tabs.setCurrentIndex(1)

    def _on_tab2_output(self, path):
        """Tab2 输出文件后，自动切换到 Tab3 并加载"""
        if QMessageBox.question(self, "自动流转",
                                f"文案提取已完成！\n是否切换到「AI文案修正」标签页并自动加载文件？") == QMessageBox.Yes:
            self.tab3.load_file_from(path)
            self.tabs.setCurrentIndex(2)


# ══════════════════════════════════════════════════════════════════════════════
# 第十部分: 入口
# ══════════════════════════════════════════════════════════════════════════════

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
