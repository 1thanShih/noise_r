# White Noise Looper & Player

這是一個完整的白噪音音訊處理與 ESP32 播放解決方案。包含從電腦端的白噪音音訊無縫銜接生成，到微控制器（ESP32 + DFPlayer Mini）端的循環播放測試。

## 專案結構

- `noise_looper.py`: Python GUI 工具。用於將較短的白噪音音檔，透過無縫交叉淡化（Crossfade）和 RMS 音量標準化，延長並生成長時段（如 30 分鐘）的音檔。支援匯出 WAV, FLAC, 與 MP3 格式。
- `prepare_sd_card.py`: Python 腳本。用於將生成的白噪音音檔自動複製並重新命名為 DFPlayer Mini 支援的標準命名格式（如 `0001.mp3`），並放置到 `sd_card_test/mp3/` 目錄下以供測試。
- `esp32_loop_test/`: Arduino 專案。測試使用 ESP32 與 DFPlayer Mini 播放分為頭（head）尾（tail）兩段的短音檔，透過精確的定時主動切換來模擬無縫循環。
- `sd_card_test/`: Arduino 專案。測試使用 ESP32 與 DFPlayer Mini 直接播放透過 `noise_looper.py` 生成的 30 分鐘長版本白噪音。包含定時主動重播與 BUSY Pin 兜底機制，確保長時間連續播放不中斷。

## 系統需求與環境設定

### 電腦端音訊處理工具 (Python)
1. Python 3.10 以上版本
2. 安裝必要的套件：
   ```bash
   pip install customtkinter soundfile numpy
   ```
3. 若需輸出 MP3 格式，系統中必須安裝 `ffmpeg`，並將其加入系統環境變數 PATH 中。

### 硬體端 (ESP32 + DFPlayer Mini)
- ESP32 開發板
- DFPlayer Mini 模組
- MicroSD 卡（需格式化為 FAT32）
- 依賴的 Arduino 程式庫：`DFRobotDFPlayerMini` (建議版本 1.0.6)

#### 硬體接線
| ESP32 Pin | DFPlayer Mini Pin | 說明 |
| :--- | :--- | :--- |
| GPIO 16 (RX2) | TX (Pin 3) | 序列通訊接收 |
| GPIO 17 (TX2) | RX (Pin 2) | 序列通訊發送（建議串聯 1kΩ 電阻） |
| GPIO 4 | BUSY (Pin 16) | 狀態偵測（LOW = 播放中） |
| 5V / VIN | VCC | DFPlayer 電源（需穩定 5V） |
| GND | GND | 共地 |

## 使用流程

### 1. 製作長時間白噪音音檔
執行 `noise_looper.py` 開啟圖形化介面。
```bash
python noise_looper.py
```
- **選擇音檔**：載入你的原始短白噪音檔案。
- **設定參數**：設定目標長度（例如 30 分鐘），調整 Crossfade 長度（推薦 2 秒）以及目標 RMS 音量（推薦 -20 dB）。
- **輸出設定**：選擇輸出格式（WAV, FLAC, MP3）並選擇輸出目錄（建議匯出到本專案的 `30loop/` 目錄）。
- **開始轉檔**：點擊「開始轉檔」生成檔案。

### 2. 準備 SD 卡檔案
生成 30 分鐘的檔案後，執行腳本以複製並轉換檔名：
```bash
python prepare_sd_card.py
```
這會將 `30loop/` 目錄下的特定音檔重新命名為 `0001.mp3` 到 `0005.mp3`，並放入 `sd_card_test/mp3/` 中。接著將 `sd_card_test/mp3/` 整個資料夾複製到你的 MicroSD 卡根目錄。

### 3. ESP32 播放測試
使用 Arduino IDE 開啟並上傳 `sd_card_test/sd_card_test.ino` 到 ESP32。

上傳完成後開啟序列埠監控視窗 (Baud rate: 115200)。你可以透過發送以下字元指令來控制播放：
- `1` ~ `5`：切換音軌（對應 0001.mp3 ~ 0005.mp3）
- `v18`：設定音量為 18（範圍 0~30）
- `s`：顯示目前播放狀態與時長估算
- `r`：立即從頭重新播放目前音檔

## 聲音內容與音軌對照

| 檔名 (SD卡) | 原檔名 (30loop) | 內容類型 |
| :--- | :--- | :--- |
| `0001.mp3` | `30min_camp_fire.mp3` | 營火 (Camp fire) |
| `0002.mp3` | `30min_dark_noise.mp3` | 暗噪音 (Dark noise) |
| `0003.mp3` | `30min_ocean.mp3` | 海浪 (Ocean) |
| `0004.mp3` | `30min_rainy.mp3` | 下雨 (Rainy) |
| `0005.mp3` | `30min_coffee_shop.mp3` | 咖啡廳 (Coffee shop) |
