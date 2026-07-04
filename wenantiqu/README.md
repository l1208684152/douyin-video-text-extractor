# Douyin Video Text Extractor

Douyin Video Text Extractor is a powerful desktop application designed to automatically download Douyin (TikTok) videos, extract audio, and transcribe speech to text using a local Whisper model. It features a user-friendly GUI built with PyQt5 and supports multiple download modes.

## Features

- **Multiple Download Modes**:
  - **Browser Download Mode** (Recommended): Uses an existing browser session with debugging port enabled to download videos.
  - **Local Video Mode**: Process pre-downloaded videos from a local folder.
  - **yt-dlp Mode**: Download videos directly using yt-dlp (requires valid cookies).
  
- **Local Whisper Model**: Uses the OpenAI Whisper model for speech-to-text transcription, ensuring privacy and avoiding network-dependent services.
  
- **Batch Processing**: Process multiple videos at once by providing an Excel/CSV file with video links.
  
- **Automatic Audio Extraction**: Extracts audio from videos and converts it to the appropriate format for transcription.
  
- **Result Export**: Automatically saves transcribed text back to an Excel file alongside the original video links.

## Prerequisites

- Python 3.11+
- Edge or Chrome browser installed

## Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd wenantiqu
   ```

2. **Create a virtual environment (optional but recommended)**:
   ```bash
   python -m venv venv
   venv\Scripts\activate  # On Windows
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Install Playwright browser**:
   ```bash
   playwright install
   playwright install-deps
   ```

5. **Download Whisper model (optional - automatic on first run)**:
   The `small` model is used by default. You can change the model size in `main.py` by modifying the `WHISPER_MODEL_SIZE` variable. Available options: `tiny`, `base`, `small`, `medium`, `large`.

## Usage

### 1. Browser Download Mode (Recommended)

Before using this mode, you need to start your browser with remote debugging enabled:

**For Edge:**
```bash
msedge.exe --remote-debugging-port=9222
```

**For Chrome:**
```bash
chrome.exe --remote-debugging-port=9222
```

Then:
1. Run the application: `python main.py`
2. Select "Browser Download Mode" from the dropdown.
3. Choose your Excel file containing the video links.
4. Select the output directory for videos.
5. Click "Start Processing".

### 2. Local Video Mode

1. Pre-download your videos to a folder.
2. Run the application: `python main.py`
3. Select "Local Video Mode".
4. Choose your Excel file containing the video links.
5. Select the local video folder.
6. Click "Start Processing".

### 3. yt-dlp Mode

1. Obtain a valid `cookies.txt` file from your browser (cookies will expire over time).
2. Place `cookies.txt` in the project directory.
3. Run the application and select "yt-dlp Mode".
4. Click "Start Processing".

## Input File Format

The application expects an Excel (`.xlsx`) or CSV (`.csv`) file with at least one column containing video links. The column name should include "视频链接" (Video Link) or "video url".

Example Excel structure:
| 视频链接 | 其他数据 |
|----------|----------|
| https://www.douyin.com/video/xxxxx | ... |

## Output

The application will generate an output Excel file (named `<original_name>_已处理.xlsx`) with a new column "视频文案" containing the transcribed text for each video.

## Configuration

You can modify the following variables in `main.py`:

- `USE_WHISPER`: Set to `True` to use the local Whisper model (default).
- `WHISPER_MODEL_SIZE`: Change the Whisper model size (default: `"small"`).

## Troubleshooting

- **DLL Initialization Error**: Ensure `whisper` is imported before `PyQt5` and `yt_dlp` in the code.
- **FileNotFoundError during transcription**: The application uses a monkey-patch to fix the ffmpeg path. Ensure `imageio-ffmpeg` is installed.
- **Video Download Failed**: Try using the Browser Download mode with a freshly started browser session.
- **Cookies Expired**: For yt-dlp mode, you need to periodically refresh your `cookies.txt` file.

## License

This project is for educational purposes only. Please respect copyright and content usage policies when using this tool.
