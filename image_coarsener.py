#!/usr/bin/env python3
"""Image coarsening / hole-shooting tool. Grayscale and colour.

Python 3.13 + Tkinter + Pillow.

Hole shooting uses circular shots with a selectable diameter. Shot centers are
taken from dark pixels on a dark/light boundary. Centers are spaced by at least
the shot diameter so a large brush does not turn into hundreds of overlapping
holes.

Presets are BLACK RETENTION:
  66% -> a candidate shot fires with probability 34%
  33% -> a candidate shot fires with probability 67%
   0% -> every candidate shot fires

Colour handling:
  Every dark/light decision runs on a luminance copy of the image, so the
  thresholds keep their old 0-255 meaning. Pixels are written in the image's
  own mode, so an RGB image stays RGB and an RGBA image keeps its alpha.
  The local background is the channel-wise mean of the substantially lighter
  8-neighbors of the shot center, so a hole picks up the colour of the material
  around it. A pixel is only ever lightened, never darkened.

  Images with alpha are composited onto white before the luminance pass, so a
  transparent background reads as light rather than as black.

  Modes that cannot be edited pixel-by-pixel (P, 1, CMYK, I, F, ...) are
  converted on load and converted back on save, so the file keeps its original
  mode and format.
"""

from __future__ import annotations

import math
import random
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageFilter, ImageTk


PRESETS = {
    "66% black retention": 0.66,
    "33% black retention": 0.33,
    "0% black retention": 0.00,
}

# Modes we can address pixel-by-pixel. Everything else is converted on load.
EDIT_MODES = {"L", "LA", "RGB", "RGBA"}

EDIT_MODE_FOR = {
    "1": "L",
    "I": "L",
    "I;16": "L",
    "I;16B": "L",
    "F": "L",
    "PA": "RGBA",
    "CMYK": "RGB",
    "YCbCr": "RGB",
    "LAB": "RGB",
    "HSV": "RGB",
}

# Modes each format accepts. None means "anything Pillow can hand it".
FORMAT_MODES: dict[str, set[str] | None] = {
    "JPEG": {"1", "L", "RGB", "CMYK"},
    "JPEG2000": {"L", "RGB", "RGBA"},
    "BMP": {"1", "L", "P", "RGB", "RGBA"},
    "DIB": {"1", "L", "P", "RGB", "RGBA"},
    "GIF": {"1", "L", "LA", "P", "RGB", "RGBA"},
    "PNG": {"1", "L", "LA", "P", "RGB", "RGBA", "I"},
    "TIFF": None,
    "WEBP": None,
}

# Ordered downgrades used when a format rejects the original mode.
MODE_FALLBACKS = {
    "1": ["L", "RGB"],
    "I": ["L", "RGB"],
    "F": ["L", "RGB"],
    "P": ["RGB", "L"],
    "PA": ["RGBA", "RGB"],
    "LA": ["L", "RGBA", "RGB"],
    "RGBA": ["RGB"],
    "CMYK": ["RGB"],
    "YCbCr": ["RGB"],
    "LAB": ["RGB"],
    "HSV": ["RGB"],
}

OPEN_FILETYPES = [
    ("All images", "*.png *.bmp *.tif *.tiff *.jpg *.jpeg *.gif *.webp"),
    ("PNG files", "*.png"),
    ("BMP files", "*.bmp"),
    ("TIFF files", "*.tif *.tiff"),
    ("JPEG files", "*.jpg *.jpeg"),
    ("GIF files", "*.gif"),
    ("WebP files", "*.webp"),
    ("All files", "*.*"),
]

SAVE_FILETYPES = [
    (".png", "PNG files"),
    (".bmp", "BMP files"),
    (".tif", "TIFF files"),
    (".tiff", "TIFF files"),
    (".jpg", "JPEG files"),
    (".jpeg", "JPEG files"),
    (".gif", "GIF files"),
    (".webp", "WebP files"),
]


@dataclass
class Selection:
    x0: int
    y0: int
    x1: int
    y1: int

    def normalized(self) -> "Selection":
        return Selection(
            min(self.x0, self.x1),
            min(self.y0, self.y1),
            max(self.x0, self.x1),
            max(self.y0, self.y1),
        )

    @property
    def empty(self) -> bool:
        s = self.normalized()
        return s.x0 == s.x1 or s.y0 == s.y1


# colour helpers

def edit_mode_for(img: Image.Image) -> str:
    """Mode we edit in. Same as the file's mode whenever that is possible."""
    if img.mode in EDIT_MODES:
        return img.mode
    if img.mode == "P":
        return "RGBA" if "transparency" in img.info else "RGB"
    return EDIT_MODE_FOR.get(img.mode, "RGB")


def flatten_onto_white(img: Image.Image) -> Image.Image:
    """Composite an alpha image onto white. Non-alpha images pass through."""
    if img.mode not in ("LA", "RGBA", "PA"):
        return img
    rgba = img.convert("RGBA")
    flat = Image.new("RGB", img.size, (255, 255, 255))
    flat.paste(rgba.convert("RGB"), mask=rgba.getchannel("A"))
    return flat.convert("L") if img.mode == "LA" else flat


def luminance(img: Image.Image) -> Image.Image:
    """Single channel used for every dark/light decision.

    Transparent areas read as light, not as whatever RGB hides under them.
    """
    if img.mode in ("LA", "RGBA", "PA"):
        return flatten_onto_white(img).convert("L")
    if img.mode == "L":
        return img.copy()
    return img.convert("L")


def fit_to_format(img: Image.Image, fmt: str | None) -> Image.Image:
    """Downgrade the mode only as far as the target format requires."""
    allowed = FORMAT_MODES.get((fmt or "").upper(), None)
    if allowed is None or img.mode in allowed:
        return img

    for target in MODE_FALLBACKS.get(img.mode, ["RGB"]):
        if target in allowed:
            if img.mode in ("LA", "RGBA", "PA") and target in ("L", "RGB"):
                flat = flatten_onto_white(img)
                return flat if flat.mode == target else flat.convert(target)
            return img.convert(target)

    return img.convert("RGB")


# hole shooting

def boundary_candidates(
    src: Image.Image,
    lum: Image.Image,
    selection: Selection,
    dark_t: int,
    light_delta: int,
) -> list[tuple[int, int, int | tuple[int, ...], int]]:
    """Return (x, y, background_pixel, background_luminance) for dark edges."""
    bands = len(src.getbands())

    # A 3x3 maximum over the luminance rules out interior dark pixels before
    # the 8-neighbor loop runs. One pixel of margin keeps the result exact.
    px0 = max(0, selection.x0 - 1)
    py0 = max(0, selection.y0 - 1)
    px1 = min(lum.width, selection.x1 + 1)
    py1 = min(lum.height, selection.y1 + 1)
    brightest = lum.crop((px0, py0, px1, py1)).filter(ImageFilter.MaxFilter(3))

    sp = src.load()
    lp = lum.load()
    bp = brightest.load()
    candidates: list[tuple[int, int, int | tuple[int, ...], int]] = []

    for y in range(selection.y0, selection.y1):
        for x in range(selection.x0, selection.x1):
            v = lp[x, y]
            if v > dark_t:
                continue
            if bp[x - px0, y - py0] < v + light_delta:
                continue

            sums = [0] * bands
            lum_sum = 0
            count = 0

            for ny in range(max(0, y - 1), min(src.height, y + 2)):
                for nx in range(max(0, x - 1), min(src.width, x + 2)):
                    if nx == x and ny == y:
                        continue
                    nv = lp[nx, ny]
                    if nv < v + light_delta:
                        continue
                    pixel = sp[nx, ny]
                    if bands == 1:
                        sums[0] += pixel
                    else:
                        for i in range(bands):
                            sums[i] += pixel[i]
                    lum_sum += nv
                    count += 1

            if count:
                mean = tuple(round(s / count) for s in sums)
                bg = mean[0] if bands == 1 else mean
                candidates.append((x, y, bg, round(lum_sum / count)))

    return candidates


def space_shot_centers(candidates: list, diameter: int, rng: random.Random) -> list:
    """Thin boundary candidates so large shots do not heavily overlap."""
    if not candidates:
        return []

    # Randomize the order so the retained pattern is not biased toward
    # the top-left corner of the image.
    candidates = list(candidates)
    rng.shuffle(candidates)

    cell = max(1, diameter)
    min_distance_sq = float(diameter * diameter)
    grid: dict[tuple[int, int], list[tuple[int, int]]] = {}
    accepted: list = []

    for candidate in candidates:
        cx, cy = candidate[0], candidate[1]
        gx, gy = cx // cell, cy // cell
        too_close = False

        for nx in range(gx - 1, gx + 2):
            for ny in range(gy - 1, gy + 2):
                for ax, ay in grid.get((nx, ny), []):
                    if (cx - ax) ** 2 + (cy - ay) ** 2 < min_distance_sq:
                        too_close = True
                        break
                if too_close:
                    break
            if too_close:
                break

        if not too_close:
            accepted.append(candidate)
            grid.setdefault((gx, gy), []).append((cx, cy))

    return accepted


def shoot_holes_on(
    img: Image.Image,
    selection: Selection,
    *,
    dark_t: int,
    light_delta: int,
    diameter: int,
    retention: float,
    rng: random.Random | None = None,
) -> tuple[Image.Image, int, int, int]:
    """Shoot holes into one rectangle. Returns (image, fired, centers, pixels)."""
    rng = rng or random.Random()
    lum = luminance(img)
    dst = img.copy()
    lp = lum.load()
    dp = dst.load()

    candidates = boundary_candidates(img, lum, selection, dark_t, light_delta)
    centers = space_shot_centers(candidates, diameter, rng)

    radius = (diameter - 1) / 2.0
    fired = 0
    changed = 0

    for cx, cy, bg, bg_lum in centers:
        # "Black retention" is the probability that a possible shot is skipped.
        if rng.random() < retention:
            continue

        fired += 1

        xmin = max(selection.x0, math.floor(cx - radius))
        xmax = min(selection.x1 - 1, math.ceil(cx + radius))
        ymin = max(selection.y0, math.floor(cy - radius))
        ymax = min(selection.y1 - 1, math.ceil(cy + radius))

        for y in range(ymin, ymax + 1):
            for x in range(xmin, xmax + 1):
                if (x - cx) ** 2 + (y - cy) ** 2 > radius * radius:
                    continue

                # Only shoot dark material, and only ever lighten it. Existing
                # background inside the circle stays untouched.
                v = lp[x, y]
                if v > dark_t or bg_lum <= v or dp[x, y] == bg:
                    continue

                dp[x, y] = bg
                changed += 1

    return dst, fired, len(centers), changed


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Image Coarsener — Hole Shooting")
        self.root.geometry("1200x850")
        self.root.minsize(800, 600)

        self.image: Image.Image | None = None
        self.original_path: Path | None = None
        self.original_mode: str = "RGB"
        self.original_format: str | None = None
        self.source_info: dict = {}
        self.palette_source: Image.Image | None = None
        self.tk_image: ImageTk.PhotoImage | None = None
        self.selection: Selection | None = None
        self.drag_start: tuple[int, int] | None = None
        self.selection_canvas_id: int | None = None
        self.undo_stack: list[Image.Image] = []
        self.max_undo = 12

        self.display_scale = 1.0
        self.display_offset = (0, 0)
        self.photo_size = (1, 1)

        self.black_threshold = tk.IntVar(value=60)
        self.light_delta = tk.IntVar(value=55)
        self.shot_size = tk.IntVar(value=7)
        self.blur_size = tk.IntVar(value=21)
        self.preset = tk.StringVar(value="66% black retention")
        self.tool = tk.StringVar(value="select")
        self.status = tk.StringVar(value="Open an image, then drag a rectangle.")

        self._build_ui()
        self.root.bind("<Control-o>", lambda _e: self.open_image())
        self.root.bind("<Control-s>", lambda _e: self.save_image())
        self.root.bind("<Control-z>", lambda _e: self.undo())
        self.root.bind("<Escape>", lambda _e: self.clear_selection())

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self.root, padding=6)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(toolbar, text="Open…", command=self.open_image).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(toolbar, text="Save…", command=self.save_image).pack(side=tk.LEFT, padx=4)
        ttk.Button(toolbar, text="Undo", command=self.undo).pack(side=tk.LEFT, padx=4)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Radiobutton(
            toolbar, text="Rectangle select", variable=self.tool, value="select"
        ).pack(side=tk.LEFT, padx=4)
        ttk.Radiobutton(
            toolbar, text="Blur brush", variable=self.tool, value="blur"
        ).pack(side=tk.LEFT, padx=4)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Label(toolbar, text="Hole mode:").pack(side=tk.LEFT, padx=(4, 3))
        preset_box = ttk.Combobox(
            toolbar,
            textvariable=self.preset,
            values=list(PRESETS),
            state="readonly",
            width=19,
        )
        preset_box.pack(side=tk.LEFT, padx=3)

        ttk.Label(toolbar, text="Shot size:").pack(side=tk.LEFT, padx=(10, 2))
        ttk.Spinbox(
            toolbar,
            from_=1,
            to=301,
            increment=2,
            textvariable=self.shot_size,
            width=6,
        ).pack(side=tk.LEFT)

        ttk.Label(toolbar, text="px").pack(side=tk.LEFT, padx=(2, 3))
        ttk.Button(toolbar, text="Shoot holes", command=self.shoot_holes).pack(
            side=tk.LEFT, padx=6
        )

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Label(toolbar, text="Blur size:").pack(side=tk.LEFT, padx=(3, 2))
        ttk.Spinbox(
            toolbar,
            from_=1,
            to=301,
            increment=2,
            textvariable=self.blur_size,
            width=6,
        ).pack(side=tk.LEFT)

        settings = ttk.Frame(self.root, padding=(8, 0, 8, 6))
        settings.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(settings, text="Dark threshold").pack(side=tk.LEFT)
        ttk.Scale(
            settings,
            from_=0,
            to=255,
            variable=self.black_threshold,
            orient=tk.HORIZONTAL,
            length=180,
        ).pack(side=tk.LEFT, padx=6)
        ttk.Label(settings, textvariable=self.black_threshold, width=4).pack(side=tk.LEFT)

        ttk.Label(settings, text="Light-neighbor delta").pack(side=tk.LEFT, padx=(18, 0))
        ttk.Scale(
            settings,
            from_=1,
            to=150,
            variable=self.light_delta,
            orient=tk.HORIZONTAL,
            length=180,
        ).pack(side=tk.LEFT, padx=6)
        ttk.Label(settings, textvariable=self.light_delta, width=4).pack(side=tk.LEFT)
        ttk.Label(settings, text="(0–255 luminance)").pack(side=tk.LEFT, padx=8)

        self.canvas = tk.Canvas(
            self.root, background="#202020", highlightthickness=0, cursor="crosshair"
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", lambda _e: self.refresh_canvas())
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Motion>", self.on_motion)

        ttk.Label(
            self.root, textvariable=self.status, anchor="w", padding=(8, 4)
        ).pack(side=tk.BOTTOM, fill=tk.X)

    # image I/O
    def open_image(self) -> None:
        filename = filedialog.askopenfilename(
            title="Open image",
            filetypes=OPEN_FILETYPES,
        )
        if not filename:
            return
        try:
            with Image.open(filename) as handle:
                handle.load()
                self.original_mode = handle.mode
                self.original_format = handle.format
                self.source_info = dict(handle.info)
                self.palette_source = handle.copy() if handle.mode == "P" else None
                work_mode = edit_mode_for(handle)
                img = handle.copy() if handle.mode == work_mode else handle.convert(work_mode)
        except Exception as exc:
            messagebox.showerror("Open failed", str(exc))
            return

        self.image = img
        self.original_path = Path(filename)
        self.undo_stack.clear()
        self.clear_selection()

        note = "" if img.mode == self.original_mode else f", edited as {img.mode}"
        self.status.set(
            f"Loaded {Path(filename).name} — {img.width}×{img.height}px, "
            f"{self.original_format or '?'} {self.original_mode}{note}"
        )
        self.refresh_canvas()

    def save_image(self) -> None:
        if self.image is None:
            messagebox.showinfo("Nothing to save", "Open an image first.")
            return

        suffix = self.original_path.suffix.lower() if self.original_path else ".png"
        known = [ext for ext, _ in SAVE_FILETYPES]
        types: list[tuple[str, str]] = []
        seen: set[str] = set()
        for ext, label in sorted(SAVE_FILETYPES, key=lambda e: e[0] != suffix):
            if label in seen:
                continue
            seen.add(label)
            patterns = " ".join(f"*{e}" for e, lab in SAVE_FILETYPES if lab == label)
            types.append((label, patterns))
        default_ext = suffix if suffix in known else ".png"

        initial = self.original_path.stem if self.original_path else "coarsened"
        filename = filedialog.asksaveasfilename(
            title="Save image",
            initialfile=initial,
            defaultextension=default_ext,
            filetypes=types,
        )
        if not filename:
            return

        out, params = self.prepare_for_save(Path(filename))
        try:
            out.save(filename, **params)
        except Exception:
            try:
                out.save(filename)
            except Exception as exc:
                messagebox.showerror("Save failed", str(exc))
                return
            self.status.set(f"Saved {Path(filename).name} ({out.mode}, metadata dropped)")
            return

        self.status.set(f"Saved {Path(filename).name} — {out.mode}")

    def restore_original_mode(self, img: Image.Image) -> Image.Image:
        """Convert the working image back to the mode the file arrived in."""
        target = self.original_mode
        if img.mode == target:
            return img

        if target == "P":
            base = img.convert("RGB")
            if self.palette_source is not None:
                try:
                    return base.quantize(
                        palette=self.palette_source, dither=Image.Dither.NONE
                    )
                except Exception:
                    pass
            return base.convert("P", palette=Image.Palette.ADAPTIVE, colors=256)

        if target == "1":
            return img.convert("L").convert("1", dither=Image.Dither.NONE)

        if target in ("CMYK", "YCbCr", "LAB", "HSV"):
            return flatten_onto_white(img).convert(target)

        try:
            return img.convert(target)
        except ValueError:
            return img

    def prepare_for_save(self, path: Path) -> tuple[Image.Image, dict]:
        """Restore the original mode, fit it to the target format, carry metadata."""
        assert self.image is not None
        fmt = Image.registered_extensions().get(path.suffix.lower(), self.original_format)
        img = fit_to_format(self.restore_original_mode(self.image), fmt)

        params: dict = {}
        info = self.source_info

        if fmt in ("PNG", "JPEG", "TIFF", "WEBP"):
            if info.get("dpi"):
                params["dpi"] = info["dpi"]
            if info.get("icc_profile"):
                params["icc_profile"] = info["icc_profile"]
            if info.get("exif"):
                params["exif"] = info["exif"]

        if fmt == "JPEG":
            params.update(quality=95, subsampling=0)
        elif fmt == "WEBP":
            params.update(quality=95, method=6)
        elif fmt == "TIFF" and info.get("compression"):
            params["compression"] = info["compression"]

        if fmt in ("PNG", "GIF") and img.mode == "P" and isinstance(info.get("transparency"), int):
            params["transparency"] = info["transparency"]

        return img, params

    # canvas mapping
    def _fit_geometry(self) -> tuple[float, int, int, int, int]:
        assert self.image is not None
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        iw, ih = self.image.size
        scale = min(cw / iw, ch / ih)
        dx = int((cw - iw * scale) / 2)
        dy = int((ch - ih * scale) / 2)
        return scale, dx, dy, max(1, int(iw * scale)), max(1, int(ih * scale))

    def canvas_to_image(self, x: int, y: int) -> tuple[int, int] | None:
        if self.image is None:
            return None
        scale, dx, dy, _, _ = self._fit_geometry()
        ix = int((x - dx) / scale)
        iy = int((y - dy) / scale)
        if 0 <= ix < self.image.width and 0 <= iy < self.image.height:
            return ix, iy
        return None

    def image_to_canvas(self, x: int, y: int) -> tuple[int, int]:
        scale, dx, dy, _, _ = self._fit_geometry()
        return int(dx + x * scale), int(dy + y * scale)

    def refresh_canvas(self) -> None:
        self.canvas.delete("all")
        if self.image is None:
            return

        scale, dx, dy, dw, dh = self._fit_geometry()
        display = self.image.resize(
            (dw, dh),
            Image.Resampling.NEAREST if scale >= 1 else Image.Resampling.LANCZOS,
        )
        self.tk_image = ImageTk.PhotoImage(display)
        self.canvas.create_image(
            dx, dy, image=self.tk_image, anchor=tk.NW, tags="image"
        )
        self.display_scale = scale
        self.display_offset = (dx, dy)
        self.photo_size = (dw, dh)
        self.draw_selection()

    # selection
    def on_press(self, event: tk.Event) -> None:
        if self.image is None:
            return

        if self.tool.get() == "blur":
            self.push_undo()
            self.apply_blur_at(event.x, event.y)
            return

        p = self.canvas_to_image(event.x, event.y)
        if p is None:
            return

        self.drag_start = p
        self.selection = Selection(*p, *p)
        self.draw_selection()

    def on_drag(self, event: tk.Event) -> None:
        if self.image is None:
            return

        if self.tool.get() == "blur":
            self.apply_blur_at(event.x, event.y)
            return

        if self.drag_start is None:
            return

        p = self.canvas_to_image(event.x, event.y)
        if p is None:
            return

        self.selection = Selection(*self.drag_start, *p)
        self.draw_selection()

    def on_release(self, event: tk.Event) -> None:
        if (
            self.image is None
            or self.tool.get() == "blur"
            or self.drag_start is None
        ):
            return

        p = self.canvas_to_image(event.x, event.y)
        if p is not None:
            self.selection = Selection(*self.drag_start, *p).normalized()

        self.drag_start = None

        if self.selection and not self.selection.empty:
            s = self.selection.normalized()
            self.status.set(
                f"Selected x={s.x0}:{s.x1}, y={s.y0}:{s.y1}  "
                f"({s.x1-s.x0}×{s.y1-s.y0}px)"
            )

        self.draw_selection()

    def on_motion(self, event: tk.Event) -> None:
        if self.image is None:
            return

        p = self.canvas_to_image(event.x, event.y)
        if p is not None:
            self.status.set(f"Cursor: {p[0]}, {p[1]} px")

    def draw_selection(self) -> None:
        if self.selection_canvas_id is not None:
            self.canvas.delete(self.selection_canvas_id)
            self.selection_canvas_id = None

        if self.image is None or self.selection is None or self.selection.empty:
            return

        s = self.selection.normalized()
        x0, y0 = self.image_to_canvas(s.x0, s.y0)
        x1, y1 = self.image_to_canvas(s.x1, s.y1)

        self.selection_canvas_id = self.canvas.create_rectangle(
            x0, y0, x1, y1, outline="#ff3b30", width=2, dash=(6, 4)
        )

    def clear_selection(self) -> None:
        self.selection = None
        self.drag_start = None
        self.draw_selection()

    # undo
    def push_undo(self) -> None:
        if self.image is not None:
            self.undo_stack.append(self.image.copy())
            if len(self.undo_stack) > self.max_undo:
                self.undo_stack.pop(0)

    def undo(self) -> None:
        if not self.undo_stack:
            return

        self.image = self.undo_stack.pop()
        self.refresh_canvas()
        self.status.set("Undo applied")

    # hole shooting
    def shoot_holes(self) -> None:
        if self.image is None:
            messagebox.showinfo("No image", "Open an image first.")
            return

        if self.selection is None or self.selection.empty:
            messagebox.showinfo("No rectangle", "Select a rectangle first.")
            return

        keep = PRESETS[self.preset.get()]
        dark_t = int(self.black_threshold.get())
        light_delta = int(self.light_delta.get())
        diameter = max(1, int(self.shot_size.get()))
        if diameter % 2 == 0:
            diameter += 1
            self.shot_size.set(diameter)

        s = self.selection.normalized()
        self.push_undo()

        self.status.set("Shooting…")
        self.root.update_idletasks()

        dst, fired, centers, changed = shoot_holes_on(
            self.image,
            s,
            dark_t=dark_t,
            light_delta=light_delta,
            diameter=diameter,
            retention=keep,
        )

        self.image = dst
        self.refresh_canvas()
        self.status.set(
            f"Fired {fired:,}/{centers:,} shots, changed {changed:,} px — "
            f"{self.preset.get()}, shot Ø{diameter}px, dark≤{dark_t}, "
            f"light delta≥{light_delta}"
        )

    # blur brush
    def apply_blur_at(self, canvas_x: int, canvas_y: int) -> None:
        if self.image is None:
            return

        p = self.canvas_to_image(canvas_x, canvas_y)
        if p is None:
            return

        cx, cy = p
        size = max(1, int(self.blur_size.get()))
        if size % 2 == 0:
            size += 1

        radius = size // 2
        x0 = max(0, cx - radius)
        y0 = max(0, cy - radius)
        x1 = min(self.image.width, cx + radius + 1)
        y1 = min(self.image.height, cy + radius + 1)

        crop = self.image.crop((x0, y0, x1, y1))
        blurred = crop.filter(ImageFilter.GaussianBlur(max(0.5, size / 6)))
        self.image.paste(blurred, (x0, y0))
        self.refresh_canvas()


def main() -> None:
    root = tk.Tk()
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
