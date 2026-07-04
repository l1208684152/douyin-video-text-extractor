# 抖音视频文案处理一体化工具

三合一 PyQt5 桌面应用：**采集 → 识别 → 修正**，一条龙处理抖音视频文案。

## 功能概览

### ① 视频信息采集
- 通过 Playwright CDP 连接浏览器，采集博主主页视频元数据
- 提取字段：视频标题、完整标题、话题标签、链接、封面、点赞数
- 支持导出 Excel + 嵌入封面缩略图
- 手动控制滚动，支持断点续采（去重）

### ② 文案提取（下载 + 语音识别）
- **三种下载模式**：浏览器 CDP / 本地视频 / yt-dlp
- 自动提取音频（16kHz 单声道 WAV）
- **Whisper 本地语音识别**：`large-v3-turbo` 模型，常驻多子进程并行
- **断点续传**：跳过已有文案，每 5 个增量保存
- **下载重试**：失败自动重试 3 次（递增间隔）

### ③ AI 文案修正
- **9 种服务商**：LM Studio / Ollama / OpenAI / DeepSeek / 通义千问 / 智谱 / Kimi / 零一万物 / 自定义
- **系统提示词**：定义 AI 角色和行为
- **多规则批处理**：每条规则独立指定源列和输出列
- **API 重试**：超时/连接错误自动重试 3 次
- 配置保存/加载（JSON）

## 安装

```bash
# 1. 克隆
git clone https://github.com/l1208684152/douyin-video-text-extractor.git
cd douyin-video-text-extractor/merged_app

# 2. 安装依赖
pip install -r requirements.txt

# 3. 安装 Playwright 浏览器
playwright install

# 4. (可选) 安装 SpeechRecognition 作为语音识别备选
pip install SpeechRecognition
```

## 使用

### 启动程序
```bash
python main.py
```

### Tab1 — 采集视频信息
1. 用调试端口启动浏览器：`msedge.exe --remote-debugging-port=9222`
2. 在浏览器中打开抖音博主主页
3. 点击「检测浏览器」→ 设置等待秒数 →「开始采集」
4. 在等待时间内手动滚动加载视频，时间到自动提取
5. 保存为 Excel

### Tab2 — 提取文案
1. 加载 Tab1 输出的 Excel（或任意含视频链接列的表格）
2. 选择下载模式（推荐浏览器模式，需先启动带调试端口的浏览器）
3. 点击「开始处理」，自动完成：下载 → 音频提取 → Whisper 识别
4. 结果写入「视频文案」列

### Tab3 — AI 修正文案
1. 选择 AI 服务商，填写 API Key（本地模型无需）
2. 填写系统提示词（选填）
3. 配置处理规则：规则名称、源列、输出列、处理指令
4. 打开表格 →「批量处理全部」
5. 保存结果

## 配置

### Whisper 模型
在 `main.py` 顶部修改：
```python
USE_WHISPER = True
WHISPER_MODEL_SIZE = "large-v3-turbo"  # tiny/base/small/medium/large/large-v3-turbo
```

模型首次使用时自动下载到 `~/.cache/whisper/`。

### 并行子进程数
默认自动检测：`min(2, CPU核心数/2)`。可在 TranscribeThread 初始化时传入 `workers` 参数。

### 浏览器调试端口
默认 `9222`，可在 Tab1 界面修改。Edge 启动命令：
```bash
msedge.exe --remote-debugging-port=9222
```
Chrome：
```bash
chrome.exe --remote-debugging-port=9222
```

## 依赖

| 库 | 用途 |
|---|---|
| PyQt5 | GUI 框架 |
| Playwright | 浏览器自动化（采集 + 下载） |
| openai-whisper | 本地语音识别 |
| yt-dlp | 视频下载备用方案 |
| pandas / openpyxl | Excel 读写 |
| ffmpeg-python / imageio-ffmpeg | 音频提取 |
| requests | HTTP（下载 + API 调用） |

Python 3.10+，Windows/macOS/Linux 均可。

## 架构

```
main.py
├── BrowserDownloadThread  # 视频下载
├── ExtractAudioThread     # 音频提取
├── TranscribeThread       # 语音识别（常驻子进程，并行）
├── CorrectionThread       # AI 文案修正
├── CollectThread          # 视频信息采集
├── CollectorTab           # 标签页 1
├── ExtractorTab           # 标签页 2
└── CorrectorTab           # 标签页 3
```

数据流转：`Tab1 输出 Excel → Tab2 加载 → Tab3 加载`，每步完成自动提示跳转。

## License

MIT
