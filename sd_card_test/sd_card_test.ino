/* Project: DFPlayer Mini 30 分鐘白噪音循環播放 (SD Card Test)
 * Target:  ESP32 DevKit (原版)
 * Framework: Arduino (ESP32 board package)
 * Libraries: DFRobotDFPlayerMini @ 1.0.6
 *
 * 說明：
 *   播放 30 分鐘完整白噪音檔案，播完後自動重播（無限循環）。
 *   邏輯參考 esp32_loop_test.ino，但改為單檔完整播放而非 tail/head 切片。
 *   使用「定時主動切」+ 「BUSY 兜底」雙保險，確保不會中斷。
 *
 * SD 卡檔案結構（DFPlayer Mini /mp3/ 資料夾標準命名）：
 *
 *   ┌────────┬──────────────────────────────────────────────────┐
 *   │ 檔案   │ 內容                                             │
 *   ├────────┼──────────────────────────────────────────────────┤
 *   │ 0001   │ camp fire   (營火)         — 30min, 1800.000s   │
 *   │ 0002   │ dark noise  (暗噪音)       — 30min, 1800.000s   │
 *   │ 0003   │ ocean       (海洋)         — 30min, 1800.000s   │
 *   │ 0004   │ rainny      (下雨)         — 30min, 1800.000s   │
 *   │ 0005   │ coffee shop (咖啡廳)       — 30min, 1800.000s   │
 *   └────────┴──────────────────────────────────────────────────┘
 *
 *   來源：30loop/ 資料夾中的 30min_*.mp3 檔案
 *   複製到 SD 卡時需重新命名：
 *     30min_camp_fire.mp3   → /mp3/0001.mp3
 *     30min_dark_noise.mp3  → /mp3/0002.mp3
 *     30min_ocean.mp3       → /mp3/0003.mp3
 *     30min_rainy.mp3       → /mp3/0004.mp3
 *     30min_coffee_shop.mp3 → /mp3/0005.mp3
 *
 * Serial 指令 (115200 baud, 行尾 Newline)：
 *   1 ~ 5 : 切換音軌
 *   v 數字: 設定音量 (0~30)，例如 v18
 *   s     : 顯示目前狀態
 *   r     : 立即從頭重播目前音軌
 *   ?     : 顯示說明
 */

#include <HardwareSerial.h>
#include <DFRobotDFPlayerMini.h>

// === Pin definitions ===
#define DFPLAYER_RX_PIN  16  // ESP32 RX2 <- DFPlayer TX (pin 3)
#define DFPLAYER_TX_PIN  17  // ESP32 TX2 -> DFPlayer RX (pin 2，記得串 1k 電阻)
#define DFPLAYER_BUSY    4   // DFPlayer BUSY (pin 16) -> ESP32 GPIO4 (LOW=播放中)

// === 預設參數 ===
#define DEFAULT_VOLUME 18
#define DEFAULT_TRACK  3    // 預設播放 ocean
#define NUM_TRACKS     5

// === 各檔案實測長度 (毫秒) ===
// 全部皆為 30 分鐘 = 1,800,000 ms
const uint32_t TRACK_DURATION_MS[NUM_TRACKS + 1] = {
  0,          // index 0 unused
  1800000,    // 0001 = camp fire
  1800000,    // 0002 = dark noise
  1800000,    // 0003 = ocean
  1800000,    // 0004 = rainny
  1800000,    // 0005 = coffee shop
};

// === 提前重播的緩衝時間 ===
// 在檔案預計結束前多少 ms 發出重播指令，
// 避開 DFPlayer 開檔延遲造成的空白。
#define RESTART_BEFORE_END_MS  500

HardwareSerial dfSerial(2);
DFRobotDFPlayerMini player;

// === 執行期狀態 ===
uint8_t  currentTrack      = DEFAULT_TRACK;
uint8_t  volume            = DEFAULT_VOLUME;
uint32_t playbackStartMs   = 0;
bool     hasIssuedRestart  = false;
uint32_t loopCount         = 0;   // 已循環幾次

// === Helpers ===
const char* trackName(uint8_t t) {
  switch (t) {
    case 1: return "camp fire";
    case 2: return "dark noise";
    case 3: return "ocean";
    case 4: return "rainny";
    case 5: return "coffee shop";
    default: return "?";
  }
}

void playTrack(uint8_t track) {
  if (track < 1 || track > NUM_TRACKS) return;

  uint32_t now = millis();
  uint32_t gap = (playbackStartMs == 0) ? 0 : (now - playbackStartMs);

  player.playMp3Folder(track);

  Serial.print("[");
  Serial.print(now);
  Serial.print("ms] -> 000");
  Serial.print(track);
  Serial.print(".mp3 (");
  Serial.print(trackName(track));
  Serial.print(")");
  if (playbackStartMs != 0) {
    Serial.print("  距上次啟動 ");
    Serial.print(gap / 1000);
    Serial.print(".");
    Serial.print((gap % 1000) / 100);
    Serial.print("s");
  }
  if (loopCount > 0) {
    Serial.print("  [loop #");
    Serial.print(loopCount);
    Serial.print("]");
  }
  Serial.println();

  playbackStartMs  = now;
  hasIssuedRestart = false;
}

void switchTrack(uint8_t newTrack) {
  if (newTrack < 1 || newTrack > NUM_TRACKS) return;
  Serial.print("\n=== 切換到音軌 ");
  Serial.print(newTrack);
  Serial.print(" (");
  Serial.print(trackName(newTrack));
  Serial.println(") ===");
  currentTrack = newTrack;
  loopCount = 0;
  playTrack(currentTrack);
}

void restartCurrentTrack() {
  loopCount++;
  playTrack(currentTrack);
}

void printStatus() {
  uint32_t elapsed = millis() - playbackStartMs;
  uint32_t total   = TRACK_DURATION_MS[currentTrack];
  uint32_t remain  = (elapsed < total) ? (total - elapsed) : 0;

  Serial.println("\n--- 狀態 ---");
  Serial.print("  音軌      : "); Serial.print(currentTrack);
  Serial.print(" ("); Serial.print(trackName(currentTrack)); Serial.println(")");
  Serial.print("  檔案      : 000"); Serial.print(currentTrack); Serial.println(".mp3");
  Serial.print("  總長      : "); Serial.print(total / 60000); Serial.print(":00 (");
  Serial.print(total / 1000); Serial.println(" s)");
  Serial.print("  已播      : "); Serial.print(elapsed / 60000); Serial.print(":");
  uint32_t secPart = (elapsed % 60000) / 1000;
  if (secPart < 10) Serial.print("0");
  Serial.print(secPart); Serial.print(" (");
  Serial.print(elapsed / 1000); Serial.println(" s)");
  Serial.print("  剩餘      : "); Serial.print(remain / 60000); Serial.print(":");
  secPart = (remain % 60000) / 1000;
  if (secPart < 10) Serial.print("0");
  Serial.print(secPart); Serial.println();
  Serial.print("  音量      : "); Serial.println(volume);
  Serial.print("  循環次數  : "); Serial.println(loopCount);
  Serial.print("  BUSY pin  : "); Serial.println(digitalRead(DFPLAYER_BUSY) == LOW ? "LOW (播放中)" : "HIGH (閒置)");
  Serial.println();
}

void printHelp() {
  Serial.println("\n--- 指令說明 ---");
  Serial.println("  1~5    切換音軌");
  Serial.println("         1=camp fire  2=dark noise  3=ocean");
  Serial.println("         4=rainny     5=coffee shop");
  Serial.println("  v18    設定音量 (0~30)");
  Serial.println("  s      顯示狀態");
  Serial.println("  r      立即從頭重播");
  Serial.println("  ?      指令說明");
  Serial.println();
}

// === Serial 指令處理 ===
void handleSerial() {
  if (!Serial.available()) return;
  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.length() == 0) return;

  char c = line.charAt(0);

  if (c >= '1' && c <= '5') {
    switchTrack(c - '0');
  }
  else if (c == 'v' || c == 'V') {
    int v = line.substring(1).toInt();
    if (v >= 0 && v <= 30) {
      volume = v;
      player.volume(volume);
      Serial.print("音量 = "); Serial.println(volume);
    }
  }
  else if (c == 's' || c == 'S') {
    printStatus();
  }
  else if (c == 'r' || c == 'R') {
    Serial.println("[手動] 重新播放目前音軌");
    restartCurrentTrack();
  }
  else if (c == '?') {
    printHelp();
  }
}

// === Setup ===
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n\n===== DFPlayer Mini 30 分鐘白噪音循環播放 =====");
  Serial.println("SD 卡 /mp3/ 資料夾需放置 0001~0005.mp3");
  Serial.println("每個檔案為 30 分鐘白噪音，播完自動重播\n");

  pinMode(DFPLAYER_BUSY, INPUT);

  dfSerial.begin(9600, SERIAL_8N1, DFPLAYER_RX_PIN, DFPLAYER_TX_PIN);
  delay(200);

  Serial.println("初始化 DFPlayer...");
  if (!player.begin(dfSerial, /*isACK=*/true, /*doReset=*/true)) {
    Serial.println("  !! 失敗。請檢查：");
    Serial.println("     - SD 卡是否插入且為 FAT32");
    Serial.println("     - TX/RX 是否交叉接 (ESP32 TX -> DFPlayer RX)");
    Serial.println("     - 5V 電源是否供電穩定");
    Serial.println("     - /mp3/ 資料夾是否存在且包含 0001~0005.mp3");
    while (true) delay(1000);
  }
  Serial.println("DFPlayer 就緒");

  player.volume(volume);
  player.EQ(DFPLAYER_EQ_NORMAL);
  delay(100);

  printHelp();
  switchTrack(DEFAULT_TRACK);
}

// === Loop ===
void loop() {
  handleSerial();

  uint32_t elapsed  = millis() - playbackStartMs;
  uint32_t expected = TRACK_DURATION_MS[currentTrack];

  // ── 定時主動重播 ──
  // 在預計結束前 RESTART_BEFORE_END_MS 發出重播指令
  if (!hasIssuedRestart && elapsed + RESTART_BEFORE_END_MS >= expected) {
    hasIssuedRestart = true;
    Serial.println("[自動] 30 分鐘到，重新循環播放");
    restartCurrentTrack();
    return;
  }

  // ── BUSY 兜底 ──
  // 如果定時切已觸發但 DFPlayer 意外提前結束播放，用 BUSY pin 偵測補救
  if (hasIssuedRestart && elapsed > expected + 1000 && digitalRead(DFPLAYER_BUSY) == HIGH) {
    Serial.println("[兜底] BUSY 偵測到播放結束，重新播放");
    restartCurrentTrack();
    return;
  }

  // ── 終極兜底 ──
  // 超過預期時間太久（可能指令丟失）
  if (elapsed > expected + 5000) {
    Serial.println("[警告] 超時兜底，重新播放");
    restartCurrentTrack();
    return;
  }

  delay(50);  // 30 分鐘檔案不需要太頻繁的輪詢
}
