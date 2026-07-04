import sys
import os
import json
import subprocess
import threading
import tempfile
import shutil
import time

# 最先导入whisper，避免DLL冲突
try:
    import whisper
    WHISPER_AVAILABLE = True
    print("✓ OpenAI Whisper导入成功")
except Exception as e:
    WHISPER_AVAILABLE = False
    print(f"✗ Whisper导入失败: {e}，将使用SpeechRecognition作为备选方案")

# 在导入whisper后立即修复ffmpeg路径问题
if WHISPER_AVAILABLE:
    try:
        import imageio_ffmpeg
        _whisper_ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        if os.path.exists(_whisper_ffmpeg_path):
            # Monkey-patch whisper的load_audio函数以使用正确的ffmpeg路径
            original_load_audio = None
            try:
                from whisper import audio as _whisper_audio
                original_load_audio = _whisper_audio.load_audio
                
                def patched_load_audio(audio_file: str, sr: int = 16000):
                    """使用完整的ffmpeg路径加载音频文件"""
                    import numpy as np
                    import tempfile
                    
                    cmd = [
                        _whisper_ffmpeg_path,
                        '-nostdin',
                        '-threads', '0',
                        '-i', audio_file,
                        '-f', 's16le',
                        '-ac', '1',
                        '-acodec', 'pcm_s16le',
                        '-ar', str(sr),
                        '-'
                    ]
                    
                    out = subprocess.run(cmd, capture_output=True, check=True).stdout
                    data = np.frombuffer(out, np.int16).flatten().astype(np.float32) / 32768.0
                    return data
                
                _whisper_audio.load_audio = patched_load_audio
                print(f"✓ 已修复whisper的ffmpeg路径: {_whisper_ffmpeg_path}")
            except Exception as e:
                print(f"✗ 修复whisper ffmpeg路径失败: {e}")
        else:
            print(f"✗ ffmpeg不存在: {_whisper_ffmpeg_path}")
    except Exception as e:
        print(f"✗ 获取ffmpeg路径失败: {e}")

import requests
from PyQt5.QtWidgets import QApplication, QMainWindow, QPushButton, QFileDialog, QProgressBar, QTextEdit, QLabel, QVBoxLayout, QHBoxLayout, QWidget, QLineEdit, QMessageBox, QComboBox
from PyQt5.QtCore import Qt, QThread, pyqtSignal
import pandas as pd
import ffmpeg
import yt_dlp

# 配置：是否使用Whisper模型（默认启用）
USE_WHISPER = True

# 配置：Whisper模型名称
WHISPER_MODEL_SIZE = "large-v3-turbo"  # 可选: tiny, base, small, medium, large, large-v3-turbo

# 导入 imageio_ffmpeg
try:
    import imageio_ffmpeg
    FFMPEG_AVAILABLE = True
    FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG_AVAILABLE = False
    FFMPEG_EXE = None
    print("imageio_ffmpeg 未安装，正在安装...")
    try:
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'imageio_ffmpeg'], check=True)
        import imageio_ffmpeg
        FFMPEG_AVAILABLE = True
        FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
        print("imageio_ffmpeg 安装成功！")
    except:
        print("imageio_ffmpeg 安装失败")

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("Playwright未安装，将使用备用下载方式")

class BrowserDownloadThread(QThread):
    """使用Playwright通过浏览器下载视频"""
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(list)

    def __init__(self, video_urls, temp_dir, video_save_dir=None, browser_executable=None, user_data_dir=None):
        super().__init__()
        self.video_urls = video_urls
        self.temp_dir = temp_dir
        self.video_save_dir = video_save_dir if video_save_dir else temp_dir
        self.browser_executable = browser_executable
        self.user_data_dir = user_data_dir
        self.abort = False
    
    def run(self):
        downloaded_videos = []
        total = len(self.video_urls)
        
        if not PLAYWRIGHT_AVAILABLE:
            self.progress_signal.emit(0, "Playwright未安装，尝试使用yt-dlp下载...")
            self.use_ytdlp_fallback()
            return
        
        for i, url in enumerate(self.video_urls):
            if self.abort:
                break
            
            try:
                self.progress_signal.emit(int((i+1)/total*100), f"正在处理第{i+1}个视频: {url}")
                
                video_path = self.download_video_via_browser(url, i)
                
                if video_path:
                    downloaded_videos.append((url, video_path))
                    self.progress_signal.emit(int((i+1)/total*100), f"第{i+1}个视频下载成功")
                else:
                    downloaded_videos.append((url, None))
                    self.progress_signal.emit(int((i+1)/total*100), f"第{i+1}个视频下载失败")
                    
            except Exception as e:
                self.progress_signal.emit(int((i+1)/total*100), f"第{i+1}个视频下载失败: {str(e)}")
                downloaded_videos.append((url, None))
        
        self.finished_signal.emit(downloaded_videos)
    
    def download_video_via_browser(self, video_url, index):
        """通过浏览器访问页面并提取视频流"""
        video_id = video_url.split('/')[-1].split('?')[0]
        output_path = os.path.join(self.video_save_dir, f"video_{index}_{video_id}.mp4")
        video_path = None

        try:
            with sync_playwright() as p:
                # 连接到已打开的浏览器
                browser = p.chromium.connect_over_cdp("http://localhost:9222", timeout=10000)

                # 创建新页面
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.new_page()

                # 用于存储捕获的视频URL
                captured_video_url = None

                # 设置网络请求监听 - 在页面访问前设置
                def handle_response(response):
                    nonlocal captured_video_url
                    url = response.url
                    # 查找视频相关的请求
                    if captured_video_url is None:
                        # 抖音视频域名模式
                        if any(domain in url for domain in ['douyinvod', 'v3-dy', 'amemv', '.mp4']):
                            if 'sign' in url.lower() or 'token' in url.lower() or 'play' in url.lower():
                                self.progress_signal.emit(0, f"捕获到视频请求: {url[:100]}...")
                                captured_video_url = url

                page.on("response", handle_response)

                # 访问视频页面
                self.progress_signal.emit(0, f"正在访问视频页面...")
                try:
                    page.goto(video_url, timeout=30000, wait_until="domcontentloaded")
                except:
                    page.goto(f"https://www.douyin.com/video/{video_id}", timeout=15000, wait_until="domcontentloaded", ignore_https_errors=True)

                # 等待页面加载完成后，滚动页面触发视频加载
                self.progress_signal.emit(0, f"等待视频元素加载...")
                page.wait_for_timeout(5000)

                # 方法1：查找video元素
                try:
                    video_element = page.query_selector("video")
                    if video_element:
                        src = video_element.get_attribute("src")
                        poster = video_element.get_attribute("poster")
                        if src:
                            self.progress_signal.emit(0, f"找到video元素, src: {src[:80]}...")
                            # 跳过 blob URL，它无法直接下载
                            if src.startswith("blob:"):
                                self.progress_signal.emit(0, f"blob URL无法直接下载，尝试其他方法...")
                            else:
                                if src.startswith("//"):
                                    src = "https:" + src
                                self.download_file(src, output_path)
                                if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
                                    video_path = output_path
                        elif poster:
                            self.progress_signal.emit(0, f"找到poster: {poster[:80]}...")
                except Exception as e:
                    self.progress_signal.emit(0, f"查找video元素失败: {e}")

                # 方法2：从页面执行JavaScript提取视频信息
                if not video_path:
                    try:
                        video_info = page.evaluate(r"""
                            () => {
                                const patterns = [
                                    /"playAddr"\s*:\s*"([^"]+)"/,
                                    /"play_url"\s*:\s*\{[^}]*"uri"\s*:\s*"([^"]+)"/,
                                    /https?:\/\/[^\s"']+douyinvod[^\s"']+/,
                                    /https?:\/\/[^\s"']+\.mp4[^\s"']*/,
                                    /<video[^>]+src=["']([^"']+)["']/,
                                ];

                                for (const pattern of patterns) {
                                    const html = document.documentElement.outerHTML;
                                    const match = html.match(pattern);
                                    if (match) {
                                        let url = match[1] || match[0];
                                        try { url = decodeURIComponent(url); } catch(e) {}
                                        url = url.replace(/\\\\u002F/g, '/').replace(/\\u002F/g, '/');
                                        if (url.startsWith('//')) url = 'https:' + url;
                                        if (url.startsWith('http')) return url;
                                    }
                                }

                                const scripts = document.querySelectorAll('script:not([src])');
                                for (const script of scripts) {
                                    const text = script.textContent;
                                    if (text.includes('playAddr') || text.includes('video_url')) {
                                        const match = text.match(/"playAddr"\s*:\s*"([^"]+)"/);
                                        if (match) {
                                            let url = match[1].replace(/\\\\u002F/g, '/');
                                            if (url.startsWith('//')) url = 'https:' + url;
                                            return url;
                                        }
                                    }
                                }

                                const ogVideo = document.querySelector('meta[property="og:video"]');
                                if (ogVideo) return ogVideo.content;

                                return null;
                            }
                        """)

                        if video_info and video_info.startswith("http"):
                            self.progress_signal.emit(0, f"从JavaScript提取到视频URL")
                            self.download_file(video_info, output_path)
                            if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
                                video_path = output_path
                    except Exception as e:
                        self.progress_signal.emit(0, f"JavaScript提取失败: {str(e)[:50]}")

                # 方法3：通过浏览器请求视频详情API获取目标视频
                if not video_path:
                    self.progress_signal.emit(0, f"通过浏览器请求视频详情...")
                    try:
                        # 在浏览器中执行 fetch 请求（安全，无反爬风险）
                        api_result = page.evaluate(f"""
                            async () => {{
                                const apiUrl = 'https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id={video_id}&aid=6383&device_platform=webapp';
                                try {{
                                    const resp = await fetch(apiUrl, {{
                                        method: 'GET',
                                        credentials: 'include',
                                        headers: {{
                                            'Referer': 'https://www.douyin.com/video/{video_id}'
                                        }}
                                    }});
                                    if (!resp.ok) return JSON.stringify({{error: 'HTTP ' + resp.status}});
                                    const data = await resp.json();
                                    const aweme = data?.aweme_detail;
                                    if (!aweme) return JSON.stringify({{error: 'no aweme_detail'}});
                                    const video = aweme.video;
                                    if (!video) return JSON.stringify({{error: 'no video'}});
                                    const playAddr = video.play_addr;
                                    if (!playAddr) return JSON.stringify({{error: 'no play_addr'}});
                                    const urls = playAddr.url_list;
                                    if (!urls || urls.length === 0) return JSON.stringify({{error: 'no url_list'}});
                                    return JSON.stringify({{url: urls[0], aweme_id: String(aweme.aweme_id)}});
                                }} catch (e) {{
                                    return JSON.stringify({{error: e.message}});
                                }}
                            }}
                        """)
                        result = json.loads(api_result)
                        if 'url' in result:
                            self.progress_signal.emit(0, f"✓ 获取到目标视频URL (ID: {result.get('aweme_id', '?')})")
                            self.download_file(result['url'], output_path)
                            if os.path.exists(output_path):
                                size = os.path.getsize(output_path)
                                self.progress_signal.emit(0, f"下载文件大小: {size} bytes")
                                if size > 10000:
                                    video_path = output_path
                        else:
                            self.progress_signal.emit(0, f"API返回错误: {result.get('error', 'unknown')}")
                    except Exception as e:
                        self.progress_signal.emit(0, f"请求异常: {str(e)[:50]}")

                # 方法4：使用捕获的网络请求
                if not video_path and captured_video_url:
                    self.progress_signal.emit(0, f"使用捕获的视频URL下载: {captured_video_url[:100]}")
                    self.download_file(captured_video_url, output_path)
                    if os.path.exists(output_path):
                        size = os.path.getsize(output_path)
                        self.progress_signal.emit(0, f"下载文件大小: {size} bytes")
                        if size > 10000:
                            video_path = output_path
                        else:
                            self.progress_signal.emit(0, f"文件太小，可能下载失败")
                    else:
                        self.progress_signal.emit(0, f"文件未创建")

                if not video_path:
                    self.progress_signal.emit(0, f"尝试备用方案...")

                    # 最后的备用方案：直接访问视频页面
                    try:
                        backup_url = f"https://www.douyin.com/video/{video_id}"
                        self.progress_signal.emit(0, f"访问备用URL: {backup_url}")
                        page.goto(backup_url, timeout=15000, wait_until="domcontentloaded")
                        page.wait_for_timeout(3000)

                        # 再试一次video元素
                        video_element = page.query_selector("video")
                        if video_element:
                            src = video_element.get_attribute("src")
                            if src:
                                if src.startswith("//"):
                                    src = "https:" + src
                                self.progress_signal.emit(0, f"备用方案找到video src: {src[:80]}")
                                self.download_file(src, output_path)
                                if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
                                    video_path = output_path
                    except Exception as e:
                        self.progress_signal.emit(0, f"备用方案失败: {str(e)[:50]}")

                page.close()

        except Exception as e:
            self.progress_signal.emit(0, f"浏览器访问失败: {str(e)[:80]}")

        finally:
            # 检查最终结果
            if video_path and os.path.exists(video_path):
                final_size = os.path.getsize(video_path)
                self.progress_signal.emit(0, f"最终视频文件: {video_path}, 大小: {final_size} bytes")
            else:
                self.progress_signal.emit(0, f"视频下载失败，文件不存在")

        return video_path if video_path and os.path.exists(video_path) and os.path.getsize(video_path) > 10000 else None
    
    def download_file(self, url, output_path):
        """下载文件"""
        try:
            # blob URL 无法直接通过 requests 下载
            if url.startswith("blob:"):
                self.progress_signal.emit(0, f"跳过blob URL: {url[:50]}...")
                return
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0',
                'Referer': 'https://www.douyin.com/',
            }
            response = requests.get(url, headers=headers, stream=True, timeout=30)
            if response.status_code == 200:
                with open(output_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if self.abort:
                            break
                        f.write(chunk)
        except Exception as e:
            self.progress_signal.emit(0, f"下载文件失败: {str(e)[:50]}")
    
    def use_ytdlp_fallback(self):
        """使用yt-dlp作为备用方案"""
        cookies_file = os.path.join(os.path.dirname(__file__), 'cookies.txt')
        
        downloaded_videos = []
        total = len(self.video_urls)
        
        for i, url in enumerate(self.video_urls):
            if self.abort:
                break
            
            try:
                self.progress_signal.emit(int((i+1)/total*100), f"使用yt-dlp下载第{i+1}个视频...")
                
                output_dir = os.path.join(self.temp_dir, f"video_{i}")
                os.makedirs(output_dir, exist_ok=True)
                
                ydl_opts = {
                    'format': 'best',
                    'outtmpl': os.path.join(output_dir, 'video.%(ext)s'),
                    'quiet': True,
                    'no_warnings': True,
                }
                
                if os.path.exists(cookies_file):
                    ydl_opts['cookiefile'] = cookies_file
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                
                # 查找下载的文件
                video_files = []
                for root, _, files in os.walk(output_dir):
                    for file in files:
                        if file.endswith(('.mp4', '.flv', '.avi', '.mov')):
                            video_files.append(os.path.join(root, file))
                
                if video_files:
                    downloaded_videos.append((url, video_files[0]))
                else:
                    downloaded_videos.append((url, None))
                    
            except Exception as e:
                self.progress_signal.emit(int((i+1)/total*100), f"第{i+1}个视频下载失败: {str(e)[:50]}")
                downloaded_videos.append((url, None))
        
        self.finished_signal.emit(downloaded_videos)


class ExtractAudioThread(QThread):
    """提取音频线程"""
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(list)

    def __init__(self, video_files, temp_dir):
        super().__init__()
        self.video_files = video_files
        self.temp_dir = temp_dir
        self.abort = False

    def run(self):
        print("ExtractAudioThread.run() 开始执行")
        audio_files = []
        total = len(self.video_files)
        print(f"开始提取音频，共 {total} 个视频文件")

        for i, (url, video_path) in enumerate(self.video_files):
            if self.abort:
                break

            if video_path is None:
                audio_files.append((url, None))
                continue

            # 检查视频文件是否存在
            if not os.path.exists(video_path):
                # 尝试获取绝对路径
                abs_path = os.path.abspath(video_path)
                if os.path.exists(abs_path):
                    video_path = abs_path
                    self.progress_signal.emit(int((i+1)/total*100), f"使用绝对路径: {video_path}")
                else:
                    self.progress_signal.emit(int((i+1)/total*100), f"视频文件不存在: {video_path}")
                    self.progress_signal.emit(int((i+1)/total*100), f"绝对路径: {abs_path}")
                    self.progress_signal.emit(int((i+1)/total*100), f"当前工作目录: {os.getcwd()}")
                    audio_files.append((url, None))
                    continue

            # 检查视频文件大小
            video_size = os.path.getsize(video_path)
            if video_size < 1000:
                self.progress_signal.emit(int((i+1)/total*100), f"视频文件太小: {video_size} bytes")
                audio_files.append((url, None))
                continue

            try:
                self.progress_signal.emit(int((i+1)/total*100), f"正在提取第{i+1}个视频的音频, 视频大小: {video_size} bytes")
                audio_path = os.path.join(self.temp_dir, f"audio_{i}.wav")

                # 尝试使用 imageio_ffmpeg 提取音频
                audio_extracted = False
                if FFMPEG_AVAILABLE and FFMPEG_EXE:
                    try:
                        self.progress_signal.emit(int((i+1)/total*100), f"使用 imageio_ffmpeg 提取音频")
                        self.progress_signal.emit(int((i+1)/total*100), f"FFmpeg路径: {FFMPEG_EXE}")
                        
                        cmd = [
                            FFMPEG_EXE,
                            '-i', video_path,
                            '-ac', '1',
                            '-ar', '16000',
                            '-format', 'wav',
                            '-y',
                            audio_path
                        ]
                        
                        result = subprocess.run(
                            cmd,
                            capture_output=True,
                            text=False,  # 不使用文本模式，避免编码问题
                            timeout=60
                        )
                        
                        if result.returncode == 0:
                            # 检查音频文件是否生成
                            if os.path.exists(audio_path):
                                audio_size = os.path.getsize(audio_path)
                                if audio_size > 1000:
                                    audio_files.append((url, audio_path))
                                    self.progress_signal.emit(int((i+1)/total*100), f"第{i+1}个视频音频提取完成, 音频大小: {audio_size} bytes")
                                    audio_extracted = True
                                else:
                                    self.progress_signal.emit(int((i+1)/total*100), f"第{i+1}个视频音频文件太小: {audio_size} bytes")
                            else:
                                self.progress_signal.emit(int((i+1)/total*100), f"第{i+1}个视频音频文件未生成")
                        else:
                            # 尝试解码stderr
                            try:
                                stderr = result.stderr.decode('utf-8', errors='ignore')
                                self.progress_signal.emit(int((i+1)/total*100), f"FFmpeg命令失败: {stderr[:100]}")
                            except:
                                self.progress_signal.emit(int((i+1)/total*100), f"FFmpeg命令失败")
                    except Exception as e:
                        self.progress_signal.emit(int((i+1)/total*100), f"imageio_ffmpeg 错误: {str(e)[:100]}")

                # 如果 imageio_ffmpeg 失败，尝试使用 ffmpeg-python
                if not audio_extracted:
                    try:
                        self.progress_signal.emit(int((i+1)/total*100), f"使用 ffmpeg-python 提取音频")
                        (ffmpeg
                         .input(video_path)
                         .output(audio_path, ac=1, ar=16000, format='wav', loglevel='info')
                         .overwrite_output()
                         .run(capture_stdout=True, capture_stderr=True))

                        # 检查音频文件是否生成
                        if os.path.exists(audio_path):
                            audio_size = os.path.getsize(audio_path)
                            if audio_size > 1000:
                                audio_files.append((url, audio_path))
                                self.progress_signal.emit(int((i+1)/total*100), f"第{i+1}个视频音频提取完成, 音频大小: {audio_size} bytes")
                            else:
                                self.progress_signal.emit(int((i+1)/total*100), f"第{i+1}个视频音频文件太小: {audio_size} bytes")
                                audio_files.append((url, None))
                        else:
                            self.progress_signal.emit(int((i+1)/total*100), f"第{i+1}个视频音频文件未生成")
                            audio_files.append((url, None))

                    except ffmpeg.Error as e:
                        self.progress_signal.emit(int((i+1)/total*100), f"ffmpeg错误: {str(e.stderr)[:100] if e.stderr else str(e)[:100]}")
                        audio_files.append((url, None))

            except Exception as e:
                self.progress_signal.emit(int((i+1)/total*100), f"第{i+1}个视频音频提取失败: {str(e)[:100]}")
                audio_files.append((url, None))

        # 确保发送完成信号
        print(f"音频提取完成，共 {len(audio_files)} 个结果")
        print("准备发送finished_signal...")
        self.finished_signal.emit(audio_files)
        print("finished_signal 已发送")


class TranscribeThread(QThread):
    """转写线程"""
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(list)

    def __init__(self, audio_files):
        super().__init__()
        self.audio_files = audio_files
        self.abort = False

    def run(self):
        print("TranscribeThread.run() 开始执行")
        transcriptions = []
        total = len(self.audio_files)

        print(f"开始转写，共 {total} 个音频文件")

        # 优先使用本地Whisper模型
        use_whisper_success = False
        if WHISPER_AVAILABLE and USE_WHISPER:
            print("使用OpenAI Whisper进行语音识别")
            self.progress_signal.emit(0, "使用本地Whisper模型进行语音识别")
            
            try:
                print("正在加载Whisper模型...")
                self.progress_signal.emit(0, "正在加载Whisper模型...")
                
                # 加载模型（会自动下载，如果本地没有的话）
                model = whisper.load_model(WHISPER_MODEL_SIZE)
                print("✓ Whisper模型加载成功")
                self.progress_signal.emit(0, "Whisper模型加载成功")

                for i, (url, audio_path) in enumerate(self.audio_files):
                    if self.abort:
                        break

                    if audio_path is None:
                        transcriptions.append((url, ""))
                        continue

                    # 检查音频文件是否存在
                    if not os.path.exists(audio_path):
                        self.progress_signal.emit(int((i+1)/total*100), f"音频文件不存在: {audio_path}")
                        transcriptions.append((url, ""))
                        continue

                    audio_size = os.path.getsize(audio_path)
                    if audio_size < 1000:
                        self.progress_signal.emit(int((i+1)/total*100), f"音频文件太小: {audio_size} bytes")
                        transcriptions.append((url, ""))
                        continue

                    try:
                        print(f"正在转写第{i+1}个音频, 文件大小: {audio_size} bytes")
                        self.progress_signal.emit(int((i+1)/total*100), f"正在转写第{i+1}个音频, 文件大小: {audio_size} bytes")

                        # 确保ffmpeg在PATH中（Whisper需要）
                        if FFMPEG_AVAILABLE and FFMPEG_EXE:
                            ffmpeg_dir = os.path.dirname(FFMPEG_EXE)
                            current_path = os.environ.get('PATH', '')
                            if ffmpeg_dir not in current_path:
                                os.environ['PATH'] = ffmpeg_dir + os.pathsep + current_path
                                print(f"已将ffmpeg目录添加到PATH: {ffmpeg_dir}")
                            
                            # 也设置 WHISPER_FFMPEG_PATH 环境变量
                            os.environ['WHISPER_FFMPEG_PATH'] = FFMPEG_EXE
                            print(f"设置WHISPER_FFMPEG_PATH: {FFMPEG_EXE}")
                            
                            # 验证ffmpeg是否可用
                            try:
                                result = subprocess.run([FFMPEG_EXE, '-version'], capture_output=True, timeout=5)
                                print(f"FFmpeg验证: {'成功' if result.returncode == 0 else '失败'}")
                            except Exception as e:
                                print(f"FFmpeg验证失败: {e}")

                        # 使用OpenAI Whisper进行转写
                        # 确保使用Windows兼容的路径格式
                        audio_path_normalized = os.path.normpath(audio_path)
                        audio_path_absolute = os.path.abspath(audio_path_normalized)
                        print(f"音频绝对路径: {audio_path_absolute}")
                        print(f"音频文件存在: {os.path.exists(audio_path_absolute)}")
                        print(f"当前PATH: {os.environ.get('PATH', '')[:200]}...")
                        
                        print(f"准备调用whisper.transcribe...")
                        result = model.transcribe(
                            audio_path_absolute,
                            language="zh",
                            initial_prompt="请将以下中文语音转换为简体中文文字。请使用完整的中文标点符号，包括逗号、句号、问号、感叹号等。",
                            fp16=False,  # 使用fp32提高兼容性
                        )
                        
                        transcription = result["text"].strip()
                        
                        print(f"转写结果: {transcription}")

                        if transcription:
                            self.progress_signal.emit(int((i+1)/total*100), f"第{i+1}个音频转写完成, 文字长度: {len(transcription)}")
                            print(f"第{i+1}个音频转写完成, 文字长度: {len(transcription)}")
                            transcriptions.append((url, transcription))
                        else:
                            self.progress_signal.emit(int((i+1)/total*100), f"第{i+1}个音频转写结果为空")
                            print(f"第{i+1}个音频转写结果为空")
                            transcriptions.append((url, ""))

                    except Exception as e:
                        print(f"第{i+1}个音频转写失败: {str(e)}")
                        import traceback
                        traceback.print_exc()
                        self.progress_signal.emit(int((i+1)/total*100), f"第{i+1}个音频转写失败: {str(e)[:100]}")
                        transcriptions.append((url, ""))

                use_whisper_success = True

            except Exception as e:
                print(f"Whisper模型加载失败: {e}")
                import traceback
                traceback.print_exc()
                self.progress_signal.emit(0, f"Whisper模型加载失败，将使用SpeechRecognition: {str(e)[:50]}")

        # 如果Whisper不可用或失败，使用SpeechRecognition作为备选
        if not use_whisper_success:
            print("使用SpeechRecognition作为语音识别方案")
            self.progress_signal.emit(0, "使用SpeechRecognition进行语音识别")
            # 尝试导入SpeechRecognition
            try:
                import speech_recognition as sr
                self.progress_signal.emit(0, "SpeechRecognition库加载成功")
            except ImportError:
                self.progress_signal.emit(0, "SpeechRecognition库未安装，正在安装...")
                try:
                    subprocess.run([sys.executable, '-m', 'pip', 'install', 'SpeechRecognition', '-i', 'https://pypi.tuna.tsinghua.edu.cn/simple'], check=True)
                    import speech_recognition as sr
                    self.progress_signal.emit(0, "SpeechRecognition库安装成功")
                except:
                    self.progress_signal.emit(0, "SpeechRecognition库安装失败")
                    # 直接返回空结果
                    for url, _ in self.audio_files:
                        transcriptions.append((url, ""))
                    print("准备发送finished_signal...")
                    self.finished_signal.emit(transcriptions)
                    return

            # 初始化语音识别器
            r = sr.Recognizer()

            for i, (url, audio_path) in enumerate(self.audio_files):
                if self.abort:
                    break

                if audio_path is None:
                    transcriptions.append((url, ""))
                    continue

                # 检查音频文件是否存在
                if not os.path.exists(audio_path):
                    self.progress_signal.emit(int((i+1)/total*100), f"音频文件不存在: {audio_path}")
                    transcriptions.append((url, ""))
                    continue

                audio_size = os.path.getsize(audio_path)
                if audio_size < 1000:
                    self.progress_signal.emit(int((i+1)/total*100), f"音频文件太小: {audio_size} bytes")
                    transcriptions.append((url, ""))
                    continue

                try:
                    print(f"正在转写第{i+1}个音频, 文件大小: {audio_size} bytes")
                    self.progress_signal.emit(int((i+1)/total*100), f"正在转写第{i+1}个音频, 文件大小: {audio_size} bytes")

                    # 使用SpeechRecognition进行语音识别
                    with sr.AudioFile(audio_path) as source:
                        audio = r.record(source)
                    
                    # 尝试使用Google Web Speech API
                    try:
                        transcription = r.recognize_google(audio, language="zh-CN")
                        self.progress_signal.emit(int((i+1)/total*100), f"第{i+1}个音频转写完成, 文字长度: {len(transcription)}")
                        print(f"转写结果: {transcription}")
                        transcriptions.append((url, transcription))
                    except sr.UnknownValueError:
                        self.progress_signal.emit(int((i+1)/total*100), f"第{i+1}个音频无法识别")
                        transcriptions.append((url, ""))
                    except sr.RequestError as e:
                        self.progress_signal.emit(int((i+1)/total*100), f"第{i+1}个音频转写失败: {str(e)[:100]}")
                        transcriptions.append((url, ""))

                except Exception as e:
                    print(f"第{i+1}个音频转写失败: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    self.progress_signal.emit(int((i+1)/total*100), f"第{i+1}个音频转写失败: {str(e)[:100]}")
                    transcriptions.append((url, ""))

        # 确保发送完成信号
        print(f"转写完成，共 {len(transcriptions)} 个结果")
        print("准备发送finished_signal...")
        self.finished_signal.emit(transcriptions)
        print("finished_signal 已发送")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("视频文案提取工具 - Playwright + Whisper本地版")
        self.setGeometry(100, 100, 900, 700)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout()
        
        # 标题
        title_label = QLabel("<h2>视频文案提取工具</h2>")
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)
        
        # 模式选择
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("下载模式:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "浏览器下载（推荐，需启动浏览器）",
            "本地视频模式（需预先下载视频）",
            "yt-dlp在线下载（需要有效Cookies）"
        ])
        mode_layout.addWidget(self.mode_combo)
        mode_layout.addStretch()
        main_layout.addLayout(mode_layout)
        
        # 文件选择
        file_layout = QHBoxLayout()
        self.file_label = QLabel("选择表格文件:")
        self.file_path = QLineEdit()
        self.file_path.setReadOnly(True)
        self.browse_button = QPushButton("浏览")
        self.browse_button.clicked.connect(self.browse_file)
        file_layout.addWidget(self.file_label)
        file_layout.addWidget(self.file_path)
        file_layout.addWidget(self.browse_button)
        main_layout.addLayout(file_layout)
        
        # 本地视频文件夹
        local_layout = QHBoxLayout()
        self.local_label = QLabel("本地视频文件夹:")
        self.local_path = QLineEdit()
        self.local_path.setReadOnly(True)
        self.local_button = QPushButton("选择")
        self.local_button.clicked.connect(self.browse_local_path)
        local_layout.addWidget(self.local_label)
        local_layout.addWidget(self.local_path)
        local_layout.addWidget(self.local_button)
        main_layout.addLayout(local_layout)

        # 视频保存路径（新增）
        video_layout = QHBoxLayout()
        video_layout.addWidget(QLabel("视频保存路径:"))
        self.video_save_path = QLineEdit()
        self.video_save_path.setReadOnly(True)
        self.video_save_button = QPushButton("选择")
        self.video_save_button.clicked.connect(self.browse_video_save_path)
        video_layout.addWidget(self.video_save_path)
        video_layout.addWidget(self.video_save_button)
        main_layout.addLayout(video_layout)
        
        # 保存路径
        save_layout = QHBoxLayout()
        self.save_label = QLabel("保存路径:")
        self.save_path = QLineEdit()
        self.save_path.setReadOnly(True)
        self.save_button = QPushButton("选择")
        self.save_button.clicked.connect(self.browse_save_path)
        save_layout.addWidget(self.save_label)
        save_layout.addWidget(self.save_path)
        save_layout.addWidget(self.save_button)
        main_layout.addLayout(save_layout)
        
        # 按钮
        button_layout = QHBoxLayout()
        self.start_button = QPushButton("开始处理")
        self.start_button.clicked.connect(self.start_processing)
        self.stop_button = QPushButton("停止")
        self.stop_button.clicked.connect(self.stop_processing)
        self.stop_button.setEnabled(False)
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.stop_button)
        main_layout.addLayout(button_layout)
        
        # 进度条
        self.progress_bar = QProgressBar()
        main_layout.addWidget(self.progress_bar)
        
        # 日志
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        main_layout.addWidget(self.log_text)
        
        central_widget.setLayout(main_layout)
        
        # 初始化变量
        self.temp_dir = None
        self.download_thread = None
        self.extract_thread = None
        self.transcribe_thread = None
        self.is_running = False
        self.abort = False
        
        self.log("=" * 50)
        self.log("视频文案提取工具已启动")
        self.log("=" * 50)
        self.log("")
        self.log("使用说明:")
        self.log("1. 浏览器下载模式：需要先启动带调试端口的Edge浏览器")
        self.log("2. 本地视频模式：将视频预先下载到文件夹，选择文件夹即可")
        self.log("3. yt-dlp模式：需要有效的Cookies（Cookies会过期）")
        self.log("")
    
    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择表格文件", "", "Excel files (*.xlsx *.xls);;CSV files (*.csv)")
        if file_path:
            self.file_path.setText(file_path)
            base_name = os.path.splitext(file_path)[0]
            save_path = f"{base_name}_已处理.xlsx"
            self.save_path.setText(save_path)
    
    def browse_local_path(self):
        folder_path = QFileDialog.getExistingDirectory(self, "选择本地视频文件夹")
        if folder_path:
            self.local_path.setText(folder_path)
            self.log(f"已选择本地视频文件夹: {folder_path}")

    def browse_video_save_path(self):
        folder_path = QFileDialog.getExistingDirectory(self, "选择视频保存路径")
        if folder_path:
            self.video_save_path.setText(folder_path)
            self.log(f"已选择视频保存路径: {folder_path}")
    
    def browse_save_path(self):
        save_path, _ = QFileDialog.getSaveFileName(self, "选择保存路径", "", "Excel files (*.xlsx)")
        if save_path:
            self.save_path.setText(save_path)
    
    def log(self, message):
        self.log_text.append(message)
        self.log_text.ensureCursorVisible()
    
    def start_processing(self):
        if self.is_running:
            return
        
        print("=" * 60)
        print("开始处理...")
        print("=" * 60)
        
        file_path = self.file_path.text()
        if not file_path:
            QMessageBox.warning(self, "警告", "请选择表格文件")
            return
        
        print(f"表格文件: {file_path}")
        
        save_path = self.save_path.text()
        if not save_path:
            QMessageBox.warning(self, "警告", "请选择保存路径")
            return
        
        print(f"保存路径: {save_path}")
        
        # 读取表格
        print("读取表格...")
        try:
            if file_path.endswith('.csv'):
                df = pd.read_csv(file_path)
            else:
                df = pd.read_excel(file_path)
            print(f"表格读取成功，共 {len(df)} 行")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"读取表格失败: {str(e)}")
            print(f"读取表格失败: {str(e)}")
            return
        
        # 查找视频链接列
        print("查找视频链接列...")
        video_columns = [col for col in df.columns if '视频' in col and '链接' in col or 'video' in col.lower() and 'url' in col.lower()]
        if not video_columns:
            link_columns = [col for col in df.columns if '链接' in col or 'url' in col.lower()]
            if link_columns:
                video_columns = link_columns
            else:
                QMessageBox.critical(self, "错误", "未找到视频链接列")
                print("未找到视频链接列")
                return
        
        print(f"找到视频链接列: {video_columns[0]}")
        
        video_urls = df[video_columns[0]].dropna().tolist()
        if not video_urls:
            QMessageBox.critical(self, "错误", "视频链接列为空")
            print("视频链接列为空")
            return
        
        print(f"找到 {len(video_urls)} 个视频链接")
        
        # 清理URL
        print("清理URL...")
        import re
        cleaned_urls = []
        for url in video_urls:
            cleaned = str(url).strip().replace('`', '')
            cleaned = re.sub(r'\s+', '', cleaned)
            if cleaned.startswith('http'):
                cleaned_urls.append(cleaned)
                self.log(f"清理后的链接: {cleaned}")
                print(f"清理后的链接: {cleaned}")
        
        print(f"清理后剩余 {len(cleaned_urls)} 个有效链接")
        
        if not cleaned_urls:
            QMessageBox.critical(self, "错误", "没有有效的视频链接")
            print("没有有效的视频链接")
            return
        
        # 创建临时目录
        self.temp_dir = tempfile.mkdtemp()
        self.log(f"创建临时目录: {self.temp_dir}")
        print(f"创建临时目录: {self.temp_dir}")

        # 获取视频保存路径
        video_save_dir = self.video_save_path.text()
        if video_save_dir:
            os.makedirs(video_save_dir, exist_ok=True)
            self.log(f"视频将保存到: {video_save_dir}")
            print(f"视频将保存到: {video_save_dir}")
        else:
            video_save_dir = self.temp_dir
            self.log(f"未指定保存路径，视频将保存到临时目录")
            print(f"未指定保存路径，视频将保存到临时目录")
        
        self.is_running = True
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        
        download_mode = self.mode_combo.currentIndex()
        
        if download_mode == 0:  # 浏览器下载
            self.log("使用浏览器下载模式...")
            print("使用浏览器下载模式...")
            self.download_thread = BrowserDownloadThread(cleaned_urls, self.temp_dir, video_save_dir)
            self.download_thread.progress_signal.connect(self.update_progress)
            self.download_thread.finished_signal.connect(self.on_download_finished)
            self.download_thread.start()
        elif download_mode == 1:  # 本地视频
            self.log("使用本地视频模式...")
            print("使用本地视频模式...")
            self.process_local_videos(cleaned_urls)
        else:  # yt-dlp
            self.log("使用yt-dlp下载模式...")
            print("使用yt-dlp下载模式...")
            self.download_thread = BrowserDownloadThread(cleaned_urls, self.temp_dir, video_save_dir)
            self.download_thread.progress_signal.connect(self.update_progress)
            self.download_thread.finished_signal.connect(self.on_download_finished)
            self.download_thread.start()
    
    def process_local_videos(self, video_urls):
        """处理本地视频"""
        local_folder = self.local_path.text()
        if not local_folder or not os.path.exists(local_folder):
            self.log("请先选择本地视频文件夹")
            print("请先选择本地视频文件夹")
            self.is_running = False
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            return
        
        print(f"本地视频文件夹: {local_folder}")
        
        video_files = []
        total = len(video_urls)
        
        print("扫描本地视频文件...")
        local_videos = {}
        for file in os.listdir(local_folder):
            if file.endswith(('.mp4', '.flv', '.avi', '.mov', '.mkv')):
                name = os.path.splitext(file)[0]
                local_videos[name] = os.path.join(local_folder, file)
        
        print(f"找到 {len(local_videos)} 个本地视频文件")
        
        for i, url in enumerate(video_urls):
            if self.abort:
                break
            
            video_id = url.split('/')[-1]
            matched_path = None
            
            for name, path in local_videos.items():
                if video_id in name or name in url:
                    matched_path = path
                    break
            
            if matched_path:
                video_files.append((url, matched_path))
                self.update_progress(int((i+1)/total*100), f"第{i+1}个视频匹配成功")
                print(f"第{i+1}个视频匹配成功: {os.path.basename(matched_path)}")
            else:
                video_files.append((url, None))
                self.update_progress(int((i+1)/total*100), f"第{i+1}个视频未找到本地文件")
                print(f"第{i+1}个视频未找到本地文件")
        
        # 直接进入音频提取阶段
        print("开始音频提取...")
        self.on_download_finished(video_files)
    
    def update_progress(self, value, message):
        self.progress_bar.setValue(value)
        self.log(message)
    
    def on_download_finished(self, downloaded_videos):
        if not self.is_running:
            return

        # 添加诊断日志
        self.log(f"下载完成，收到 {len(downloaded_videos)} 个视频")
        print(f"下载完成，收到 {len(downloaded_videos)} 个视频")
        for i, (url, video_path) in enumerate(downloaded_videos):
            exists = "存在" if video_path and os.path.exists(video_path) else "不存在"
            size = os.path.getsize(video_path) if video_path and os.path.exists(video_path) else 0
            self.log(f"  视频{i+1}: {video_path} ({exists}, {size} bytes)")
            print(f"  视频{i+1}: {os.path.basename(video_path) if video_path else '无'} ({exists}, {size} bytes)")

        self.log("开始提取音频...")
        print("开始提取音频...")
        self.extract_thread = ExtractAudioThread(downloaded_videos, self.temp_dir)
        self.extract_thread.progress_signal.connect(self.update_progress)
        self.extract_thread.finished_signal.connect(self.on_extract_finished)
        self.extract_thread.start()

    def on_extract_finished(self, audio_files):
        if not self.is_running:
            return
        
        print(f"on_extract_finished 被调用，收到 {len(audio_files)} 个音频文件")
        for i, (url, path) in enumerate(audio_files):
            print(f"  音频{i+1}: {url}, 路径: {path}, 存在: {os.path.exists(path) if path else 'None'}")
        
        self.log("开始转写音频...")
        print("开始转写音频...")
        self.transcribe_thread = TranscribeThread(audio_files)
        self.transcribe_thread.progress_signal.connect(self.update_progress)
        self.transcribe_thread.finished_signal.connect(self.on_transcribe_finished)
        self.transcribe_thread.start()
        print("TranscribeThread 已启动")
    
    def on_transcribe_finished(self, transcriptions):
        if not self.is_running:
            return
        
        print("开始处理转写结果...")
        
        try:
            file_path = self.file_path.text()
            print(f"读取表格: {file_path}")
            if file_path.endswith('.csv'):
                df = pd.read_csv(file_path)
            else:
                df = pd.read_excel(file_path)
            
            print(f"表格读取成功，共 {len(df)} 行")
            
            video_columns = [col for col in df.columns if '视频' in col and '链接' in col or 'video' in col.lower() and 'url' in col.lower()]
            if not video_columns:
                link_columns = [col for col in df.columns if '链接' in col or 'url' in col.lower()]
                if link_columns:
                    video_columns = link_columns
            
            transcription_map = {url: text for url, text in transcriptions}
            print(f"转写结果数量: {len(transcription_map)}")
            
            if '视频文案' not in df.columns:
                df['视频文案'] = ''
                print("新增'视频文案'列")
            
            print("回填转写结果...")
            import re
            for i, url in enumerate(df[video_columns[0]]):
                if pd.notna(url):
                    cleaned = str(url).strip().replace('`', '')
                    cleaned = re.sub(r'\s+', '', cleaned)
                    if cleaned in transcription_map:
                        text = transcription_map[cleaned]
                        df.at[i, '视频文案'] = text
                        print(f"  第{i+1}行: 回填成功")
                        print(f"    链接: {cleaned[:50]}...")
                        print(f"    文案: {text[:100]}...")
            
            save_path = self.save_path.text()
            print(f"保存结果到: {save_path}")
            if save_path.endswith('.csv'):
                df.to_csv(save_path, index=False, encoding='utf-8-sig')
            else:
                df.to_excel(save_path, index=False)
            
            self.log(f"处理完成，结果保存至: {save_path}")
            print(f"处理完成，结果保存至: {save_path}")
            
            QMessageBox.information(self, "成功", "处理完成，结果已保存")
            
        except Exception as e:
            self.log(f"保存结果失败: {str(e)}")
            print(f"保存结果失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"保存结果失败: {str(e)}")
        
        # 清理
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
                self.log(f"清理临时目录: {self.temp_dir}")
                print(f"清理临时目录: {self.temp_dir}")
            except:
                pass
        
        self.is_running = False
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.progress_bar.setValue(0)
        print("=" * 60)
        print("处理完成")
        print("=" * 60)
        self.stop_button.setEnabled(False)
        self.progress_bar.setValue(0)
    
    def stop_processing(self):
        if not self.is_running:
            return
        
        self.abort = True
        self.is_running = False
        
        if self.download_thread:
            self.download_thread.abort = True
            self.download_thread.wait()
        if self.extract_thread:
            self.extract_thread.abort = True
            self.extract_thread.wait()
        if self.transcribe_thread:
            self.transcribe_thread.abort = True
            self.transcribe_thread.wait()
        
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
            except:
                pass
        
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self.log("处理已停止")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())