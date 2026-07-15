import os
import time
import threading
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path


def browse_folder():
    folder = filedialog.askdirectory(title="Select Folder")
    if folder:
        folder_var.set(folder)


def set_running(is_running):
    state = "disabled" if is_running else "normal"
    start_btn.config(state=state)
    browse_btn.config(state=state)
    entry.config(state=state)


def worker(folder, now, skip_svn, q):
    # runs off the main thread; reports progress via the queue
    count = 0
    errors = []
    try:
        for path in Path(folder).rglob("*"):
            try:
                if skip_svn and ".svn" in path.parts:
                    continue
                if path.is_file() and not path.is_symlink():
                    os.utime(path, (now, now))
                    count += 1
                    if count % 250 == 0:
                        q.put(("progress", count))
            except OSError as e:
                errors.append(f"{path}: {e}")
    except OSError as e:
        # rglob can raise on an unreadable directory mid-walk
        errors.append(f"walk aborted: {e}")
    q.put(("done", count, errors))


def poll_queue(q):
    try:
        while True:
            msg = q.get_nowait()
            if msg[0] == "progress":
                status_var.set(f"Processing... {msg[1]} files")
            elif msg[0] == "done":
                _, count, errors = msg
                finish(count, errors)
                return
    except queue.Empty:
        pass
    root.after(100, poll_queue, q)


def finish(count, errors):
    progress.stop()
    progress.config(mode="determinate")
    progress["value"] = 100
    set_running(False)

    if errors:
        status_var.set(f"Done. Updated {count}, {len(errors)} failed.")
        log = Path(folder_var.get()) / "touch_files_errors.log"
        try:
            log.write_text("\n".join(errors), encoding="utf-8")
            note = f"\n\n{len(errors)} files failed. Details written to:\n{log}"
        except OSError:
            note = f"\n\n{len(errors)} files failed (could not write log)."
        messagebox.showwarning("Finished with errors",
                               f"Updated timestamps for {count} files.{note}")
    else:
        status_var.set(f"Done. Updated {count} files.")
        messagebox.showinfo("Finished",
                            f"Successfully updated timestamps for {count} files.")


def start():
    folder = folder_var.get()

    if not folder or not os.path.isdir(folder):
        messagebox.showerror("Error", "Please select a valid folder.")
        return

    set_running(True)
    status_var.set("Processing...")
    progress.config(mode="indeterminate")
    progress.start(15)

    now = time.time()
    q = queue.Queue()
    t = threading.Thread(
        target=worker,
        args=(folder, now, skip_svn_var.get(), q),
        daemon=True,
    )
    t.start()
    poll_queue(q)


root = tk.Tk()
root.title("Touch Files")
root.geometry("600x190")
root.resizable(False, False)

folder_var = tk.StringVar()
status_var = tk.StringVar(value="Select a folder.")
skip_svn_var = tk.BooleanVar(value=True)

frame = tk.Frame(root, padx=10, pady=10)
frame.pack(fill="both", expand=True)

tk.Label(frame, text="Folder:").grid(row=0, column=0, sticky="w")

entry = tk.Entry(frame, textvariable=folder_var, width=60)
entry.grid(row=0, column=1, padx=5)

browse_btn = tk.Button(frame, text="Browse...", command=browse_folder)
browse_btn.grid(row=0, column=2)

tk.Checkbutton(frame, text="Skip .svn folders",
               variable=skip_svn_var).grid(row=1, column=1, sticky="w", padx=5)

start_btn = tk.Button(frame, text="Start", width=12, command=start)
start_btn.grid(row=2, column=1, pady=10)

progress = ttk.Progressbar(frame, length=560, mode="determinate")
progress.grid(row=3, column=0, columnspan=3, pady=(0, 8))

status = tk.Label(frame, textvariable=status_var, anchor="w")
status.grid(row=4, column=0, columnspan=3, sticky="w")

root.mainloop()