/* Project: DFPlayer Mini 循環接縫測試 (Tail+Head 版本) v2
 * Target:  ESP32 DevKit (原版)
 * Framework: Arduino (ESP32 board package)
 * Libraries: DFRobotDFPlayerMini @ 1.0.6
 *
 * v2 改動 (相對於 v1)：
 *   - 改用實測檔案長度 (毫秒級) 做主動提前切換
 *   - 預設 switchBeforeEndMs = 200，避開 DFPlayer 開檔延遲造成的大 gap
 *   - 拿掉 BUSY pin 主動觸發 (測試證實 gap 會被放大到 ~1500ms)，
 *     改為「定時主動切」+ 「BUSY 兜底」雙保險
 *   - 新增 'B' 指令可切換到「純 BUSY 模式」做對照組
 *
 *   檔案命名規則：
 *     /mp3/0011.mp3 ~ /mp3/0052.mp3
 *     十位數 = 音軌 (1~5)，個位數 1=tail, 2=head
 *
 *   音軌對應：
 *     1 = camp fire   (營火)
 *     2 = dark noise  (暗噪音)
 *     3 = ocean       (海洋)
 *     4 = rainny      (下雨)
 *     5 = coffee shop (咖啡廳)
 *
 *   ┌────────┬────────────────────────────────────────┐
 *   │ 檔案   │ 內容                                   │
 *   ├────────┼────────────────────────────────────────┤
 *   │ 0011   │ camp fire   — tail (尾段 ~10s)         │
 *   │ 0012   │ camp fire   — head (頭段 ~5s)          │
 *   │ 0021   │ dark noise  — tail (尾段 ~10s)         │
 *   │ 0022   │ dark noise  — head (頭段 ~5s)          │
 *   │ 0031   │ ocean       — tail (尾段 ~10s)         │
 *   │ 0032   │ ocean       — head (頭段 ~5s)          │
 *   │ 0041   │ rainny      — tail (尾段 ~10s)         │
 *   │ 0042   │ rainny      — head (頭段 ~5s)          │
 *   │ 0051   │ coffee shop — tail (尾段 ~10s)         │
 *   │ 0052   │ coffee shop — head (頭段 ~5s)          │
 *   └────────┴────────────────────────────────────────┘
 *
 * Serial 指令 (115200 baud, 行尾 Newline):
 *   1 ~ 5 : 切換音軌
 *   +     : 提前切換時機 +50ms (最多 1000ms)
 *   -     : 提前切換時機 -50ms (最少 0ms)
 *   v 數字: 設定音量 (0~30)，例如 v18
 *   B     : 切換 BUSY 偵測模式 (預設 OFF)
 *   s     : 顯示目前狀態
 *   b     : 立即手動切到下一段
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
#define DEFAULT_TRACK  3

// === 各檔案實測長度 (毫秒)，從 ffprobe 量得 ===
// tail 約 10s、head 約 5s。這是「主動提前切換」的計算基準。
const uint32_t TAIL_DURATION_MS[6] = { 0, 10000, 10031, 10031, 10031, 10031 }; // index 0 unused
const uint32_t HEAD_DURATION_MS[6] = { 0,  5042,  5042,  5042,  5042,  5042 };

HardwareSerial dfSerial(2);
DFRobotDFPlayerMini player;

// === 執行期狀態 ===
uint8_t  currentTrack       = DEFAULT_TRACK;
bool     playingTail        = true;
uint16_t switchBeforeEndMs  = 200;            // 預設提前 200ms
uint32_t segmentStartMs     = 0;
uint8_t  volume             = DEFAULT_VOLUME;
bool     hasIssuedNext      = false;
uint32_t lastSwitchMs       = 0;
bool     useBusyMode        = false;          // 預設 OFF

// === Helpers ===
uint16_t fileIndex(uint8_t track, bool tail) {
  return (uint16_t)track * 10 + (tail ? 1 : 2);
}

uint32_t segmentDuration(uint8_t track, bool tail) {
  return tail ? TAIL_DURATION_MS[track] : HEAD_DURATION_MS[track];
}

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

void playSegment(uint8_t track, bool tail) {
  uint16_t idx       = fileIndex(track, tail);
  uint32_t now       = millis();
  uint32_t gap       = (lastSwitchMs == 0) ? 0 : (now - lastSwitchMs);
  // 上一段 = 即將切換之前正在播的那段，等於目前 playingTail
  uint32_t prevDur   = segmentDuration(track, playingTail);

  player.playMp3Folder(idx);

  Serial.print("[");
  Serial.print(now);
  Serial.print("ms] -> 0");
  if (idx < 1000) Serial.print("0");
  Serial.print(idx);
  Serial.print(".mp3 (");
  Serial.print(trackName(track));
  Serial.print(" ");
  Serial.print(tail ? "tail" : "head");
  Serial.print(")");
  if (lastSwitchMs != 0) {
    int32_t delta = (int32_t)gap - (int32_t)prevDur;
    Serial.print("  距上次 ");
    Serial.print(gap);
    Serial.print("ms (預期 ");
    Serial.print(prevDur);
    Serial.print("ms, 偏差 ");
    if (delta >= 0) Serial.print("+");
    Serial.print(delta);
    Serial.print("ms)");
  }
  Serial.println();

  segmentStartMs = now;
  lastSwitchMs   = now;
  playingTail    = tail;
  hasIssuedNext  = false;
}

void advanceToNext() {
  bool nextIsTail = !playingTail;  // tail<->head 來回
  playSegment(currentTrack, nextIsTail);
}

void switchTrack(uint8_t newTrack) {
  if (newTrack < 1 || newTrack > 5) return;
  Serial.print("\n=== 切換到音軌 ");
  Serial.print(newTrack);
  Serial.print(" (");
  Serial.print(trackName(newTrack));
  Serial.println(") ===");
  currentTrack = newTrack;
  lastSwitchMs = 0;
  playSegment(currentTrack, true);
}

void printStatus() {
  Serial.println("\n--- 狀態 ---");
  Serial.print("  音軌    : "); Serial.print(currentTrack);
  Serial.print(" ("); Serial.print(trackName(currentTrack)); Serial.println(")");
  Serial.print("  段落    : "); Serial.println(playingTail ? "tail" : "head");
  Serial.print("  本段預估: "); Serial.print(segmentDuration(currentTrack, playingTail)); Serial.println(" ms");
  Serial.print("  本段已播: "); Serial.print(millis() - segmentStartMs); Serial.println(" ms");
  Serial.print("  音量    : "); Serial.println(volume);
  Serial.print("  提前切換: "); Serial.print(switchBeforeEndMs); Serial.println(" ms");
  Serial.print("  BUSY 模式: "); Serial.println(useBusyMode ? "ON" : "OFF");
  Serial.print("  BUSY pin: "); Serial.println(digitalRead(DFPLAYER_BUSY) == LOW ? "LOW (播放中)" : "HIGH (閒置)");
  Serial.println();
}

void printHelp() {
  Serial.println("\n--- 指令說明 ---");
  Serial.println("  1~5    切換音軌");
  Serial.println("  +/-    調整提前切換時機 (±50ms)");
  Serial.println("  v18    設定音量 (0~30)");
  Serial.println("  B      切換 BUSY 偵測模式 (預設 OFF)");
  Serial.println("  s      顯示狀態");
  Serial.println("  b      手動切到下一段");
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
  else if (c == '+') {
    if (switchBeforeEndMs <= 950) switchBeforeEndMs += 50;
    Serial.print("提前切換 = "); Serial.print(switchBeforeEndMs); Serial.println(" ms");
  }
  else if (c == '-') {
    if (switchBeforeEndMs >= 50) switchBeforeEndMs -= 50;
    else switchBeforeEndMs = 0;
    Serial.print("提前切換 = "); Serial.print(switchBeforeEndMs); Serial.println(" ms");
  }
  else if (c == 'v' || c == 'V') {
    int v = line.substring(1).toInt();
    if (v >= 0 && v <= 30) {
      volume = v;
      player.volume(volume);
      Serial.print("音量 = "); Serial.println(volume);
    }
  }
  else if (c == 'B') {
    useBusyMode = !useBusyMode;
    Serial.print("BUSY 模式 = "); Serial.println(useBusyMode ? "ON (等播完才切)" : "OFF (定時主動切)");
  }
  else if (c == 's' || c == 'S') {
    printStatus();
  }
  else if (c == 'b') {
    Serial.println("[手動] 強制切到下一段");
    advanceToNext();
  }
  else if (c == '?') {
    printHelp();
  }
}

// === Setup ===
void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n\n===== DFPlayer Mini 循環接縫測試 v2 =====");

  pinMode(DFPLAYER_BUSY, INPUT);

  dfSerial.begin(9600, SERIAL_8N1, DFPLAYER_RX_PIN, DFPLAYER_TX_PIN);
  delay(200);

  Serial.println("初始化 DFPlayer...");
  if (!player.begin(dfSerial, /*isACK=*/true, /*doReset=*/true)) {
    Serial.println("  !! 失敗。請檢查：");
    Serial.println("     - SD 卡是否插入且為 FAT32");
    Serial.println("     - TX/RX 是否交叉接 (ESP32 TX -> DFPlayer RX)");
    Serial.println("     - 5V 電源是否供電穩定");
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

  uint32_t elapsed  = millis() - segmentStartMs;
  uint32_t expected = segmentDuration(currentTrack, playingTail);

  if (useBusyMode) {
    // 對照組：純 BUSY 偵測 (gap 較大)
    if (elapsed > 500 && digitalRead(DFPLAYER_BUSY) == HIGH) {
      advanceToNext();
      return;
    }
    if (elapsed > expected + 2000) {
      Serial.println("[警告] BUSY 模式超時兜底");
      advanceToNext();
      return;
    }
  } else {
    // 主模式：定時主動切換
    if (!hasIssuedNext && elapsed + switchBeforeEndMs >= expected) {
      hasIssuedNext = true;
      advanceToNext();
      return;
    }
    // BUSY 兜底：定時切完還沒成功 (例如指令掉了) 用 BUSY 救
    if (hasIssuedNext && elapsed > expected + 300 && digitalRead(DFPLAYER_BUSY) == HIGH) {
      Serial.println("[兜底] BUSY 觸發補切");
      advanceToNext();
      return;
    }
    // 終極兜底
    if (elapsed > expected + 2000) {
      Serial.println("[警告] 超時兜底切換");
      advanceToNext();
      return;
    }
  }

  delay(5);
}
