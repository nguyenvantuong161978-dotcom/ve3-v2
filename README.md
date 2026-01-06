# VE3 Tool Pro

**Voice to Video** - Tu dong tao anh/video tu file voice/audio

## Tinh nang

- **Voice to SRT** - Chuyen audio thanh phu de (Whisper)
- **SRT to Prompts** - AI tao prompt tu noi dung (DeepSeek/Groq/Gemini)
- **Prompts to Images** - Tao anh bang Google Flow API
- **Images to Videos** - Tao video bang Veo 3 API
- **1 Click** - Tu dong toan bo quy trinh
- **Song song** - Nhieu Chrome profiles chay cung luc

---

## Cai dat tren may moi

### Yeu cau he thong

- Python 3.8+
- Google Chrome (da dang nhap tai khoan Google)
- Git (tuy chon, de auto-update)
- FFmpeg (tuy chon, cho video rendering)

### Buoc 1: Clone repository

```bash
git clone https://github.com/criggerbrannon-hash/ve3-tool.git
cd ve3-tool
```

Hoac tai ZIP tu GitHub va giai nen.

### Buoc 2: Cai dat dependencies

```bash
# Cai dat tu dong
python install.py

# Hoac cai thu cong
pip install -r requirements.txt
```

**Dependencies chinh:**
- `pyyaml` - Doc file config
- `openpyxl` - Quan ly Excel
- `requests` - HTTP requests
- `pillow` - Xu ly anh
- `selenium` - Browser automation
- `undetected-chromedriver` - Bypass bot detection
- `pyautogui`, `pyperclip` - Auto token extraction

**Tuy chon (cho Voice to SRT):**
```bash
pip install openai-whisper
# hoac
pip install whisper-timestamped
```

### Buoc 3: Cau hinh

#### 3.1. Tim Chrome Profile Path

1. Mo Chrome
2. Vao `chrome://version`
3. Tim dong **Profile Path**
4. Copy duong dan (vd: `C:\Users\Name\AppData\Local\Google\Chrome\User Data\Profile 1`)

#### 3.2. Sua file config/settings.yaml

```yaml
# Chrome
chrome_path: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
chrome_profile: "C:\\Users\\YOUR_NAME\\AppData\\Local\\Google\\Chrome\\User Data\\Profile 1"

# API Keys (chon 1 trong cac options)
deepseek_api_keys:
  - "sk-..."  # https://platform.deepseek.com/api_keys

groq_api_keys:
  - "gsk_..."  # https://console.groq.com/keys (FREE)

gemini_api_keys:
  - "..."  # https://aistudio.google.com/apikey

# Hoac dung Ollama (local, mien phi)
ollama:
  model: "qwen2.5:7b"
  endpoint: "http://localhost:11434"
```

#### 3.3. (Tuy chon) Cau hinh nhieu Chrome profiles

Tao file `config/accounts.json`:

```json
{
    "chrome_path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "chrome_profiles": [
        "C:\\Users\\Name\\...\\Profile 1",
        "C:\\Users\\Name\\...\\Profile 2",
        "C:\\Users\\Name\\...\\Profile 3"
    ],
    "api_keys": {
        "deepseek": ["sk-..."],
        "groq": ["gsk_...", "gsk_..."],
        "gemini": []
    },
    "settings": {
        "parallel": 2,
        "delay_between_images": 2
    }
}
```

### Buoc 4: Chay tool

```bash
python ve3_pro.py
```

**Trong GUI:**
1. Chon file voice (.mp3, .wav) hoac thu muc
2. Click **BAT DAU**
3. Tool tu dong chay:
   - Lay token tu Chrome
   - Chuyen voice -> SRT
   - Tao prompts bang AI
   - Tao anh/video

---

## Cau truc thu muc

```
ve3-tool/
├── ve3_pro.py           # Main GUI app
├── main_tab.py          # UI workspace
├── install.py           # Script cai dat
├── requirements.txt     # Dependencies
├── config/
│   ├── settings.yaml    # Cau hinh chinh
│   ├── accounts.json    # Multi-profile (tuy chon)
│   └── prompts.yaml     # Prompt templates
├── modules/             # Core modules
│   ├── smart_engine.py  # Pipeline orchestration
│   ├── google_flow_api.py
│   ├── prompts_generator.py
│   ├── voice_to_srt.py
│   └── ...
├── scripts/             # Helper scripts
└── PROJECTS/            # Output folder
    └── {project_name}/
        ├── project.xlsx
        ├── srt/
        ├── img/
        └── video/
```

---

## Lay API Keys

### DeepSeek (Khuyen dung - Re)
1. Vao https://platform.deepseek.com
2. Dang ky tai khoan
3. Vao API Keys -> Create new key
4. Copy va dan vao config

### Groq (Mien phi)
1. Vao https://console.groq.com/keys
2. Dang nhap bang Google
3. Create API Key
4. Copy va dan vao config

### Gemini (Mien phi)
1. Vao https://aistudio.google.com/apikey
2. Create API Key
3. Copy va dan vao config

### Ollama (Local, mien phi)
1. Cai dat Ollama: https://ollama.ai
2. Pull model: `ollama pull qwen2.5:7b`
3. Chay: `ollama serve`

---

## Su dung

### Mode 1: GUI (De su dung)
```bash
python ve3_pro.py
```

### Mode 2: Windows Launcher
```
Double-click RUN.bat
```

---

## Troubleshooting

### Loi: "Khong lay duoc token"
- Dam bao Chrome da dang nhap Google
- Thu dung Chrome profile khac
- Kiem tra chrome_path trong settings.yaml

### Loi: "Module not found"
```bash
pip install -r requirements.txt
```

### Loi: "Chrome khong mo duoc"
- Kiem tra duong dan chrome_path
- Dam bao Chrome da dong het

### Loi: "API rate limit"
- Them nhieu API keys vao config
- Giam settings.parallel xuong

---

## Update

Code tu dong update moi lan chay (neu co Git).

Config va PROJECTS **khong bi anh huong** khi update.

---

## License

MIT

## Author

Developed with Claude AI
