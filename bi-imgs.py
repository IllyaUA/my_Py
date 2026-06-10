import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk

# try to support drag-and-drop from OS if tkinterdnd2 is installed
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    TkBase = TkinterDnD.Tk
    HAS_DND = True
except ImportError:
    TkBase = tk.Tk
    HAS_DND = False


class ImageStackApp(TkBase):
    def __init__(self):
        super().__init__()
        self.title("Image stacker")
        self.geometry("900x500")

        self.images = []   # list of dicts: {"path": ..., "image": PIL.Image}
        self.preview_photo = None

        self.create_widgets()

    def create_widgets(self):
        main = ttk.Frame(self, padding=5)
        main.pack(fill="both", expand=True)

        # left side: controls + list
        left = ttk.Frame(main)
        left.pack(side="left", fill="y")

        # alphanumeric value
        ttk.Label(left, text="Name / ID:").pack(anchor="w")
        self.name_var = tk.StringVar()
        ttk.Entry(left, textvariable=self.name_var, width=25).pack(anchor="w", pady=(0, 5))

        # list of images
        ttk.Label(left, text="Images (top entry = bottom layer):").pack(anchor="w")

        self.listbox = tk.Listbox(left, width=35, height=20, selectmode=tk.SINGLE)
        self.listbox.pack(fill="y", expand=False, pady=5)

        # enable internal drag-reorder
        self.listbox.bind("<Button-1>", self.on_listbox_click)
        self.listbox.bind("<B1-Motion>", self.on_listbox_drag)

        # OS drag-and-drop
        if HAS_DND:
            self.listbox.drop_target_register(DND_FILES)
            self.listbox.dnd_bind("<<Drop>>", self.on_external_drop)

        # buttons
        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=5)
        ttk.Button(btns, text="Add image…", command=self.add_images).pack(side="left", padx=2)
        ttk.Button(btns, text="Remove", command=self.remove_selected).pack(side="left", padx=2)
        ttk.Button(btns, text="Save as…", command=self.save_composite).pack(side="right", padx=2)

        # right side: preview
        preview_frame = ttk.Frame(main)
        preview_frame.pack(side="left", fill="both", expand=True)
        ttk.Label(preview_frame, text="Preview:").pack(anchor="w")
        self.preview_label = ttk.Label(preview_frame)
        self.preview_label.pack(fill="both", expand=True, padx=5, pady=5)

    # ------------- list drag reorder -------------
    def on_listbox_click(self, event):
        self.listbox.selection_clear(0, tk.END)
        idx = self.listbox.nearest(event.y)
        self.listbox.selection_set(idx)
        self._drag_start_index = idx

    def on_listbox_drag(self, event):
        new_index = self.listbox.nearest(event.y)
        old_index = getattr(self, "_drag_start_index", None)
        if old_index is None or new_index == old_index:
            return
        # swap in listbox
        text = self.listbox.get(old_index)
        self.listbox.delete(old_index)
        self.listbox.insert(new_index, text)
        # swap in our list
        item = self.images.pop(old_index)
        self.images.insert(new_index, item)

        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(new_index)
        self._drag_start_index = new_index

        # update preview
        self.update_preview()

    # ------------- add/remove -------------
    def add_images(self):
        paths = filedialog.askopenfilenames(
            title="Select images",
            filetypes=[("Image files", "*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.webp"), ("All files", "*.*")]
        )
        if not paths:
            return
        for p in paths:
            self._add_image_path(p)
        self.update_preview()

    def _add_image_path(self, path):
        try:
            img = Image.open(path).convert("RGBA")
        except Exception as e:
            messagebox.showerror("Error", f"Cannot open {path}:\n{e}")
            return

        self.images.append({"path": path, "image": img})
        self.listbox.insert(tk.END, os.path.basename(path))

    def remove_selected(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self.listbox.delete(idx)
        del self.images[idx]
        self.update_preview()

    # ------------- external drag&drop -------------
    def on_external_drop(self, event):
        # event.data may contain {path1} {path2}
        raw = self.split_dnd_paths(event.data)
        for p in raw:
            self._add_image_path(p)
        self.update_preview()

    @staticmethod
    def split_dnd_paths(data: str):
        # handles windows-style {C:\path a} {C:\path b}
        paths = []
        curr = ""
        inside = False
        for ch in data:
            if ch == "{":
                inside = True
                curr = ""
            elif ch == "}":
                inside = False
                paths.append(curr)
                curr = ""
            else:
                if inside:
                    curr += ch
        if not paths and data:
            paths = [data]
        return paths

    # ------------- composite + preview -------------
    def update_preview(self):
        if not self.images:
            self.preview_label.configure(image="", text="(no images)")
            return

        # composite all to size of first image
        base_img = self.images[0]["image"].copy()
        for layer in self.images[1:]:
            base_img.alpha_composite(layer["image"].resize(base_img.size))

        # make a preview thumbnail
        preview = base_img.copy()
        preview.thumbnail((400, 400))
        self.preview_photo = ImageTk.PhotoImage(preview)
        self.preview_label.configure(image=self.preview_photo, text="")

    def save_composite(self):
        if not self.images:
            messagebox.showwarning("Nothing to save", "Add at least one image.")
            return

        # composite
        base_img = self.images[0]["image"].copy()
        for layer in self.images[1:]:
            # resize other layers to match first
            img = layer["image"]
            if img.size != base_img.size:
                img = img.resize(base_img.size, Image.LANCZOS)
            base_img.alpha_composite(img)

        # default filename from alphanumeric entry
        base_name = self.name_var.get().strip() or "composite"
        initfile = base_name + ".png"

        path = filedialog.asksaveasfilename(
            title="Save composite",
            defaultextension=".png",
            initialfile=initfile,
            filetypes=[("PNG image", "*.png")]
        )
        if not path:
            return

        base_img.save(path, "PNG")
        messagebox.showinfo("Saved", f"Saved to {path}")


if __name__ == "__main__":
    app = ImageStackApp()
    app.mainloop()
