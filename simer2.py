import os
import time
import random
import ctypes
import subprocess
import threading
import tkinter as tk
import win32gui
import win32con
import win32process
import psutil
import pythoncom
import pyautogui
import win32com.client
from pynput import keyboard
from tkinter import scrolledtext

# Constants to prevent sleep/lock
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


class AutomationController:
    def __init__(self):
        self.script_path = r"C:\temp\script.py"
        self.snippets = self.load_snippets()
        self.running = threading.Event()
        self.user_detection_enabled = False

        # Setup GUI
        self.root = tk.Tk()
        self.root.title("MS Word Automation")
        self.root.geometry("+0+0")
        self.root.attributes('-topmost', True)

        self.toggle_btn = tk.Button(self.root, text="Start", command=self.toggle_automation,
                                    width=20, height=2, bg="white")
        self.toggle_btn.pack(pady=10)

        self.log_field = scrolledtext.ScrolledText(self.root, height=5, width=40, state=tk.DISABLED)
        self.log_field.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        # Setup keyboard listener
        self.keyboard_listener = keyboard.Listener(on_press=self.on_key_press)
        self.keyboard_listener.start()

        self.log_queue = []
        self.root.after(100, self.update_log)

    def log_message(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.log_queue.append(f"[{timestamp}] {message}")

    def update_log(self):
        if self.log_queue:
            self.log_field.config(state=tk.NORMAL)
            while self.log_queue:
                msg = self.log_queue.pop(0)
                self.log_field.insert(tk.END, msg + "\n")
            self.log_field.config(state=tk.DISABLED)
            self.log_field.yview(tk.END)
        self.root.after(100, self.update_log)

    @staticmethod
    def prevent_sleep():
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)

    @staticmethod
    def allow_sleep():
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)

    def load_snippets(self):
        try:
            with open("dblib.py", "r") as f:
                lines = [line.strip() for line in f if line.strip()]
            return lines if lines else ["Default snippet: dblib.py is empty."]
        except Exception as e:
            self.log_message(f"Error loading snippets: {e}")
            return ["Default snippet: dblib.py not found."]

    def open_script_in_pycharm(self):
        try:
            with open(self.script_path, 'w') as f:
                f.write("# New Python script\n")
            subprocess.Popen(f'start pycharm "{self.script_path}"', shell=True)
            self.log_message(f"Opened script in PyCharm: {self.script_path}")
        except Exception as e:
            self.log_message(f"Error opening script: {e}")

    @staticmethod
    def find_word_window():
        hwnd_list = []

        def enum_window_callback(hwnd, result):
            if win32gui.IsWindowVisible(hwnd):
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                for proc in psutil.process_iter(['pid', 'name']):
                    if proc.info['pid'] == pid and proc.info['name'].lower() == "winword.exe":
                        result.append(hwnd)

        win32gui.EnumWindows(enum_window_callback, hwnd_list)
        return hwnd_list[0] if hwnd_list else None

    def bring_window_to_front(self):
        hwnd = self.find_word_window()
        if hwnd:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            self.log_message("Brought WINWORD.EXE to the foreground.")
        else:
            self.log_message("Could not find WINWORD.EXE window.")

    def get_or_create_word_doc(self):
        pythoncom.CoInitialize()
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = True

        for doc in word.Documents:
            if doc.Name.lower() == "py.simer.docx":
                self.log_message("Using existing Word document: py.simer")
                doc.Application.Activate()
                self.bring_window_to_front()
                return doc

        doc = word.Documents.Add()
        temp_path = os.path.join(os.environ["TEMP"], "py.simer.docx")
        doc.SaveAs2(temp_path)
        doc.Application.Activate()
        self.bring_window_to_front()
        self.log_message("Created new Word document: py.simer")
        return doc

    def random_mouse_movement(self):
        current_x, current_y = pyautogui.position()
        x_end = random.randint(0, pyautogui.size()[0])
        y_end = random.randint(0, pyautogui.size()[1])
        curve_x = random.randint(-100, 100)
        curve_y = random.randint(-100, 100)
        for i in range(10):
            if not self.running.is_set():
                self.log_message("Aborting mouse movement due to stop request.")
                break
            x = current_x + (x_end - current_x) * i / 10 + random.uniform(-curve_x, curve_x)
            y = current_y + (y_end - current_y) * i / 10 + random.uniform(-curve_y, curve_y)
            pyautogui.moveTo(x, y, duration=random.uniform(0.05, 0.5))

    def random_typing(self):
        pythoncom.CoInitialize()
        try:
            self.prevent_sleep()
            self.user_detection_enabled = True
            self.get_or_create_word_doc()
            time.sleep(2)
            self.log_message("Automation started.")

            pyautogui.FAILSAFE = False

            while self.running.is_set():
                snippet = random.choice(self.snippets)
                for char in snippet:
                    if not self.running.is_set():
                        self.log_message("Typing interrupted by stop request.")
                        return
                    pyautogui.write(char, interval=random.uniform(0.1, 0.4))
                pyautogui.write("\n")
                # Check running flag before sleeping
                for _ in range(random.randint(1, 3)):
                    if not self.running.is_set():
                        self.log_message("Sleep interrupted by stop request.")
                        return
                    time.sleep(1)
                self.random_mouse_movement()

        finally:
            pyautogui.FAILSAFE = True
            self.allow_sleep()
            pythoncom.CoUninitialize()
            self.log_message("Automation stopped.")

    def on_key_press(self, key):
        if self.user_detection_enabled and key == keyboard.Key.esc:
            self.running.clear()
            self.user_detection_enabled = False
            self.toggle_btn.config(text="Start", bg="white")
            self.log_message("ESC detected! Stopping automation immediately.")

    def toggle_automation(self):
        if not self.running.is_set():
            self.running.set()
            self.toggle_btn.config(text="Stop", bg="gray")
            threading.Thread(target=self.random_typing, daemon=True).start()
            #self.open_script_in_pycharm()
            self.log_message("Starting automation...")
        else:
            self.running.clear()
            self.toggle_btn.config(text="Start", bg="white")
            self.log_message("Stopping automation...")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    AutomationController().run()
