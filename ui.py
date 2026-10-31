# -*- coding: utf-8 -*-
"""
SpiderUika 图形界面（tkinter）

用法：
    python ui.py

设计要点：
  1. 爬虫跑在子线程，界面不卡
  2. 子线程通过 queue 把日志/进度传回主线程，只有主线程能碰控件
  3. 停止按钮用 threading.Event，爬虫循环里检查
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

from config import CHARACTERS, EXTRA_CHARACTERS
from tools import (make_session, fetch_character_data,
                   write_character_voice_json, build_id_to_speaker,
                   audio_to_list)
from story_scraper import story_scraper
from character_scraper import character_voice_scraper


class SpiderUikaApp:
    def __init__(self, root):
        self.root = root
        root.title("SpiderUika — bdon.moe 语音抓取")
        root.geometry("860x640")
        root.minsize(720, 520)

        # ---- 线程通信 ----
        self.msg_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.running = False

        # ---- 当前可选项 ----
        self.choice_map = {}          # 下拉框显示文本 -> (角色ID, 是否编外)

        self._build_ui()
        self._refresh_characters()

        # 启动队列轮询（主线程定时器）
        self.root.after(80, self._poll_queue)

    # ==================== 界面搭建 ====================
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # ---------- 第 1 区：选角色 ----------
        box1 = ttk.LabelFrame(self.root, text="1. 选择角色")
        box1.pack(fill="x", **pad)

        row = ttk.Frame(box1)
        row.pack(fill="x", padx=8, pady=6)

        ttk.Label(row, text="类型：").pack(side="left")

        self.kind_var = tk.StringVar(value="band")
        ttk.Radiobutton(row, text="编内（有角色卡）", value="band",
                        variable=self.kind_var,
                        command=self._refresh_characters).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(row, text="编外（仅剧情NPC）", value="extra",
                        variable=self.kind_var,
                        command=self._refresh_characters).pack(side="left")

        row2 = ttk.Frame(box1)
        row2.pack(fill="x", padx=8, pady=(0, 8))

        ttk.Label(row2, text="角色：").pack(side="left")
        self.char_combo = ttk.Combobox(row2, state="readonly", width=34)
        self.char_combo.pack(side="left")
        self.char_combo.bind("<<ComboboxSelected>>", lambda e: self._on_kind_changed())

        self.info_label = ttk.Label(row2, text="", foreground="#555")
        self.info_label.pack(side="left", padx=12)

        # ---------- 第 2 区：选任务 ----------
        box2 = ttk.LabelFrame(self.root, text="2. 选择任务")
        box2.pack(fill="x", **pad)

        self.task_story = tk.BooleanVar(value=True)
        self.task_voice = tk.BooleanVar(value=True)
        self.task_list = tk.BooleanVar(value=False)

        r3 = ttk.Frame(box2)
        r3.pack(fill="x", padx=8, pady=6)

        ttk.Checkbutton(r3, text="剧情语音", variable=self.task_story).pack(side="left")
        self.cb_voice = ttk.Checkbutton(r3, text="角色语音", variable=self.task_voice)
        self.cb_voice.pack(side="left", padx=16)
        ttk.Checkbutton(r3, text="生成训练列表（.list）", variable=self.task_list).pack(side="left")

        # ---------- 第 3 区：按钮 + 进度 ----------
        box3 = ttk.Frame(self.root)
        box3.pack(fill="x", **pad)

        self.btn_start = ttk.Button(box3, text="▶ 开始", command=self._on_start)
        self.btn_start.pack(side="left")

        self.btn_stop = ttk.Button(box3, text="■ 停止", command=self._on_stop,
                                   state="disabled")
        self.btn_stop.pack(side="left", padx=8)

        ttk.Button(box3, text="打开输出文件夹",
                   command=self._open_folder).pack(side="left", padx=8)

        ttk.Button(box3, text="清空日志",
                   command=self._clear_log).pack(side="left")

        self.progress = ttk.Progressbar(box3, mode="determinate", maximum=100)
        self.progress.pack(side="right", fill="x", expand=True, padx=(16, 0))

        self.progress_label = ttk.Label(box3, text="就绪", width=14, anchor="e")
        self.progress_label.pack(side="right", padx=(8, 0))

        # ---------- 第 4 区：日志 ----------
        box4 = ttk.LabelFrame(self.root, text="日志")
        box4.pack(fill="both", expand=True, **pad)

        self.log_text = scrolledtext.ScrolledText(box4, height=18, wrap="word",
                                                  font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True, padx=6, pady=6)
        self.log_text.configure(state="disabled")

    # ==================== 事件处理 ====================
    def _refresh_characters(self):
        """切换编内/编外时重建下拉列表"""
        self.choice_map.clear()
        items = []

        if self.kind_var.get() == "band":
            base = CHARACTERS
        else:
            base = EXTRA_CHARACTERS

        for cid, info in sorted(base.items(), key=lambda kv: int(kv[0])):
            label = f"{info['name']}  ({cid})"
            self.choice_map[label] = (cid, self.kind_var.get() == "extra")
            items.append(label)

        self.char_combo["values"] = items
        if items:
            self.char_combo.current(0)

        self._on_kind_changed()

    def _on_kind_changed(self):
        """编外角色没有角色语音，禁用那个勾选框"""
        is_extra = self.kind_var.get() == "extra"
        self.cb_voice.configure(state="disabled" if is_extra else "normal")
        if is_extra:
            self.task_voice.set(False)

        label = self.char_combo.get()
        cid, _ = self.choice_map.get(label, (None, False))
        if cid:
            table = EXTRA_CHARACTERS if is_extra else CHARACTERS
            info = table[cid]
            sid = info.get("speaker_id") or "（由角色表推导）"
            self.info_label.configure(text=f"speakerId = {sid}")

    def _on_start(self):
        if self.running:
            return

        label = self.char_combo.get()
        if label not in self.choice_map:
            messagebox.showwarning("提示", "请先选择角色")
            return

        if not (self.task_story.get() or self.task_voice.get() or self.task_list.get()):
            messagebox.showwarning("提示", "至少勾选一个任务")
            return

        cid, is_extra = self.choice_map[label]

        self.running = True
        self.stop_event.clear()
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.progress["value"] = 0
        self.progress_label.configure(text="准备中…")

        args = {
            "cid": cid,
            "is_extra": is_extra,
            "do_story": self.task_story.get(),
            "do_voice": self.task_voice.get(),
            "do_list": self.task_list.get(),
        }

        threading.Thread(target=self._worker, kwargs=args, daemon=True).start()

    def _on_stop(self):
        if not self.running:
            return
        self.stop_event.set()
        self.progress_label.configure(text="正在停止…")
        self._push_log("⏹ 已发送停止信号，等待当前文件结束…")

    def _open_folder(self):
        label = self.char_combo.get()
        path = "."
        if label in self.choice_map:
            cid, is_extra = self.choice_map[label]
            table = EXTRA_CHARACTERS if is_extra else CHARACTERS
            path = table[cid]["short"]

        full = os.path.abspath(path)
        if not os.path.isdir(full):
            messagebox.showinfo("提示", f"文件夹还没创建：\n{full}")
            return

        try:
            os.startfile(full)          # Windows 专用
        except AttributeError:
            messagebox.showinfo("提示", f"请手动打开：\n{full}")

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # ==================== 后台工作线程 ====================
    def _worker(self, cid, is_extra, do_story, do_voice, do_list):
        try:
            self._push_log("=" * 60)
            session = make_session()

            self._push_log("下载 character-voices.json …")
            character_data = fetch_character_data(session)
            write_character_voice_json(character_data)
            n = len(character_data["sets"][character_data["servers"]["jp"]])
            self._push_log(f"  角色数：{n}")

            table = EXTRA_CHARACTERS if is_extra else CHARACTERS
            info = table[cid]

            if is_extra:
                speaker_id = info["speaker_id"]
            else:
                speaker_id = build_id_to_speaker()[cid]

            self._push_log(f"角色：{info['name']}（{'编外' if is_extra else '编内'}）")
            self._push_log(f"speakerId：{speaker_id}")
            self._push_log("")

            if do_story:
                self._push_log("——— 剧情语音 ———")
                story_scraper(session, cid, speaker_id, not is_extra,
                              log=self._push_log,
                              stop_event=self.stop_event,
                              on_progress=self._push_progress)

            if self.stop_event.is_set():
                self._push_log("已停止")
                return

            if do_voice and not is_extra:
                self._push_log("——— 角色语音 ———")
                character_voice_scraper(session, character_data, cid,
                                        log=self._push_log,
                                        stop_event=self.stop_event,
                                        on_progress=self._push_progress)

            if self.stop_event.is_set():
                self._push_log("已停止")
                return

            if do_list:
                self._push_log("——— 生成训练列表 ———")
                audio_to_list(cid, character_in_band=not is_extra,
                              log=self._push_log)

            self._push_log("")
            self._push_log("全部任务结束")

        except Exception as e:
            import traceback
            self._push_log(f"❌ 出错：{type(e).__name__}: {e}")
            self._push_log(traceback.format_exc())
        finally:
            self.msg_queue.put(("done", None))

    # ==================== 线程 → 界面 ====================
    def _push_log(self, text):
        self.msg_queue.put(("log", str(text)))

    def _push_progress(self, done, total):
        self.msg_queue.put(("progress", done, total))

    def _poll_queue(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                kind = msg[0]

                if kind == "log":
                    self._append_log(msg[1])
                elif kind == "progress":
                    self._update_progress(msg[1], msg[2])
                elif kind == "done":
                    self._on_finished()
        except queue.Empty:
            pass

        self.root.after(80, self._poll_queue)

    def _append_log(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _update_progress(self, done, total):
        if total <= 0:
            return
        pct = done / total * 100
        self.progress["value"] = pct
        self.progress_label.configure(text=f"{done}/{total}  ({pct:.0f}%)")

    def _on_finished(self):
        self.running = False
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        if self.stop_event.is_set():
            self.progress_label.configure(text="已停止")
        else:
            self.progress["value"] = 100
            self.progress_label.configure(text="完成")


def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    SpiderUikaApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
