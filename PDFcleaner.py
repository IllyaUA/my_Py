#!/usr/bin/env python3
"""
Document Scan Restorer
─────────────────────
Loads a PDF or images (PNG/JPEG/BMP/TIFF), lets you tweak levels /
contrast / colour balance / gradient-shadow normalisation with live
preview, crop pages, then exports a clean PDF.

Drag-and-drop of files onto the window is supported.

Dependencies: PyMuPDF (fitz), Pillow, NumPy, SciPy, tkinterdnd2
"""
from __future__ import annotations

import io
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _DND_AVAILABLE = True
except ImportError:
    _DND_AVAILABLE = False

import fitz
import numpy as np
from PIL import Image, ImageTk
from scipy.ndimage import gaussian_filter


# Image processing
def apply_levels(arr, black_in, white_in, gamma, black_out, white_out):
    arr = arr.astype(np.float32)
    lo, hi = black_in / 255.0, white_in / 255.0
    arr = np.clip((arr / 255.0 - lo) / max(hi - lo, 1e-6), 0.0, 1.0)
    arr = np.power(arr, 1.0 / max(gamma, 0.01))
    arr = arr * (white_out - black_out) / 255.0 + black_out / 255.0
    return np.clip(arr * 255.0, 0, 255).astype(np.uint8)


def normalise_gradient(arr, sigma, strength):
    if strength < 0.01:
        return arr
    f = arr.astype(np.float32)
    blurred = np.stack([gaussian_filter(f[:, :, c], sigma=sigma)
                        for c in range(3)], axis=2)
    ref = np.full_like(blurred, 200.0)
    corrected = np.clip(f / np.maximum(blurred, 1.0) * ref, 0, 255)
    return np.clip((1.0 - strength) * f + strength * corrected, 0, 255).astype(np.uint8)


def apply_colour_balance(arr, r_shift, g_shift, b_shift, saturation):
    f = arr.astype(np.float32)
    f[:, :, 0] = np.clip(f[:, :, 0] + r_shift, 0, 255)
    f[:, :, 1] = np.clip(f[:, :, 1] + g_shift, 0, 255)
    f[:, :, 2] = np.clip(f[:, :, 2] + b_shift, 0, 255)
    if abs(saturation - 1.0) > 0.001:
        lum = (0.299*f[:,:,0] + 0.587*f[:,:,1] + 0.114*f[:,:,2])[:,:,np.newaxis]
        f = np.clip(lum + saturation * (f - lum), 0, 255)
    return f.astype(np.uint8)


def process_page(page_img: Image.Image, params: dict, crop_norm=None) -> Image.Image:
    """Full pipeline. crop_norm = (x0,y0,x1,y1) normalised 0-1, or None."""
    arr = np.array(page_img.convert("RGB"))
    arr = normalise_gradient(arr, params["grad_sigma"], params["grad_strength"])
    arr = apply_levels(arr, params["black_in"], params["white_in"], params["gamma"],
                       params["black_out"], params["white_out"])
    arr = arr.astype(np.float32)
    arr = np.clip((arr - 128.0) * params["contrast"] + 128.0 + params["brightness"], 0, 255).astype(np.uint8)
    arr = apply_colour_balance(arr, params["r_shift"], params["g_shift"],
                                params["b_shift"], params["saturation"])
    img = Image.fromarray(arr)
    if crop_norm:
        w, h = img.size
        img = img.crop((int(crop_norm[0]*w), int(crop_norm[1]*h),
                        int(crop_norm[2]*w), int(crop_norm[3]*h)))
    return img


# Theme
PANEL_BG   = "#1e1e2e"
CTRL_BG    = "#2a2a3e"
ACCENT     = "#7c6af7"
ACCENT2    = "#f5a623"
TEXT_FG    = "#cdd6f4"
PREVIEW_BG = "#11111b"

DEFAULT_PARAMS = {
    "black_in": 0.0, "white_in": 255.0, "gamma": 1.0,
    "black_out": 0.0, "white_out": 255.0,
    "brightness": 0.0, "contrast": 1.0,
    "r_shift": 0.0, "g_shift": 0.0, "b_shift": 0.0, "saturation": 1.0,
    "grad_strength": 0.0, "grad_sigma": 80.0,
}

PREVIEW_DPI = 120
EXPORT_DPI  = 200
HANDLE_R    = 6
CROP_CLR    = "#f5a623"

# SliderRow
class SliderRow:
    def __init__(self, parent, label, var, from_, to, fmt="{:.0f}"):
        self.fmt, self.var = fmt, var
        row = tk.Frame(parent, bg=CTRL_BG)
        row.pack(fill=tk.X, padx=8, pady=2)
        tk.Label(row, text=label, bg=CTRL_BG, fg=TEXT_FG,
                 width=18, anchor="w", font=("Helvetica", 9)).pack(side=tk.LEFT)
        ttk.Scale(row, from_=from_, to=to, orient=tk.HORIZONTAL,
                  variable=var, length=155).pack(side=tk.LEFT, padx=(0,4))
        self.ent = tk.Entry(row, width=6, bg="#3b3b52", fg=TEXT_FG,
                            insertbackground=TEXT_FG, relief=tk.FLAT,
                            font=("Courier", 9))
        self.ent.pack(side=tk.LEFT)
        var.trace_add("write", lambda *_: self._sync())
        self.ent.bind("<Return>",   self._from_ent)
        self.ent.bind("<FocusOut>", self._from_ent)
        self._sync()

    def _sync(self):
        self.ent.delete(0, tk.END)
        self.ent.insert(0, self.fmt.format(self.var.get()))

    def _from_ent(self, *_):
        try:
            self.var.set(float(self.ent.get()))
        except ValueError:
            self._sync()


# App
_AppBase = TkinterDnD.Tk if _DND_AVAILABLE else tk.Tk

class App(_AppBase):
    def __init__(self):
        super().__init__()
        self.title("Document Scan Restorer")
        self.configure(bg=PANEL_BG)
        self.geometry("1300x840")
        self.minsize(900, 600)

        self.doc         = None
        self.page_index  = 0
        self.raw_pages   = []
        self._source_type = None  # "pdf" or "images"
        self._image_paths = []    # original paths when loaded from images

        self._preview_job = None
        self._tk_img      = None

        # crop state
        self.crop_norm      = None   # (x0,y0,x1,y1) normalised, or None
        self._crop_mode     = False
        self._drag_start    = None
        self._drag_handle   = None
        self._new_rect_orig = None   # anchor for new-rect drag
        self._drag_crop_bak = None   # crop snapshot at body-drag start
        self._overlay       = []     # canvas item ids

        self._build_ui()
        self._apply_style()

    # build UI

    def _build_ui(self):
        # top bar
        top = tk.Frame(self, bg=PANEL_BG, height=44)
        top.pack(fill=tk.X)
        top.pack_propagate(False)
        btn = dict(bg=ACCENT, fg="white", relief=tk.FLAT, padx=14, pady=4,
                   font=("Helvetica", 10, "bold"), cursor="hand2",
                   activebackground="#6a5ae0", activeforeground="white")
        tk.Button(top, text="📂  Open…", command=self._open_dialog, **btn).pack(side=tk.LEFT, padx=8, pady=6)
        self.lbl_file = tk.Label(top, text="No file loaded", bg=PANEL_BG, fg=TEXT_FG, font=("Helvetica", 9))
        self.lbl_file.pack(side=tk.LEFT, padx=4)
        tk.Button(top, text="💾  Export PDF", command=self._export_pdf, **btn).pack(side=tk.RIGHT, padx=8, pady=6)
        tk.Button(top, text="↺  Reset",       command=self._reset_params,
                  bg="#444460", fg=TEXT_FG, relief=tk.FLAT, padx=10, pady=4,
                  font=("Helvetica", 10), cursor="hand2").pack(side=tk.RIGHT, padx=4, pady=6)

        # main
        main = tk.Frame(self, bg=PANEL_BG)
        main.pack(fill=tk.BOTH, expand=True)

        # left panel
        ctrl_outer = tk.Frame(main, bg=CTRL_BG, width=284)
        ctrl_outer.pack(side=tk.LEFT, fill=tk.Y)
        ctrl_outer.pack_propagate(False)
        cs = tk.Canvas(ctrl_outer, bg=CTRL_BG, highlightthickness=0, width=282)
        sb = ttk.Scrollbar(ctrl_outer, orient="vertical", command=cs.yview)
        cs.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        cs.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        cs.bind("<MouseWheel>", lambda e: cs.yview_scroll(-1*(e.delta//120), "units"))
        self.ctrl_frame = tk.Frame(cs, bg=CTRL_BG)
        cw = cs.create_window((0,0), window=self.ctrl_frame, anchor="nw")
        self.ctrl_frame.bind("<Configure>", lambda e: cs.configure(scrollregion=cs.bbox("all")))
        cs.bind("<Configure>", lambda e: cs.itemconfig(cw, width=e.width))
        self._build_controls()

        # right preview
        pv = tk.Frame(main, bg=PREVIEW_BG)
        pv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # nav bar
        nav = tk.Frame(pv, bg=PANEL_BG, height=36)
        nav.pack(fill=tk.X)
        nav.pack_propagate(False)
        tk.Button(nav, text="◀", command=self._prev_page,
                  bg=PANEL_BG, fg=TEXT_FG, relief=tk.FLAT, font=("Helvetica", 12)).pack(side=tk.LEFT, padx=6)
        self.lbl_page = tk.Label(nav, text="Page — / —", bg=PANEL_BG, fg=TEXT_FG, font=("Helvetica", 9))
        self.lbl_page.pack(side=tk.LEFT)
        tk.Button(nav, text="▶", command=self._next_page,
                  bg=PANEL_BG, fg=TEXT_FG, relief=tk.FLAT, font=("Helvetica", 12)).pack(side=tk.LEFT, padx=6)

        # zoom (right side)
        tk.Label(nav, text="Zoom:", bg=PANEL_BG, fg=TEXT_FG, font=("Helvetica", 9)).pack(side=tk.RIGHT, padx=(0,2))
        self.zoom_var = tk.DoubleVar(value=1.0)
        ttk.Scale(nav, from_=0.3, to=3.0, orient=tk.HORIZONTAL,
                  variable=self.zoom_var, length=100).pack(side=tk.RIGHT, padx=6)
        self.zoom_var.trace_add("write", lambda *_: self._refresh_canvas())
        tk.Frame(nav, bg="#444460", width=1).pack(side=tk.RIGHT, fill=tk.Y, pady=4, padx=4)

        # crop buttons
        tk.Button(nav, text="✕ Clear", command=self._clear_crop,
                  bg="#444460", fg=TEXT_FG, relief=tk.FLAT,
                  padx=8, pady=2, font=("Helvetica", 9), cursor="hand2").pack(side=tk.RIGHT, padx=2)
        self.btn_crop = tk.Button(nav, text="✂  Crop", command=self._toggle_crop_mode,
                                   bg="#444460", fg=TEXT_FG, relief=tk.FLAT,
                                   padx=10, pady=2, font=("Helvetica", 9, "bold"), cursor="hand2")
        self.btn_crop.pack(side=tk.RIGHT, padx=2)

        # canvas
        cf = tk.Frame(pv, bg=PREVIEW_BG)
        cf.pack(fill=tk.BOTH, expand=True)
        self.h_scroll = ttk.Scrollbar(cf, orient=tk.HORIZONTAL)
        self.v_scroll = ttk.Scrollbar(cf, orient=tk.VERTICAL)
        self.canvas   = tk.Canvas(cf, bg=PREVIEW_BG, highlightthickness=0,
                                   xscrollcommand=self.h_scroll.set,
                                   yscrollcommand=self.v_scroll.set)
        self.h_scroll.config(command=self.canvas.xview)
        self.v_scroll.config(command=self.canvas.yview)
        self.h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.v_scroll.pack(side=tk.RIGHT,  fill=tk.Y)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.bind("<ButtonPress-1>",  self._on_press)
        self.canvas.bind("<B1-Motion>",       self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>",          self._on_motion)
        self.canvas.bind("<MouseWheel>",      self._cv_scroll)
        self.canvas.bind("<Button-4>",        self._cv_scroll)
        self.canvas.bind("<Button-5>",        self._cv_scroll)

        # drag-and-drop (requires tkinterdnd2)
        if _DND_AVAILABLE:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)

        # status
        hint = "Open a PDF or images to begin — or drag & drop files here."
        self.status_var = tk.StringVar(value=hint)
        tk.Label(self, textvariable=self.status_var, bg=PANEL_BG, fg="#888aaa",
                 font=("Helvetica", 8), anchor="w").pack(fill=tk.X, padx=8, pady=(0,2))

    def _sec(self, title):
        tk.Frame(self.ctrl_frame, bg=CTRL_BG).pack(fill=tk.X, pady=(10,2))
        tk.Label(self.ctrl_frame, text=f"  {title}", bg=CTRL_BG, fg=ACCENT,
                 font=("Helvetica", 10, "bold"), anchor="w").pack(fill=tk.X)
        tk.Frame(self.ctrl_frame, bg="#3f3f5a", height=1).pack(fill=tk.X, padx=8)

    def _build_controls(self):
        self.vars = {k: tk.DoubleVar(value=v) for k, v in DEFAULT_PARAMS.items()}
        for v in self.vars.values():
            v.trace_add("write", self._schedule_update)

        self._sec("Shadow / Gradient Removal")
        SliderRow(self.ctrl_frame, "Strength",     self.vars["grad_strength"], 0,    1,   "{:.2f}")
        SliderRow(self.ctrl_frame, "Blur radius",  self.vars["grad_sigma"],    10,   300)

        self._sec("Levels")
        SliderRow(self.ctrl_frame, "Black pt (in)",  self.vars["black_in"],   0,   254)
        SliderRow(self.ctrl_frame, "White pt (in)",  self.vars["white_in"],   1,   255)
        SliderRow(self.ctrl_frame, "Gamma",          self.vars["gamma"],      0.1, 4.0, "{:.2f}")
        SliderRow(self.ctrl_frame, "Black pt (out)", self.vars["black_out"],  0,   254)
        SliderRow(self.ctrl_frame, "White pt (out)", self.vars["white_out"],  1,   255)

        self._sec("Brightness / Contrast")
        SliderRow(self.ctrl_frame, "Brightness", self.vars["brightness"], -128, 128)
        SliderRow(self.ctrl_frame, "Contrast",   self.vars["contrast"],    0.1, 3.0, "{:.2f}")

        self._sec("Colour Balance")
        SliderRow(self.ctrl_frame, "Red shift",   self.vars["r_shift"],   -80, 80)
        SliderRow(self.ctrl_frame, "Green shift", self.vars["g_shift"],   -80, 80)
        SliderRow(self.ctrl_frame, "Blue shift",  self.vars["b_shift"],   -80, 80)
        SliderRow(self.ctrl_frame, "Saturation",  self.vars["saturation"], 0,  3.0, "{:.2f}")

        self._sec("Crop")
        self.lbl_crop = tk.Label(self.ctrl_frame,
                                  text="No crop.\nClick ✂ Crop, then drag on image.",
                                  bg=CTRL_BG, fg="#888aaa",
                                  font=("Helvetica", 8), justify=tk.LEFT, anchor="w")
        self.lbl_crop.pack(anchor="w", padx=10, pady=4)

        self._sec("")
        self.compare_var = tk.BooleanVar(value=False)
        tk.Checkbutton(self.ctrl_frame, text="  Show original (compare)",
                       variable=self.compare_var, command=self._refresh_canvas,
                       bg=CTRL_BG, fg=TEXT_FG, selectcolor=CTRL_BG,
                       activebackground=CTRL_BG, activeforeground=TEXT_FG,
                       font=("Helvetica", 9)).pack(anchor="w", padx=8, pady=6)

    def _apply_style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TScale", troughcolor="#3b3b52", background=CTRL_BG,
                    sliderlength=14, sliderrelief="flat")
        s.configure("TScrollbar", background="#3b3b52", troughcolor=PANEL_BG, arrowcolor=TEXT_FG)

    # crop mode
    def _toggle_crop_mode(self):
        self._crop_mode = not self._crop_mode
        if self._crop_mode:
            self.btn_crop.config(bg=ACCENT2, fg="black")
            self.canvas.config(cursor="crosshair")
            self.status_var.set("✂ Crop mode ON — drag to draw, drag handles/corners to adjust.")
        else:
            self.btn_crop.config(bg="#444460", fg=TEXT_FG)
            self.canvas.config(cursor="arrow")
            self.status_var.set("Crop mode off.")

    def _clear_crop(self):
        self.crop_norm = None
        self._drag_start = None
        self._update_crop_label()
        self._refresh_canvas()

    def _update_crop_label(self):
        s = self._raw_size()
        if self.crop_norm and s:
            w, h = s
            x0 = int(self.crop_norm[0]*w); y0 = int(self.crop_norm[1]*h)
            x1 = int(self.crop_norm[2]*w); y1 = int(self.crop_norm[3]*h)
            self.lbl_crop.config(
                text=f"({x0},{y0}) → ({x1},{y1})\n{x1-x0} × {y1-y0} px",
                fg=ACCENT2)
        else:
            self.lbl_crop.config(
                text="No crop.\nClick ✂ Crop, then drag on image.",
                fg="#888aaa")

    # coordinate helpers
    def _raw_size(self):
        if self.raw_pages and self.page_index < len(self.raw_pages):
            p = self.raw_pages[self.page_index]
            if p:
                return p.width, p.height
        return None

    def _canvas_to_norm(self, cx, cy):
        """Widget coords → normalised image coords (0-1)."""
        s = self._raw_size()
        if not s:
            return 0.0, 0.0
        zoom = self.zoom_var.get()
        ix = self.canvas.canvasx(cx) / zoom
        iy = self.canvas.canvasy(cy) / zoom
        return max(0.0, min(1.0, ix/s[0])), max(0.0, min(1.0, iy/s[1]))

    def _norm_to_canvas(self, nx, ny):
        s = self._raw_size()
        if not s:
            return 0.0, 0.0
        zoom = self.zoom_var.get()
        return nx * s[0] * zoom, ny * s[1] * zoom

    def _hit_handle(self, cx, cy):
        """Which crop handle is at canvas widget coord (cx,cy)?"""
        if not self.crop_norm:
            return None
        x0c, y0c = self._norm_to_canvas(self.crop_norm[0], self.crop_norm[1])
        x1c, y1c = self._norm_to_canvas(self.crop_norm[2], self.crop_norm[3])
        ax = self.canvas.canvasx(cx)
        ay = self.canvas.canvasy(cy)
        HR = HANDLE_R + 4
        corners = {"tl":(x0c,y0c),"tr":(x1c,y0c),"bl":(x0c,y1c),"br":(x1c,y1c)}
        for n,(hx,hy) in corners.items():
            if abs(ax-hx)<=HR and abs(ay-hy)<=HR:
                return n
        mx = (x0c+x1c)/2;  my = (y0c+y1c)/2
        edges = {"t":(mx,y0c),"b":(mx,y1c),"l":(x0c,my),"r":(x1c,my)}
        for n,(hx,hy) in edges.items():
            if abs(ax-hx)<=HR+2 and abs(ay-hy)<=HR+2:
                return n
        if x0c<=ax<=x1c and y0c<=ay<=y1c:
            return "body"
        return None

    # mouse events
    def _on_press(self, event):
        if not self._crop_mode:
            return
        handle = self._hit_handle(event.x, event.y)
        self._drag_handle = handle
        self._drag_start  = (event.x, event.y)
        if handle is None:
            nx, ny = self._canvas_to_norm(event.x, event.y)
            self._new_rect_orig = (nx, ny)
            self.crop_norm = (nx, ny, nx, ny)
        elif handle == "body":
            self._drag_crop_bak = self.crop_norm

    def _on_drag(self, event):
        if not self._crop_mode or self._drag_start is None:
            return
        s = self._raw_size()
        if not s:
            return
        nx, ny = self._canvas_to_norm(event.x, event.y)

        h = self._drag_handle
        if h is None:
            ox, oy = self._new_rect_orig
            self.crop_norm = (min(ox,nx), min(oy,ny), max(ox,nx), max(oy,ny))
        elif h == "body":
            zoom = self.zoom_var.get()
            dnx = (event.x - self._drag_start[0]) / (s[0] * zoom)
            dny = (event.y - self._drag_start[1]) / (s[1] * zoom)
            ox0,oy0,ox1,oy1 = self._drag_crop_bak
            bw,bh = ox1-ox0, oy1-oy0
            nx0 = max(0.0, min(1.0-bw, ox0+dnx))
            ny0 = max(0.0, min(1.0-bh, oy0+dny))
            self.crop_norm = (nx0, ny0, nx0+bw, ny0+bh)
        else:
            x0,y0,x1,y1 = self.crop_norm
            if   h=="tl": x0,y0 = nx,ny
            elif h=="tr": x1,y0 = nx,ny
            elif h=="bl": x0,y1 = nx,ny
            elif h=="br": x1,y1 = nx,ny
            elif h=="t":  y0 = ny
            elif h=="b":  y1 = ny
            elif h=="l":  x0 = nx
            elif h=="r":  x1 = nx
            self.crop_norm = (min(x0,x1), min(y0,y1), max(x0,x1), max(y0,y1))

        self._redraw_overlay()
        self._update_crop_label()

    def _on_release(self, event):
        if not self._crop_mode:
            return
        self._drag_start  = None
        self._drag_handle = None
        # discard accidental tiny rects
        if self.crop_norm:
            s = self._raw_size()
            if s:
                pw = (self.crop_norm[2]-self.crop_norm[0])*s[0]
                ph = (self.crop_norm[3]-self.crop_norm[1])*s[1]
                if pw < 5 or ph < 5:
                    self.crop_norm = None
        self._update_crop_label()
        self._refresh_canvas()

    def _on_motion(self, event):
        if not self._crop_mode or not self.crop_norm:
            return
        h = self._hit_handle(event.x, event.y)
        cursors = {
            "tl":"top_left_corner","tr":"top_right_corner",
            "bl":"bottom_left_corner","br":"bottom_right_corner",
            "t":"top_side","b":"bottom_side","l":"left_side","r":"right_side",
            "body":"fleur",
        }
        self.canvas.config(cursor=cursors.get(h, "crosshair"))

    # crop overlay

    def _clear_overlay(self):
        for item in self._overlay:
            self.canvas.delete(item)
        self._overlay = []

    def _redraw_overlay(self):
        self._clear_overlay()
        if not self.crop_norm:
            return
        s = self._raw_size()
        if not s:
            return
        w, h = s
        zoom = self.zoom_var.get()
        iw, ih = int(w*zoom), int(h*zoom)

        x0c, y0c = self._norm_to_canvas(self.crop_norm[0], self.crop_norm[1])
        x1c, y1c = self._norm_to_canvas(self.crop_norm[2], self.crop_norm[3])

        # darkened outside (4 rects, stippled)
        def drk(ax,ay,bx,by):
            if bx>ax and by>ay:
                i = self.canvas.create_rectangle(ax,ay,bx,by,
                    fill="#000000", outline="", stipple="gray50")
                self._overlay.append(i)
        drk(0,   0,   iw,  y0c)
        drk(0,   y1c, iw,  ih)
        drk(0,   y0c, x0c, y1c)
        drk(x1c, y0c, iw,  y1c)

        # border
        self._overlay.append(self.canvas.create_rectangle(
            x0c, y0c, x1c, y1c,
            outline=CROP_CLR, width=2, dash=(7,3)))

        # rule-of-thirds lines
        for f in (1/3, 2/3):
            self._overlay += [
                self.canvas.create_line(x0c+(x1c-x0c)*f, y0c, x0c+(x1c-x0c)*f, y1c,
                                         fill=CROP_CLR, width=1, dash=(3,5)),
                self.canvas.create_line(x0c, y0c+(y1c-y0c)*f, x1c, y0c+(y1c-y0c)*f,
                                         fill=CROP_CLR, width=1, dash=(3,5)),
            ]

        # handles (corners + edge midpoints)
        mx, my = (x0c+x1c)/2, (y0c+y1c)/2
        for hx, hy in [(x0c,y0c),(x1c,y0c),(x0c,y1c),(x1c,y1c),
                        (mx,y0c),(mx,y1c),(x0c,my),(x1c,my)]:
            self._overlay.append(self.canvas.create_oval(
                hx-HANDLE_R, hy-HANDLE_R, hx+HANDLE_R, hy+HANDLE_R,
                fill=CROP_CLR, outline="white", width=1))

        # size label
        pw = int((self.crop_norm[2]-self.crop_norm[0])*w)
        ph = int((self.crop_norm[3]-self.crop_norm[1])*h)
        txt = self.canvas.create_text(x0c+6, y0c+5,
            text=f" {pw}×{ph}px ", anchor="nw",
            fill="white", font=("Helvetica", 8, "bold"))
        bb = self.canvas.bbox(txt)
        bg = self.canvas.create_rectangle(*bb, fill="#333355", outline="")
        self.canvas.tag_lower(bg, txt)
        self._overlay += [txt, bg]

    # page / file

    def _open_dialog(self):
        """Single open button — detects PDF vs images from extension."""
        path = filedialog.askopenfilename(
            title="Open PDF or image(s)",
            filetypes=[
                ("All supported", "*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"),
                ("PDF",   "*.pdf"),
                ("Images","*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"),
                ("All files","*.*"),
            ])
        if path:
            self._load_paths([path])

    def _on_drop(self, event):
        """Handle files dropped onto the window."""
        # tkinterdnd2 encodes multiple paths as a Tcl list: {path1} {path2} …
        # splitlist handles spaces-in-paths correctly
        try:
            paths = list(self.tk.splitlist(event.data))
        except Exception:
            paths = event.data.split()
        if paths:
            self._load_paths(paths)

    def _load_paths(self, paths: list[str]):
        """Route one-or-more paths to PDF or image loader."""
        IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp",
                     ".tif", ".tiff", ".webp"}
        import os
        first_ext = os.path.splitext(paths[0])[1].lower()
        if first_ext == ".pdf":
            self._open_pdf(paths[0])
        else:
            # treat all dropped/selected paths as an image stack;
            # silently skip anything that isn't a recognised image
            img_paths = [p for p in paths
                         if os.path.splitext(p)[1].lower() in IMAGE_EXT]
            if img_paths:
                self._open_images(img_paths)
            else:
                messagebox.showwarning("Unsupported",
                    f"No recognised file type:\n{paths[0]}")

    def _open_pdf(self, path: str | None = None):
        if path is None:
            path = filedialog.askopenfilename(
                title="Open scanned PDF",
                filetypes=[("PDF files","*.pdf"),("All files","*.*")])
        if not path:
            return
        self.status_var.set("Loading…")
        self.update_idletasks()
        try:
            self.doc          = fitz.open(path)
            self._source_type = "pdf"
            self._image_paths = []
            self.page_index   = 0
            self.raw_pages    = []
            self.crop_norm    = None
            self._update_crop_label()
            self.lbl_file.config(text=path.split("/")[-1])
            self._rasterise_page(0)
            self._update_page_label()
        except Exception as e:
            messagebox.showerror("Error", f"Could not open PDF:\n{e}")

    def _open_images(self, paths: list[str] | None = None):
        if paths is None:
            paths = list(filedialog.askopenfilenames(
                title="Open image(s)",
                filetypes=[
                    ("Images", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"),
                    ("PNG",  "*.png"),
                    ("JPEG", "*.jpg *.jpeg"),
                    ("BMP",  "*.bmp"),
                    ("TIFF", "*.tif *.tiff"),
                    ("All files", "*.*"),
                ]))
        if not paths:
            return
        self.status_var.set("Loading…")
        self.update_idletasks()
        try:
            # load all images eagerly (they're already rasterised)
            loaded = []
            for p in paths:
                img = Image.open(p).convert("RGB")
                img.load()  # force decode now, not lazily
                loaded.append(img)
            self.doc          = None
            self._source_type = "images"
            self._image_paths = list(paths)
            self.page_index   = 0
            self.raw_pages    = loaded
            self.crop_norm    = None
            self._update_crop_label()
            label = paths[0].split("/")[-1]
            if len(paths) > 1:
                label += f"  (+{len(paths)-1} more)"
            self.lbl_file.config(text=label)
            self._refresh_canvas()
            self._update_page_label()
        except Exception as e:
            messagebox.showerror("Error", f"Could not open image(s):\n{e}")

    def _rasterise_page(self, idx):
        if self._source_type == "images":
            # images are already loaded into raw_pages; nothing to rasterise
            self._refresh_canvas()
            return
        if idx >= len(self.raw_pages):
            self.raw_pages.extend([None]*(idx+1-len(self.raw_pages)))
        if self.raw_pages[idx] is None:
            page = self.doc[idx]
            mat  = fitz.Matrix(PREVIEW_DPI/72, PREVIEW_DPI/72)
            pix  = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
            self.raw_pages[idx] = Image.frombytes("RGB",(pix.width,pix.height),pix.samples)
        self._refresh_canvas()

    def _prev_page(self):
        if self.raw_pages and self.page_index > 0:
            self.page_index -= 1
            self._rasterise_page(self.page_index)
            self._update_page_label()

    def _next_page(self):
        total = len(self.raw_pages) if self._source_type == "images" else (len(self.doc) if self.doc else 0)
        if self.raw_pages and self.page_index < total - 1:
            self.page_index += 1
            self._rasterise_page(self.page_index)
            self._update_page_label()

    def _update_page_label(self):
        if self._source_type == "images":
            n = len(self.raw_pages)
        else:
            n = len(self.doc) if self.doc else 0
        self.lbl_page.config(text=f"Page {self.page_index+1} / {n}")

    # preview
    def _schedule_update(self, *_):
        if self._preview_job:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(80, self._refresh_canvas)

    def _refresh_canvas(self):
        if not self.raw_pages or self.page_index >= len(self.raw_pages):
            return
        raw = self.raw_pages[self.page_index]
        if raw is None:
            return

        params  = self._get_params()
        compare = self.compare_var.get()
        zoom    = self.zoom_var.get()

        def _worker():
            result = raw.copy() if compare else process_page(raw, params)
            if abs(zoom-1.0) > 0.02:
                result = result.resize((int(result.width*zoom),int(result.height*zoom)),
                                       Image.LANCZOS)
            self.after(0, lambda: self._show_image(result))

        threading.Thread(target=_worker, daemon=True).start()

    def _show_image(self, img):
        tk_img = ImageTk.PhotoImage(img)
        self._tk_img  = tk_img
        self._overlay = []
        self.canvas.delete("all")
        self.canvas.config(scrollregion=(0,0,img.width,img.height))
        self.canvas.create_image(0, 0, anchor="nw", image=tk_img)
        self._redraw_overlay()
        # status
        s  = self._raw_size()
        cr = ""
        if self.crop_norm and s:
            pw = int((self.crop_norm[2]-self.crop_norm[0])*s[0])
            ph = int((self.crop_norm[3]-self.crop_norm[1])*s[1])
            cr = f"  │  ✂ {pw}×{ph}px"
        if self._source_type == "images":
            n = len(self.raw_pages)
        else:
            n = len(self.doc) if self.doc else "—"
        self.status_var.set(f"{img.width}×{img.height}px  │  Page {self.page_index+1}/{n}{cr}")

    def _cv_scroll(self, event):
        if event.delta:
            self.canvas.yview_scroll(-1*(event.delta//120), "units")
        elif event.num==4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num==5:
            self.canvas.yview_scroll(1,  "units")

    # helpers ─

    def _get_params(self):
        return {k: v.get() for k,v in self.vars.items()}

    def _reset_params(self):
        for k,v in DEFAULT_PARAMS.items():
            self.vars[k].set(v)

    # export

    def _export_pdf(self):
        if not self.raw_pages:
            messagebox.showwarning("No content", "Please open a PDF or images first.")
            return
        out_path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files","*.pdf")],
            title="Save restored PDF")
        if not out_path:
            return

        params    = self._get_params()
        crop_norm = self.crop_norm

        if self._source_type == "images":
            pages_raw = self.raw_pages
            n = len(pages_raw)
        else:
            n = len(self.doc)
            pages_raw = None  # will rasterise from doc per page

        try:
            out_doc = fitz.open()
            for i in range(n):
                self.status_var.set(f"Exporting page {i+1}/{n}…")
                self.update_idletasks()

                if self._source_type == "images":
                    raw = pages_raw[i]
                else:
                    page = self.doc[i]
                    mat  = fitz.Matrix(EXPORT_DPI/72, EXPORT_DPI/72)
                    pix  = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
                    raw  = Image.frombytes("RGB",(pix.width,pix.height),pix.samples)

                processed = process_page(raw, params, crop_norm)

                buf = io.BytesIO()
                processed.save(buf, format="JPEG", quality=92)

                if crop_norm:
                    ow = processed.width  * 72 / EXPORT_DPI
                    oh = processed.height * 72 / EXPORT_DPI
                elif self._source_type == "images":
                    ow = processed.width  * 72 / EXPORT_DPI
                    oh = processed.height * 72 / EXPORT_DPI
                else:
                    ow, oh = self.doc[i].rect.width, self.doc[i].rect.height

                new_page = out_doc.new_page(width=ow, height=oh)
                new_page.insert_image(new_page.rect, stream=buf.getvalue())

            out_doc.save(out_path, garbage=4, deflate=True)
            out_doc.close()
            self.status_var.set(f"Saved → {out_path}")
            messagebox.showinfo("Done",
                f"Exported {n} page(s) to:\n{out_path}"
                + ("\n\nCrop applied to all pages." if crop_norm else ""))
        except Exception as e:
            messagebox.showerror("Export failed", str(e))
            self.status_var.set("Export failed.")

if __name__ == "__main__":
    App().mainloop()