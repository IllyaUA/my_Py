#!/usr/bin/env python3
# offline document scanner / cleaner
# open a photo of a document, adjust the four crop corners, deskew, flatten
# shadows and gradients, pick an output filter, and export PNG or PDF.
# single document at a time.
#
# geometry assumes a flat page: a trapezoid-to-rectangle perspective warp plus an
# optional uniform deskew rotation. both map every kind of content the same way,
# so text, images, tables and ruled lines all come out straight. decurl (the
# text-row remap) is a separate opt-in for genuinely bent or curled pages and is
# off by default because it warps non-text content.
#
# deps: opencv-python, numpy, pillow  (tkinter ships with python)
#   pip install opencv-python numpy pillow

import os
import sys
import math
import numpy as np

try:
    import cv2
except ImportError:
    sys.exit("opencv missing: pip install opencv-python")

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except ImportError:
    tk = None  # checked in main()

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = ImageTk = None  # checked in main()


# image pipeline (pure functions, no gui state)

def order_pts(pts):
    # return corners as tl, tr, br, bl
    pts = np.asarray(pts, dtype=np.float32)
    s = pts.sum(1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)],
                     pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def full_quad(shape):
    # quad covering the whole image
    h, w = shape[:2]
    return np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)


def estimate_corners(bgr):
    # auto detect the page as the largest bright low-saturation region
    h, w = bgr.shape[:2]
    scale = 1000.0 / max(h, w)
    small = cv2.resize(bgr, None, fx=scale, fy=scale)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    mask = ((s < 60) & (v > 90)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return full_quad(bgr.shape)
    c = max(cnts, key=cv2.contourArea)
    area_frac = cv2.contourArea(c) / (small.shape[0] * small.shape[1])
    approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
    if len(approx) == 4 and area_frac > 0.15:
        return order_pts(approx.reshape(-1, 2) / scale)
    # fallback to the bounding box of the largest region
    x, y, ww, hh = cv2.boundingRect(c)
    quad = np.array([[x, y], [x + ww, y], [x + ww, y + hh], [x, y + hh]], dtype=np.float32) / scale
    return order_pts(quad)


def warp(bgr, quad, aspect=None):
    # perspective correct the quad to a flat rectangle
    # aspect = height / width; None means infer from the quad
    tl, tr, br, bl = order_pts(quad)
    wa = np.linalg.norm(br - bl)
    wb = np.linalg.norm(tr - tl)
    ha = np.linalg.norm(tr - br)
    hb = np.linalg.norm(tl - bl)
    W = max(int(round(max(wa, wb))), 1)
    if aspect is None:
        H = max(int(round(max(ha, hb))), 1)
    else:
        H = max(int(round(W * aspect)), 1)
    src = order_pts(quad)
    dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(bgr, M, (W, H), flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_REPLICATE)


def rotate(img, deg):
    # rotate about center, fill new area with white
    if abs(deg) < 1e-3:
        return img
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), deg, 1.0)
    border = (255, 255, 255) if img.ndim == 3 else 255
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=border)


def _proj_sharpness(gray, a):
    # how cleanly horizontal structure lines up with image rows after rotating by a
    h, w = gray.shape
    M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), a, 1.0)
    r = cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_NEAREST, borderValue=255)
    proj = (r < 128).sum(axis=1).astype(np.float64)
    return ((proj[1:] - proj[:-1]) ** 2).sum()


def auto_deskew_angle(gray):
    # general skew estimate from dominant straight structure: text rows, table
    # rules, figure borders and underlines all count. a uniform rotation, so it
    # transforms every kind of content the same way.
    scale = 1200.0 / max(gray.shape)
    small = cv2.resize(gray, None, fx=scale, fy=scale) if scale < 1 else gray
    edges = cv2.Canny(small, 60, 160)
    segs = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=100,
                           minLineLength=small.shape[1] // 5, maxLineGap=20)
    devs = []
    if segs is not None:
        for x1, y1, x2, y2 in segs[:, 0]:
            a = math.degrees(math.atan2(y2 - y1, x2 - x1))
            dev = ((a + 45) % 90) - 45  # deviation from the nearest horizontal/vertical
            if abs(dev) < 12:
                devs.append(dev)
    if len(devs) >= 8:
        cand = float(np.median(devs))
    else:
        # fallback: brute-force the rotation that best aligns dark ink into rows
        cands = list(np.arange(-10, 10.01, 0.25))
        return float(max(cands, key=lambda a: _proj_sharpness(small, a)))
    # confirm sign and refine, since a line angle is ambiguous up to its rotation sense
    best = max([cand, -cand, 0.0], key=lambda a: _proj_sharpness(small, a))
    best = float(max(np.arange(best - 1.0, best + 1.01, 0.1),
                     key=lambda a: _proj_sharpness(small, a)))
    return best


def _baselines(gray):
    # find text rows and fit a straight baseline to each
    th = (gray < 90).astype(np.uint8) * 255
    band = cv2.dilate(th, cv2.getStructuringElement(cv2.MORPH_RECT, (81, 3)))
    band = cv2.morphologyEx(band, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 9)))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(band)
    H, W = gray.shape
    lines = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w < W * 0.20 or h < 6 or h > H * 0.12 or area < W * 2:
            continue
        xs, ys = [], []
        for cx in range(x, x + w, 4):
            col = np.where(th[y:y + h, cx] > 0)[0]
            if len(col):
                xs.append(cx)
                ys.append(y + col.mean())
        if len(xs) < 8:
            continue
        m, b = np.polyfit(xs, ys, 1)
        lines.append((m, b))
    return lines


def dewarp_lines(bgr):
    # straighten page curl by remapping every detected text baseline to horizontal
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    lines = _baselines(gray)
    if len(lines) < 3:
        return bgr
    H, W = gray.shape
    cx = W / 2.0
    xf = np.arange(W)
    centers, rows = [], []
    for m, b in lines:
        yc = m * cx + b
        centers.append(yc)
        rows.append(m * xf + b - yc)  # vertical deviation from flat at each x
    order = np.argsort(centers)
    centers = np.array(centers)[order]
    rows = np.array(rows)[order]
    ys = np.arange(H)
    disp = np.empty((H, W), np.float32)
    for x in range(W):
        disp[:, x] = np.interp(ys, centers, rows[:, x], left=rows[0, x], right=rows[-1, x])
    map_x = np.tile(xf.astype(np.float32), (H, 1))
    map_y = np.tile(ys.reshape(-1, 1), (1, W)).astype(np.float32) + disp
    return cv2.remap(bgr, map_x, map_y, interpolation=cv2.INTER_CUBIC,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))


def _background(gray, k):
    # bright envelope of the paper: closing removes dark text, blur smooths it
    k = int(k) | 1
    bg = cv2.morphologyEx(gray, cv2.MORPH_CLOSE,
                          cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    bg = cv2.GaussianBlur(bg, (0, 0), max(k / 6.0, 1.0))
    return bg


def flatten_gray(gray, strength):
    # divide out the illumination so shadows and gradients go to even white
    if strength <= 0:
        return gray
    k = max(15, (max(gray.shape) // 30))
    bg = _background(gray, k).astype(np.float32)
    norm = np.clip(gray.astype(np.float32) / (bg + 1e-6), 0, 1) * 255.0
    out = (1.0 - strength) * gray.astype(np.float32) + strength * norm
    return np.clip(out, 0, 255).astype(np.uint8)


def flatten_color(bgr, strength):
    # same illumination flattening applied per channel, keeps coloured ink
    if strength <= 0:
        return bgr
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    k = max(15, (max(gray.shape) // 30))
    bg = _background(gray, k).astype(np.float32)
    gain = np.clip(255.0 / (bg + 1e-6), 1.0, 4.0)
    boosted = np.clip(bgr.astype(np.float32) * gain[..., None], 0, 255)
    out = (1.0 - strength) * bgr.astype(np.float32) + strength * boosted
    return np.clip(out, 0, 255).astype(np.uint8)


def level(gray, black, white, gamma=1.0):
    # map [black, white] to [0, 255], crush mid greys toward white when white is low
    black = float(black)
    white = float(max(white, black + 1))
    out = np.clip((gray.astype(np.float32) - black) / (white - black), 0, 1)
    if abs(gamma - 1.0) > 1e-3:
        out = out ** gamma
    return (out * 255.0).astype(np.uint8)


def process(bgr, mode, shadow, black, white, deskew):
    # full filter chain on an already-cropped/warped colour image
    img = rotate(bgr, deskew)

    if mode == "Color":
        return img
    if mode == "Grayscale":
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if mode == "Document Color":
        return flatten_color(img, shadow)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = flatten_gray(gray, shadow)
    if mode == "Document Gray":
        return level(gray, black, white)
    if mode == "Document B/W":
        lv = level(gray, black, white)
        return cv2.threshold(lv, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    return img


def to_pil(img):
    # opencv bgr/gray to a pillow image for display and saving
    if img.ndim == 2:
        return Image.fromarray(img)
    return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))


# gui

ASPECTS = {
    "Auto": None,
    "A4 portrait": 1.41421,
    "A4 landscape": 0.70711,
    "Letter portrait": 1.29412,
    "Letter landscape": 0.77273,
    "Square": 1.0,
}
MODES = ["Color", "Grayscale", "Document Color", "Document Gray", "Document B/W"]
PREVIEW_MAX = 950  # working size for live preview processing
HANDLE_R = 8


class App:
    def __init__(self, root):
        self.root = root
        root.title("Document Scanner")
        root.geometry("1280x820")

        self.src = None          # original bgr
        self.quad = None         # 4 corners in source pixel coords
        self.scale = 1.0         # source -> source-canvas display scale
        self.drag = None         # index of the corner being dragged
        self.path = None
        self._after = None       # debounce handle
        self.pages = []          # queued processed pages (numpy arrays) for multi-page pdf

        self._build_ui()
        self.root.bind("<Left>", lambda e: self._nudge(-1, 0))
        self.root.bind("<Right>", lambda e: self._nudge(1, 0))
        self.root.bind("<Up>", lambda e: self._nudge(0, -1))
        self.root.bind("<Down>", lambda e: self._nudge(0, 1))

    def _build_ui(self):
        bar = ttk.Frame(self.root, padding=6)
        bar.pack(side=tk.TOP, fill=tk.X)
        ttk.Button(bar, text="Open\u2026", command=self.open_image).pack(side=tk.LEFT)
        ttk.Button(bar, text="Auto-detect", command=self.auto_detect).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="Reset corners", command=self.reset_corners).pack(side=tk.LEFT)
        ttk.Button(bar, text="Rotate \u27f2", command=lambda: self.rotate90("ccw")).pack(side=tk.LEFT, padx=(12, 2))
        ttk.Button(bar, text="Rotate \u27f3", command=lambda: self.rotate90("cw")).pack(side=tk.LEFT)
        ttk.Button(bar, text="Auto deskew", command=self.auto_deskew).pack(side=tk.LEFT, padx=12)

        ttk.Button(bar, text="Export PDF", command=self.export_pdf).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bar, text="Export PNG", command=self.export_png).pack(side=tk.RIGHT)
        # multi-page queue: process each page, add it, then export the lot as one pdf
        sep = ttk.Separator(bar, orient=tk.VERTICAL)
        sep.pack(side=tk.RIGHT, fill=tk.Y, padx=8)
        self.pages_lbl = ttk.Label(bar, text="0 pages")
        self.pages_lbl.pack(side=tk.RIGHT, padx=4)
        ttk.Button(bar, text="Clear", command=self.clear_pages).pack(side=tk.RIGHT)
        ttk.Button(bar, text="Add page \u2192", command=self.add_page).pack(side=tk.RIGHT, padx=2)

        body = ttk.Frame(self.root)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # left: source with draggable corners
        left = ttk.LabelFrame(body, text="Source  (drag corners, arrow keys nudge)", padding=4)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.src_canvas = tk.Canvas(left, bg="#202225", highlightthickness=0)
        self.src_canvas.pack(fill=tk.BOTH, expand=True)
        self.src_canvas.bind("<ButtonPress-1>", self.on_press)
        self.src_canvas.bind("<B1-Motion>", self.on_drag)
        self.src_canvas.bind("<ButtonRelease-1>", self.on_release)

        # right: controls + preview
        right = ttk.Frame(body)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=6, pady=6)

        ctl = ttk.LabelFrame(right, text="Output", padding=8)
        ctl.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(ctl, text="Filter").grid(row=0, column=0, sticky="w")
        self.mode = tk.StringVar(value="Document Gray")
        cb = ttk.Combobox(ctl, textvariable=self.mode, values=MODES, state="readonly", width=18)
        cb.grid(row=0, column=1, sticky="w", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self.queue_preview())

        ttk.Label(ctl, text="Aspect").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.aspect = tk.StringVar(value="Auto")
        ab = ttk.Combobox(ctl, textvariable=self.aspect, values=list(ASPECTS), state="readonly", width=14)
        ab.grid(row=0, column=3, sticky="w", padx=4)
        ab.bind("<<ComboboxSelected>>", lambda e: self.queue_preview())

        self.shadow = self._slider(ctl, "Shadow removal", 1, 0, 100, 80)
        self.black = self._slider(ctl, "Black point", 2, 0, 255, 60)
        self.white = self._slider(ctl, "White point", 3, 0, 255, 150)
        self.deskew = self._slider(ctl, "Deskew (deg)", 4, -15, 15, 0, resolution=0.1)

        self.do_dewarp = tk.BooleanVar(value=False)
        ttk.Checkbutton(ctl, text="Decurl bent pages (text-only \u2014 distorts tables & images)",
                        variable=self.do_dewarp,
                        command=self.on_dewarp_toggle).grid(row=5, column=0, columnspan=4,
                                                            sticky="w", pady=(4, 0))

        prev = ttk.LabelFrame(right, text="Preview", padding=4)
        prev.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=(8, 0))
        self.prev_canvas = tk.Canvas(prev, bg="#202225", highlightthickness=0)
        self.prev_canvas.pack(fill=tk.BOTH, expand=True)

        self.status = ttk.Label(self.root, text="Open an image to begin.", anchor="w", padding=4)
        self.status.pack(side=tk.BOTTOM, fill=tk.X)

        self.src_canvas.bind("<Configure>", lambda e: self.redraw_source())
        self.prev_canvas.bind("<Configure>", lambda e: self.queue_preview())

    def on_dewarp_toggle(self):
        # decurl is a non-rigid remap driven by text rows; safe only on bent pages
        if self.do_dewarp.get():
            self.status.config(text="Decurl on: assumes a text page. Leave off for flat docs "
                                    "with tables, figures or lines.")
        self.queue_preview()

    def _slider(self, parent, label, row, lo, hi, val, resolution=1):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=2)
        var = tk.DoubleVar(value=val)
        s = tk.Scale(parent, from_=lo, to=hi, orient=tk.HORIZONTAL, variable=var,
                     resolution=resolution, length=320, showvalue=True,
                     command=lambda e: self.queue_preview())
        s.grid(row=row, column=1, columnspan=3, sticky="we", padx=4)
        return var

    # io

    def open_image(self):
        path = filedialog.askopenfilename(
            title="Open document photo",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp"), ("All files", "*.*")])
        if not path:
            return
        data = np.fromfile(path, dtype=np.uint8)  # handles non-ascii paths
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            messagebox.showerror("Open", "Could not read that file.")
            return
        self.src = img
        self.path = path
        self.deskew.set(0)
        self.quad = estimate_corners(img)
        self.redraw_source()
        self.queue_preview()
        h, w = img.shape[:2]
        self.status.config(text=f"{os.path.basename(path)}   {w}\u00d7{h}px")

    def _save_dialog(self, ext, kind):
        if self.src is None:
            return None
        base = os.path.splitext(os.path.basename(self.path or "document"))[0]
        return filedialog.asksaveasfilename(
            defaultextension=ext, initialfile=base + "_clean" + ext,
            filetypes=[(kind, "*" + ext)])

    # multi-page queue

    def _update_pages_lbl(self):
        n = len(self.pages)
        self.pages_lbl.config(text=f"{n} page" + ("" if n == 1 else "s"))

    def add_page(self):
        # render the current document at full resolution and queue it
        out = self._render(preview=False)
        if out is None:
            self.status.config(text="Open an image first.")
            return
        self.pages.append(out)
        self._update_pages_lbl()
        self.status.config(text=f"Added page {len(self.pages)}. "
                                f"Open the next page, then Add page; Export PDF when done.")

    def clear_pages(self):
        if not self.pages:
            return
        if messagebox.askyesno("Clear", f"Discard {len(self.pages)} queued page(s)?"):
            self.pages.clear()
            self._update_pages_lbl()
            self.status.config(text="Queue cleared.")

    def _pages_to_pil(self, imgs):
        # PDF wants L or RGB per page; convert each to its natural mode
        out = []
        for im in imgs:
            out.append(to_pil(im).convert("RGB" if im.ndim == 3 else "L"))
        return out

    def export_png(self):
        out = self._render(preview=False)
        if out is None:
            return
        path = self._save_dialog(".png", "PNG")
        if not path:
            return
        ok, buf = cv2.imencode(".png", out)
        if ok:
            buf.tofile(path)
            self.status.config(text="Saved " + os.path.basename(path))

    def export_pdf(self):
        # if pages are queued, export them as one multi-page pdf; otherwise export
        # the current single document. the current page is NOT auto-appended, so
        # remember to Add page for it if you want it included.
        if self.pages:
            imgs = list(self.pages)
            note = f"{len(imgs)} queued page(s)"
        else:
            out = self._render(preview=False)
            if out is None:
                return
            imgs = [out]
            note = "current page"
        path = self._save_dialog(".pdf", "PDF")
        if not path:
            return
        pages = self._pages_to_pil(imgs)
        pages[0].save(path, "PDF", resolution=200.0,
                      save_all=True, append_images=pages[1:])
        self.status.config(text=f"Saved {os.path.basename(path)}  ({note})")

    # corner detection and orientation

    def auto_detect(self):
        if self.src is None:
            return
        self.quad = estimate_corners(self.src)
        self.redraw_source()
        self.queue_preview()

    def reset_corners(self):
        if self.src is None:
            return
        self.quad = full_quad(self.src.shape)
        self.redraw_source()
        self.queue_preview()

    def rotate90(self, direction):
        if self.src is None:
            return
        h = self.src.shape[0]
        w = self.src.shape[1]
        if direction == "cw":
            self.src = np.ascontiguousarray(np.rot90(self.src, k=-1))
            pts = [(h - 1 - y, x) for (x, y) in self.quad]
        else:
            self.src = np.ascontiguousarray(np.rot90(self.src, k=1))
            pts = [(y, w - 1 - x) for (x, y) in self.quad]
        self.quad = order_pts(np.array(pts, dtype=np.float32))
        self.redraw_source()
        self.queue_preview()

    def auto_deskew(self):
        out = self._warped(preview=True)
        if out is None:
            return
        gray = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
        self.deskew.set(round(auto_deskew_angle(gray), 1))
        self.queue_preview()

    # corner dragging

    def redraw_source(self):
        c = self.src_canvas
        c.delete("all")
        if self.src is None:
            return
        h, w = self.src.shape[:2]
        cw = max(c.winfo_width(), 10)
        ch = max(c.winfo_height(), 10)
        self.scale = min(cw / w, ch / h)
        dw, dh = int(w * self.scale), int(h * self.scale)
        disp = cv2.resize(self.src, (dw, dh), interpolation=cv2.INTER_AREA)
        self._src_tk = ImageTk.PhotoImage(to_pil(disp))
        self.ox = (cw - dw) // 2
        self.oy = (ch - dh) // 2
        c.create_image(self.ox, self.oy, anchor="nw", image=self._src_tk)
        # quad outline
        pts = [self._to_canvas(p) for p in self.quad]
        flat = [v for p in pts for v in p]
        c.create_polygon(*flat, outline="#37c", width=2, fill="")
        # corner handles
        for i, (x, y) in enumerate(pts):
            fill = "#fc3" if self.drag == i else "#37c"
            c.create_oval(x - HANDLE_R, y - HANDLE_R, x + HANDLE_R, y + HANDLE_R,
                          fill=fill, outline="white", width=2)

    def _to_canvas(self, p):
        return (self.ox + p[0] * self.scale, self.oy + p[1] * self.scale)

    def _to_image(self, x, y):
        return ((x - self.ox) / self.scale, (y - self.oy) / self.scale)

    def on_press(self, e):
        if self.src is None:
            return
        for i, p in enumerate(self.quad):
            cx, cy = self._to_canvas(p)
            if (e.x - cx) ** 2 + (e.y - cy) ** 2 <= (HANDLE_R + 6) ** 2:
                self.drag = i
                self.redraw_source()
                return

    def on_drag(self, e):
        if self.drag is None or self.src is None:
            return
        h, w = self.src.shape[:2]
        x, y = self._to_image(e.x, e.y)
        self.quad[self.drag] = [min(max(x, 0), w - 1), min(max(y, 0), h - 1)]
        self.redraw_source()

    def on_release(self, e):
        if self.drag is not None:
            self.drag = None
            self.redraw_source()
            self.queue_preview()

    def _nudge(self, dx, dy):
        if self.drag is None or self.src is None:
            return
        h, w = self.src.shape[:2]
        x, y = self.quad[self.drag]
        self.quad[self.drag] = [min(max(x + dx, 0), w - 1), min(max(y + dy, 0), h - 1)]
        self.redraw_source()
        self.queue_preview()

    # preview rendering

    def _warped(self, preview):
        if self.src is None:
            return None
        img = self.src
        if preview:
            sc = PREVIEW_MAX / max(img.shape[:2])
            if sc < 1:
                small = cv2.resize(img, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA)
                return warp(small, np.asarray(self.quad) * sc, ASPECTS[self.aspect.get()])
        return warp(img, self.quad, ASPECTS[self.aspect.get()])

    def _render(self, preview):
        w = self._warped(preview)
        if w is None:
            return None
        if self.do_dewarp.get():
            w = dewarp_lines(w)
        return process(w, self.mode.get(), self.shadow.get() / 100.0,
                       self.black.get(), self.white.get(), self.deskew.get())

    def queue_preview(self):
        # debounce so dragging sliders does not stack up renders
        if self._after is not None:
            self.root.after_cancel(self._after)
        self._after = self.root.after(60, self.update_preview)

    def update_preview(self):
        self._after = None
        out = self._render(preview=True)
        if out is None:
            return
        c = self.prev_canvas
        cw = max(c.winfo_width(), 10)
        ch = max(c.winfo_height(), 10)
        h, w = out.shape[:2]
        sc = min(cw / w, ch / h)
        disp = cv2.resize(out, (max(int(w * sc), 1), max(int(h * sc), 1)),
                          interpolation=cv2.INTER_AREA)
        self._prev_tk = ImageTk.PhotoImage(to_pil(disp))
        c.delete("all")
        c.create_image(cw // 2, ch // 2, image=self._prev_tk)


def main():
    if tk is None:
        sys.exit("tkinter missing (install python3-tk on linux)")
    if Image is None:
        sys.exit("pillow missing: pip install pillow")
    root = tk.Tk()
    App(root)
    root.mainloop()


# entry point
if __name__ == "__main__":
    main()