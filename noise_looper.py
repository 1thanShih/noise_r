"""
White Noise Looper — 白噪音循環銜接工具
========================================
功能：
  1. 載入白噪音音檔（WAV / FLAC / OGG）
  2. 以交叉淡化（crossfade）方式無縫循環至指定時長
  3. RMS 音量標準化
  4. 匯出處理後音檔

作者：Antigravity AI Assistant
"""

import os
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path

import customtkinter as ctk
import numpy as np
import soundfile as sf

# ─────────────────── 音訊處理核心 ───────────────────

class AudioProcessor:
    """白噪音循環銜接 + RMS 標準化處理器"""

    def __init__(self):
        self.source_data: np.ndarray | None = None
        self.sample_rate: int = 0
        self.channels: int = 0
        self.source_path: str = ""

    def load(self, filepath: str) -> dict:
        """載入音檔，回傳音檔資訊"""
        data, sr = sf.read(filepath, dtype="float64")
        if data.ndim == 1:
            data = data[:, np.newaxis]  # mono → (N, 1)
        self.source_data = data
        self.sample_rate = sr
        self.channels = data.shape[1]
        self.source_path = filepath
        duration = len(data) / sr
        return {
            "filename": Path(filepath).name,
            "sample_rate": sr,
            "channels": self.channels,
            "duration": round(duration, 2),
            "samples": len(data),
        }

    def process(
        self,
        target_seconds: float,
        crossfade_seconds: float = 2.0,
        target_rms_db: float = -20.0,
        progress_cb=None,
    ) -> np.ndarray:
        """
        核心處理流程
        1) 複製 + crossfade 拼接至目標時長
        2) RMS 標準化
        """
        if self.source_data is None:
            raise RuntimeError("尚未載入音檔")

        src = self.source_data
        sr = self.sample_rate
        fade_samples = int(crossfade_seconds * sr)
        src_len = len(src)

        # 若 crossfade 長度 >= 原始音檔長度的一半，自動縮減
        if fade_samples >= src_len // 2:
            fade_samples = src_len // 4
            if fade_samples < 1:
                fade_samples = 1

        target_samples = int(target_seconds * sr)

        # ── Step 1: 建立可循環的單段（去除 crossfade 重疊區的有效長度） ──
        effective_len = src_len - fade_samples  # 每次迴圈實際推進的取樣數

        if target_samples <= src_len:
            # 目標比原始短或一樣長 → 直接截取 + 淡出
            result = src[:target_samples].copy()
            # 加一個短淡入淡出避免 click
            _apply_fade(result, min(fade_samples, target_samples // 4), sr)
        else:
            # 需要循環拼接
            result = np.zeros((target_samples, self.channels), dtype=np.float64)
            pos = 0
            iteration = 0
            total_iterations = (target_samples // effective_len) + 2

            while pos < target_samples:
                remaining = target_samples - pos
                chunk_len = min(src_len, remaining)
                chunk = src[:chunk_len].copy()

                if pos == 0:
                    # 第一段：直接放入
                    result[:chunk_len] = chunk
                else:
                    # 交叉淡化區域
                    actual_fade = min(fade_samples, pos, chunk_len)
                    if actual_fade > 0:
                        fade_in = np.linspace(0.0, 1.0, actual_fade)[:, np.newaxis]
                        fade_out = np.linspace(1.0, 0.0, actual_fade)[:, np.newaxis]
                        # 淡出前一段尾巴
                        result[pos : pos + actual_fade] *= fade_out
                        # 淡入新段開頭
                        chunk[:actual_fade] *= fade_in
                        # 混合
                        result[pos : pos + actual_fade] += chunk[:actual_fade]
                    # 非重疊區域直接寫入
                    if actual_fade < chunk_len:
                        write_end = min(pos + chunk_len, target_samples)
                        write_len = write_end - (pos + actual_fade)
                        result[pos + actual_fade : pos + actual_fade + write_len] = (
                            chunk[actual_fade : actual_fade + write_len]
                        )

                pos += effective_len
                iteration += 1
                if progress_cb:
                    progress_cb(min(iteration / total_iterations * 0.7, 0.7))

            # 結尾淡出，避免突然截斷
            tail_fade = min(fade_samples, target_samples // 8)
            if tail_fade > 1:
                fade_out_tail = np.linspace(1.0, 0.0, tail_fade)[:, np.newaxis]
                result[-tail_fade:] *= fade_out_tail

        if progress_cb:
            progress_cb(0.75)

        # ── Step 2: RMS 標準化 ──
        result = _rms_normalize(result, target_rms_db)

        if progress_cb:
            progress_cb(1.0)

        return result

    def export(self, data: np.ndarray, output_path: str, fmt: str = "WAV", subtype: str = "PCM_24", mp3_bitrate: int = 320):
        """匯出處理後音檔（支援 WAV / FLAC / MP3）"""
        mono = data[:, 0] if data.shape[1] == 1 else data

        if fmt == "MP3":
            # MP3：先寫暫存 WAV，再用 ffmpeg 轉檔
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                sf.write(tmp_path, mono, self.sample_rate, format="WAV", subtype="PCM_24")
                cmd = [
                    "ffmpeg", "-y", "-i", tmp_path,
                    "-codec:a", "libmp3lame",
                    "-b:a", f"{mp3_bitrate}k",
                    "-q:a", "0",
                    output_path,
                ]
                result = subprocess.run(
                    cmd, capture_output=True, text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                if result.returncode != 0:
                    raise RuntimeError(f"ffmpeg 錯誤:\n{result.stderr[:500]}")
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        else:
            sf.write(output_path, mono, self.sample_rate, format=fmt, subtype=subtype)


def _apply_fade(data: np.ndarray, fade_samples: int, sr: int):
    """對音訊頭尾施加淡入淡出"""
    if fade_samples < 1:
        return
    fade_in = np.linspace(0.0, 1.0, fade_samples)[:, np.newaxis]
    fade_out = np.linspace(1.0, 0.0, fade_samples)[:, np.newaxis]
    data[:fade_samples] *= fade_in
    data[-fade_samples:] *= fade_out


def _rms_normalize(data: np.ndarray, target_db: float = -20.0) -> np.ndarray:
    """RMS 標準化至目標 dB"""
    rms = np.sqrt(np.mean(data ** 2))
    if rms < 1e-10:
        return data  # 靜音不處理
    target_rms = 10 ** (target_db / 20.0)
    gain = target_rms / rms
    result = data * gain
    # 限幅防爆音
    peak = np.max(np.abs(result))
    if peak > 0.99:
        result *= 0.99 / peak
    return result


# ─────────────────── GUI 介面 ───────────────────

# 色彩系統
COLORS = {
    "bg_dark":       "#0F0F14",
    "bg_card":       "#1A1A24",
    "bg_input":      "#12121A",
    "accent":        "#6C5CE7",
    "accent_hover":  "#7E6FF0",
    "accent_dim":    "#4A3FB5",
    "success":       "#00D2A0",
    "warning":       "#FDCB6E",
    "error":         "#FF6B6B",
    "text_primary":  "#E8E8F0",
    "text_secondary":"#8888A0",
    "text_dim":      "#55556A",
    "border":        "#2A2A3A",
    "progress_bg":   "#1E1E2E",
}


class NoiseLooperApp(ctk.CTk):
    """白噪音循環銜接工具 — 主介面"""

    def __init__(self):
        super().__init__()
        self.processor = AudioProcessor()
        self._setup_window()
        self._build_ui()
        self._source_info: dict | None = None
        self._processed_data: np.ndarray | None = None

    # ── 視窗設定 ──
    def _setup_window(self):
        self.title("🎧 Noise Looper — 白噪音循環銜接工具")
        self.geometry("700x860")
        self.minsize(600, 500)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.configure(fg_color=COLORS["bg_dark"])

    # ── 建構 UI ──
    def _build_ui(self):
        # 底部固定區域（進度條 + 狀態）—— 先 pack 確保不被擠掉
        bottom_bar = ctk.CTkFrame(self, fg_color=COLORS["bg_card"], corner_radius=0, height=60)
        bottom_bar.pack(side="bottom", fill="x")
        bottom_bar.pack_propagate(False)

        bottom_inner = ctk.CTkFrame(bottom_bar, fg_color="transparent")
        bottom_inner.pack(fill="both", expand=True, padx=24, pady=(8, 10))

        self.progress = ctk.CTkProgressBar(
            bottom_inner, height=6,
            fg_color=COLORS["progress_bg"], progress_color=COLORS["success"],
        )
        self.progress.pack(fill="x", pady=(0, 4))
        self.progress.set(0)

        self.status_label = ctk.CTkLabel(
            bottom_inner, text="就緒",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_dim"], anchor="w",
        )
        self.status_label.pack(fill="x")

        # 可捲動主容器
        container = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["accent_dim"],
        )
        container.pack(fill="both", expand=True, padx=24, pady=(20, 8))

        # ── 標題 ──
        title_frame = ctk.CTkFrame(container, fg_color="transparent")
        title_frame.pack(fill="x", pady=(0, 16))
        ctk.CTkLabel(
            title_frame, text="🎧 Noise Looper",
            font=ctk.CTkFont(family="Segoe UI", size=28, weight="bold"),
            text_color=COLORS["text_primary"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_frame, text="白噪音循環銜接 ∙ RMS 標準化 ∙ 無縫 Crossfade",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=COLORS["text_secondary"],
        ).pack(anchor="w", pady=(2, 0))

        # ── 1) 輸入區 ──
        self._build_section_label(container, "① 選擇音檔")
        input_card = self._card(container)

        file_row = ctk.CTkFrame(input_card, fg_color="transparent")
        file_row.pack(fill="x", pady=4)

        self.file_label = ctk.CTkLabel(
            file_row, text="尚未選擇檔案",
            font=ctk.CTkFont(size=13),
            text_color=COLORS["text_dim"],
            anchor="w",
        )
        self.file_label.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.btn_browse = ctk.CTkButton(
            file_row, text="瀏覽…", width=90,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            command=self._on_browse,
        )
        self.btn_browse.pack(side="right")

        # 音檔資訊
        self.info_label = ctk.CTkLabel(
            input_card, text="",
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color=COLORS["text_secondary"],
            anchor="w", justify="left",
        )
        self.info_label.pack(fill="x", pady=(8, 0))

        # ── 2) 參數設定 ──
        self._build_section_label(container, "② 參數設定")
        params_card = self._card(container)

        # 目標時長
        dur_frame = ctk.CTkFrame(params_card, fg_color="transparent")
        dur_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(
            dur_frame, text="目標時長",
            font=ctk.CTkFont(size=13), text_color=COLORS["text_primary"],
        ).pack(side="left")
        self.dur_unit = ctk.CTkSegmentedButton(
            dur_frame, values=["秒", "分鐘", "小時"],
            font=ctk.CTkFont(size=12),
            selected_color=COLORS["accent"],
            selected_hover_color=COLORS["accent_hover"],
            unselected_color=COLORS["bg_input"],
            unselected_hover_color=COLORS["border"],
            command=self._on_unit_change,
        )
        self.dur_unit.set("分鐘")
        self.dur_unit.pack(side="right")

        dur_input_frame = ctk.CTkFrame(params_card, fg_color="transparent")
        dur_input_frame.pack(fill="x", pady=(4, 8))
        self.dur_slider = ctk.CTkSlider(
            dur_input_frame, from_=1, to=120, number_of_steps=119,
            fg_color=COLORS["progress_bg"], progress_color=COLORS["accent"],
            button_color=COLORS["accent"], button_hover_color=COLORS["accent_hover"],
            command=self._on_dur_slider,
        )
        self.dur_slider.set(30)
        self.dur_slider.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self.dur_entry = ctk.CTkEntry(
            dur_input_frame, width=72, justify="center",
            font=ctk.CTkFont(family="Consolas", size=14),
            fg_color=COLORS["bg_input"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
        )
        self.dur_entry.insert(0, "30")
        self.dur_entry.pack(side="right")
        self.dur_entry.bind("<Return>", self._on_dur_entry)
        self.dur_entry.bind("<FocusOut>", self._on_dur_entry)

        self.dur_preview = ctk.CTkLabel(
            params_card, text="＝ 30 分鐘 (1800 秒)",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_dim"], anchor="w",
        )
        self.dur_preview.pack(fill="x", pady=(0, 8))

        # 分隔線
        ctk.CTkFrame(params_card, height=1, fg_color=COLORS["border"]).pack(fill="x", pady=8)

        # Crossfade 時長
        cf_frame = ctk.CTkFrame(params_card, fg_color="transparent")
        cf_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(
            cf_frame, text="交叉淡化 (Crossfade)",
            font=ctk.CTkFont(size=13), text_color=COLORS["text_primary"],
        ).pack(side="left")
        self.cf_value_label = ctk.CTkLabel(
            cf_frame, text="2.0 秒",
            font=ctk.CTkFont(family="Consolas", size=13, weight="bold"),
            text_color=COLORS["accent"],
        )
        self.cf_value_label.pack(side="right")

        self.cf_slider = ctk.CTkSlider(
            params_card, from_=0.5, to=5.0, number_of_steps=18,
            fg_color=COLORS["progress_bg"], progress_color=COLORS["accent"],
            button_color=COLORS["accent"], button_hover_color=COLORS["accent_hover"],
            command=self._on_cf_slider,
        )
        self.cf_slider.set(2.0)
        self.cf_slider.pack(fill="x", pady=(4, 8))

        # 分隔線
        ctk.CTkFrame(params_card, height=1, fg_color=COLORS["border"]).pack(fill="x", pady=8)

        # RMS 目標
        rms_frame = ctk.CTkFrame(params_card, fg_color="transparent")
        rms_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(
            rms_frame, text="RMS 目標音量",
            font=ctk.CTkFont(size=13), text_color=COLORS["text_primary"],
        ).pack(side="left")
        self.rms_value_label = ctk.CTkLabel(
            rms_frame, text="-20 dB",
            font=ctk.CTkFont(family="Consolas", size=13, weight="bold"),
            text_color=COLORS["accent"],
        )
        self.rms_value_label.pack(side="right")

        self.rms_slider = ctk.CTkSlider(
            params_card, from_=-40, to=-6, number_of_steps=34,
            fg_color=COLORS["progress_bg"], progress_color=COLORS["accent"],
            button_color=COLORS["accent"], button_hover_color=COLORS["accent_hover"],
            command=self._on_rms_slider,
        )
        self.rms_slider.set(-20)
        self.rms_slider.pack(fill="x", pady=(4, 8))

        # ── 3) 輸出設定 ──
        self._build_section_label(container, "③ 輸出設定")
        out_card = self._card(container)

        # 輸出格式
        fmt_frame = ctk.CTkFrame(out_card, fg_color="transparent")
        fmt_frame.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            fmt_frame, text="格式",
            font=ctk.CTkFont(size=13), text_color=COLORS["text_primary"],
        ).pack(side="left")
        self.fmt_menu = ctk.CTkSegmentedButton(
            fmt_frame, values=["WAV (24bit)", "WAV (16bit)", "FLAC", "MP3"],
            font=ctk.CTkFont(size=12),
            selected_color=COLORS["accent"],
            selected_hover_color=COLORS["accent_hover"],
            unselected_color=COLORS["bg_input"],
            unselected_hover_color=COLORS["border"],
            command=self._on_fmt_change,
        )
        self.fmt_menu.set("WAV (24bit)")
        self.fmt_menu.pack(side="right")

        # 分隔線
        ctk.CTkFrame(out_card, height=1, fg_color=COLORS["border"]).pack(fill="x", pady=6)

        # 輸出檔名
        name_header = ctk.CTkFrame(out_card, fg_color="transparent")
        name_header.pack(fill="x", pady=(4, 4))
        ctk.CTkLabel(
            name_header, text="檔案名稱",
            font=ctk.CTkFont(size=13), text_color=COLORS["text_primary"],
        ).pack(side="left")
        # 副檔名指示
        self.ext_badge = ctk.CTkLabel(
            name_header, text=".wav",
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color=COLORS["accent"],
            fg_color=COLORS["bg_input"],
            corner_radius=6, width=48,
        )
        self.ext_badge.pack(side="right", padx=(4, 0))

        self.out_name_entry = ctk.CTkEntry(
            out_card, height=36,
            font=ctk.CTkFont(family="Consolas", size=13),
            fg_color=COLORS["bg_input"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            placeholder_text="輸出檔名（不含副檔名）",
            placeholder_text_color=COLORS["text_dim"],
        )
        self.out_name_entry.pack(fill="x", pady=(0, 10))

        # 分隔線
        ctk.CTkFrame(out_card, height=1, fg_color=COLORS["border"]).pack(fill="x", pady=6)

        # 輸出目錄
        dir_header = ctk.CTkFrame(out_card, fg_color="transparent")
        dir_header.pack(fill="x", pady=(4, 4))
        ctk.CTkLabel(
            dir_header, text="輸出位置",
            font=ctk.CTkFont(size=13), text_color=COLORS["text_primary"],
        ).pack(side="left")
        self.btn_dir = ctk.CTkButton(
            dir_header, text="選擇資料夾", width=100,
            height=28, font=ctk.CTkFont(size=12),
            fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            command=self._on_choose_dir,
        )
        self.btn_dir.pack(side="right")

        # 路徑顯示
        self._output_dir = ""
        self.dir_path_label = ctk.CTkLabel(
            out_card, text="尚未選擇（將使用音檔所在目錄）",
            font=ctk.CTkFont(family="Consolas", size=11),
            text_color=COLORS["text_dim"],
            anchor="w", wraplength=560,
        )
        self.dir_path_label.pack(fill="x", pady=(0, 4))

        # ── 4) 執行 ──
        action_frame = ctk.CTkFrame(container, fg_color="transparent")
        action_frame.pack(fill="x", pady=(20, 4))

        self.btn_process = ctk.CTkButton(
            action_frame, text="▶  開始轉檔", height=48,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            command=self._on_process,
        )
        self.btn_process.pack(fill="x")

    # ── UI 輔助 ──
    def _card(self, parent) -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            parent,
            fg_color=COLORS["bg_card"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        card.pack(fill="x", pady=(0, 8))
        # 內距
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=14)
        return inner

    def _build_section_label(self, parent, text: str):
        ctk.CTkLabel(
            parent, text=text,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text_secondary"],
        ).pack(anchor="w", pady=(12, 4))

    # ── 事件處理 ──
    def _on_browse(self):
        filepath = filedialog.askopenfilename(
            title="選擇白噪音音檔",
            filetypes=[
                ("音訊檔案", "*.wav *.flac *.ogg *.mp3"),
                ("WAV", "*.wav"),
                ("FLAC", "*.flac"),
                ("OGG", "*.ogg"),
                ("所有檔案", "*.*"),
            ],
        )
        if not filepath:
            return
        try:
            info = self.processor.load(filepath)
            self._source_info = info
            self.file_label.configure(
                text=info["filename"],
                text_color=COLORS["text_primary"],
            )
            ch_str = "Mono" if info["channels"] == 1 else f'{info["channels"]}ch'
            self.info_label.configure(
                text=f'{info["sample_rate"]} Hz  ·  {ch_str}  ·  {info["duration"]} 秒  ·  {info["samples"]:,} samples'
            )
            self._set_status(f"已載入: {info['filename']}", COLORS["success"])
            # 自動填入預設輸出名稱
            self._update_output_name()
        except Exception as e:
            messagebox.showerror("載入失敗", str(e))

    def _on_unit_change(self, value):
        self._update_dur_preview()

    def _on_dur_slider(self, value):
        v = int(round(value))
        self.dur_entry.delete(0, "end")
        self.dur_entry.insert(0, str(v))
        self._update_dur_preview()

    def _on_dur_entry(self, event=None):
        try:
            v = float(self.dur_entry.get())
            v = max(1, min(v, 999))
            self.dur_slider.set(min(v, 120))
        except ValueError:
            pass
        self._update_dur_preview()

    def _update_dur_preview(self):
        try:
            v = float(self.dur_entry.get())
        except ValueError:
            v = 30
        unit = self.dur_unit.get()
        if unit == "秒":
            total_sec = v
        elif unit == "分鐘":
            total_sec = v * 60
        else:  # 小時
            total_sec = v * 3600
        # 格式化顯示
        if total_sec >= 3600:
            h = int(total_sec // 3600)
            m = int((total_sec % 3600) // 60)
            s = int(total_sec % 60)
            display = f"＝ {h} 小時 {m} 分 {s} 秒 ({int(total_sec)} 秒)"
        elif total_sec >= 60:
            m = int(total_sec // 60)
            s = int(total_sec % 60)
            display = f"＝ {m} 分鐘 {s} 秒 ({int(total_sec)} 秒)"
        else:
            display = f"＝ {int(total_sec)} 秒"
        self.dur_preview.configure(text=display)

    def _on_cf_slider(self, value):
        v = round(value, 1)
        self.cf_value_label.configure(text=f"{v} 秒")

    def _on_fmt_change(self, value):
        """格式選擇變更時自動更新副檔名指示與檔名"""
        _, _, ext = self._get_output_format()
        self.ext_badge.configure(text=ext)
        self._update_output_name()

    def _on_choose_dir(self):
        """選擇輸出目錄"""
        d = filedialog.askdirectory(title="選擇輸出目錄")
        if d:
            self._output_dir = d
            # 顯示縮短路徑
            display = d
            if len(display) > 60:
                display = "…" + display[-57:]
            self.dir_path_label.configure(
                text=display,
                text_color=COLORS["text_secondary"],
            )

    def _update_output_name(self):
        """根據來源檔名與目標時長自動產生輸出名稱"""
        if self._source_info is None:
            return
        stem = Path(self.processor.source_path).stem
        try:
            sec = int(self._get_target_seconds())
        except Exception:
            sec = 0
        name = f"{stem}_loop_{sec}s"
        self.out_name_entry.delete(0, "end")
        self.out_name_entry.insert(0, name)

    def _on_rms_slider(self, value):
        v = int(round(value))
        self.rms_value_label.configure(text=f"{v} dB")

    def _get_target_seconds(self) -> float:
        try:
            v = float(self.dur_entry.get())
        except ValueError:
            v = 30
        unit = self.dur_unit.get()
        if unit == "秒":
            return v
        elif unit == "分鐘":
            return v * 60
        else:
            return v * 3600

    def _get_output_format(self) -> tuple[str, str, str]:
        """回傳 (format, subtype, extension)"""
        sel = self.fmt_menu.get()
        if sel == "WAV (16bit)":
            return ("WAV", "PCM_16", ".wav")
        elif sel == "FLAC":
            return ("FLAC", "PCM_24", ".flac")
        elif sel == "MP3":
            return ("MP3", "", ".mp3")
        else:
            return ("WAV", "PCM_24", ".wav")

    def _set_status(self, text: str, color: str = COLORS["text_dim"]):
        self.status_label.configure(text=text, text_color=color)

    def _set_ui_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.btn_browse.configure(state=state)
        self.btn_process.configure(state=state)
        self.dur_slider.configure(state=state)
        self.cf_slider.configure(state=state)
        self.rms_slider.configure(state=state)

    # ── 處理流程 ──
    def _on_process(self):
        if self.processor.source_data is None:
            messagebox.showwarning("提示", "請先選擇音檔！")
            return

        target_sec = self._get_target_seconds()
        if target_sec < 1:
            messagebox.showwarning("提示", "目標時長至少需要 1 秒！")
            return

        # 取得輸出名稱
        out_name = self.out_name_entry.get().strip()
        if not out_name:
            messagebox.showwarning("提示", "請輸入輸出檔案名稱！")
            return

        cf_sec = round(self.cf_slider.get(), 1)
        rms_db = int(round(self.rms_slider.get()))
        fmt, subtype, ext = self._get_output_format()

        # 決定輸出目錄
        out_dir = self._output_dir
        if not out_dir:
            out_dir = str(Path(self.processor.source_path).parent)

        output_path = os.path.join(out_dir, out_name + ext)

        # 檢查是否覆蓋
        if os.path.exists(output_path):
            overwrite = messagebox.askyesno(
                "檔案已存在",
                f"檔案已存在：\n{Path(output_path).name}\n\n是否覆蓋？",
            )
            if not overwrite:
                return

        self._set_ui_enabled(False)
        self.progress.set(0)
        self._set_status("處理中…", COLORS["warning"])
        self.btn_process.configure(text="⏳ 處理中…")

        def _worker():
            try:
                def _progress(val):
                    self.after(0, lambda v=val: self.progress.set(v))

                result = self.processor.process(
                    target_seconds=target_sec,
                    crossfade_seconds=cf_sec,
                    target_rms_db=float(rms_db),
                    progress_cb=_progress,
                )
                self.processor.export(result, output_path, fmt=fmt, subtype=subtype)
                self._processed_data = result

                output_dur = len(result) / self.processor.sample_rate
                result_rms = np.sqrt(np.mean(result ** 2))
                result_rms_db = 20 * np.log10(result_rms) if result_rms > 1e-10 else -100

                self.after(0, lambda: self._on_done(output_path, output_dur, result_rms_db))
            except Exception as e:
                self.after(0, lambda: self._on_error(str(e)))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_done(self, path: str, duration: float, rms_db: float):
        self._set_ui_enabled(True)
        self.progress.set(1.0)
        self.btn_process.configure(text="▶  開始轉檔")

        m = int(duration // 60)
        s = int(duration % 60)
        dur_str = f"{m}:{s:02d}" if m > 0 else f"{s} 秒"

        self._set_status(
            f"✅ 完成！ {dur_str}  ·  RMS {rms_db:.1f} dB  ·  已儲存",
            COLORS["success"],
        )
        messagebox.showinfo(
            "處理完成",
            f"已成功匯出！\n\n"
            f"📁 {Path(path).name}\n"
            f"⏱ 時長: {dur_str}\n"
            f"🔊 RMS: {rms_db:.1f} dB\n"
            f"📂 {path}",
        )

    def _on_error(self, msg: str):
        self._set_ui_enabled(True)
        self.progress.set(0)
        self.btn_process.configure(text="▶  開始轉檔")
        self._set_status(f"❌ 錯誤: {msg}", COLORS["error"])
        messagebox.showerror("處理失敗", msg)


# ─────────────────── 入口 ───────────────────

if __name__ == "__main__":
    app = NoiseLooperApp()
    app.mainloop()
