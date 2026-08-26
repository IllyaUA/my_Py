#!/usr/bin/env python3
"""Grayscale coarsening / hole-shooting tool.

Python 3.13 + Tkinter + Pillow.

Hole shooting uses circular shots with a selectable diameter. Shot centers are
taken from dark pixels on a dark/light boundary. Centers are spaced by at least
the shot diameter so a large brush does not turn into hundreds of overlapping
holes.

Presets are BLACK RETENTION:
  66% -> a candidate shot fires with probability 34%
  33% -> a candidate shot fires with probability 67%
   0% -> every candidate shot fires

The shot itself only changes dark material; existing light/background pixels
inside the circle are left alone. The local background is the mean of the
substantially lighter 8-neighbors of the shot center.
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


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Grayscale Coarsener — Hole Shooting")
        self.root.geometry("1200x850")
        self.root.minsize(800, 600)

        self.image: Image.Image | None = None
        self.original_path: Path | None = None
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
        self.status = tk.StringVar(value="Open a PNG/BMP, then drag a rectangle.")

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
        ttk.Label(settings, text="(0–255 grayscale)").pack(side=tk.LEFT, padx=8)

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

    # ---------- image I/O ----------
    def open_image(self) -> None:
        filename = filedialog.askopenfilename(
            title="Open grayscale image",
            filetypes=[
                ("PNG files", "*.png"),
                ("BMP files", "*.bmp"),
                ("All images", "*.*"),
            ],
        )
        if not filename:
            return
        try:
            img = Image.open(filename).convert("L")
        except Exception as exc:
            messagebox.showerror("Open failed", str(exc))
            return

        self.image = img
        self.original_path = Path(filename)
        self.undo_stack.clear()
        self.clear_selection()
        self.status.set(
            f"Loaded {Path(filename).name} — {img.width}×{img.height}px, grayscale 8-bit"
        )
        self.refresh_canvas()

    def save_image(self) -> None:
        if self.image is None:
            messagebox.showinfo("Nothing to save", "Open an image first.")
            return

        initial = self.original_path.stem if self.original_path else "coarsened"
        filename = filedialog.asksaveasfilename(
            title="Save image",
            initialfile=initial,
            defaultextension=".png",
            filetypes=[("PNG files", "*.png"), ("BMP files", "*.bmp")],
        )
        if not filename:
            return

        try:
            self.image.save(filename)
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            return

        self.status.set(f"Saved {Path(filename).name}")

    # ---------- canvas mapping ----------
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

    # ---------- selection ----------
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

    # ---------- undo ----------
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

    # ---------- hole shooting ----------
    def _boundary_candidates(
        self,
        src: Image.Image,
        selection: Selection,
        dark_t: int,
        light_delta: int,
    ) -> list[tuple[int, int, int]]:
        """Return (x, y, local_background) for dark boundary pixels."""
        sp = src.load()
        candidates: list[tuple[int, int, int]] = []

        for y in range(selection.y0, selection.y1):
            for x in range(selection.x0, selection.x1):
                v = sp[x, y]
                if v > dark_t:
                    continue

                light_values: list[int] = []
                for ny in range(max(0, y - 1), min(src.height, y + 2)):
                    for nx in range(max(0, x - 1), min(src.width, x + 2)):
                        if nx == x and ny == y:
                            continue
                        nv = sp[nx, ny]
                        if nv >= v + light_delta:
                            light_values.append(nv)

                if light_values:
                    bg = round(sum(light_values) / len(light_values))
                    candidates.append((x, y, bg))

        return candidates

    def _space_shot_centers(
        self,
        candidates: list[tuple[int, int, int]],
        diameter: int,
    ) -> list[tuple[int, int, int]]:
        """Thin boundary candidates so large shots do not heavily overlap."""
        if not candidates:
            return []

        # Randomize the order so the retained pattern is not biased toward
        # the top-left corner of the image.
        random.shuffle(candidates)

        cell = max(1, diameter)
        min_distance_sq = float(diameter * diameter)
        grid: dict[tuple[int, int], list[tuple[int, int]]] = {}
        accepted: list[tuple[int, int, int]] = []

        for cx, cy, bg in candidates:
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
                accepted.append((cx, cy, bg))
                grid.setdefault((gx, gy), []).append((cx, cy))

        return accepted

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

        src = self.image
        dst = src.copy()
        sp = src.load()
        dp = dst.load()

        candidates = self._boundary_candidates(
            src, s, dark_t, light_delta
        )
        shot_centers = self._space_shot_centers(candidates, diameter)

        rng = random.Random()
        fired = 0
        changed = 0
        radius = (diameter - 1) / 2.0

        for cx, cy, bg in shot_centers:
            # "Black retention" means the probability that a possible shot
            # is NOT fired.
            if rng.random() >= 1.0 - keep:
                continue

            fired += 1

            xmin = max(s.x0, math.floor(cx - radius))
            xmax = min(s.x1 - 1, math.ceil(cx + radius))
            ymin = max(s.y0, math.floor(cy - radius))
            ymax = min(s.y1 - 1, math.ceil(cy + radius))

            for y in range(ymin, ymax + 1):
                for x in range(xmin, xmax + 1):
                    if (x - cx) ** 2 + (y - cy) ** 2 > radius * radius:
                        continue

                    # Only shoot dark material. Existing background inside
                    # the circle remains untouched.
                    if sp[x, y] <= dark_t and dp[x, y] != bg:
                        dp[x, y] = max(sp[x, y], min(255, bg))
                        changed += 1

        self.image = dst
        self.refresh_canvas()
        self.status.set(
            f"Fired {fired:,}/{len(shot_centers):,} shots, changed {changed:,} px — "
            f"{self.preset.get()}, shot Ø{diameter}px, dark≤{dark_t}, "
            f"light delta≥{light_delta}"
        )

    # ---------- blur brush ----------
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