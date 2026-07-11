import tkinter as tk
from tkinter import ttk, messagebox
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


class AnimatedOrbitalSimApp:
    """
    Hierarchical binary + S-type planet, restricted 3-body.

    Physics model:
      - Binary (Orange dwarf + White dwarf) is on Keplerian rails around the
        barycenter. a_wd is the RELATIVE semi-major axis of the pair; each
        star's barycentric ellipse is the relative orbit scaled by the
        opposite mass fraction.
      - Planet is a massless test particle integrated with leapfrog (KDK)
        in the barycentric inertial frame, pulled by both stars.
      - All physics runs in the barycentric frame ALWAYS. The view mode
        ("barycentric" / "orange") is a pure rendering transform: in orange
        mode every drawn coordinate has the Orange dwarf's instantaneous
        barycentric position subtracted. Nothing is re-integrated.

    Units: AU, years, solar masses -> G = 4*pi^2.
    """

    def __init__(self, root):
        self.root = root
        self.root.title("Animated Hierarchical Binary Orbital Simulator")
        self.root.geometry("1200x990+25+0")
        self.root.configure(bg="#0d1117")

        # Animation state
        self.is_running = True
        self.time_step = 0.0          # simulation time, years
        self.animation_id = None
        self.ff_in_progress = False

        # Fixed physics timestep (years). Planet period ~0.67 yr for the
        # defaults -> ~1300 steps per planet orbit. Warp changes how many
        # substeps run per frame, never the step size.
        self.dt = 0.0005

        # View mode: "barycentric" (default) or "orange" (Orange dwarf fixed)
        self.view_mode = "barycentric"

        # Dark theme
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure(".", background="#0d1117", foreground="white",
                             fieldbackground="#161b22")
        self.style.configure("TLabel", background="#0d1117",
                             foreground="#c9d1d9", font=("Arial", 10))
        self.style.configure("TButton", background="#21262d",
                             foreground="white", font=("Arial", 10, "bold"))
        self.style.map("TButton", background=[("active", "#30363d")])

        # Layout
        self.left_frame = ttk.Frame(root, padding=0, width=280)
        self.left_frame.pack(side=tk.LEFT, fill=tk.Y)
        self.left_frame.pack_propagate(False)

        self.right_frame = ttk.Frame(root, padding=1)
        self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.setup_inputs()
        self.setup_plot()

        self.update_parameters()
        self.animate_loop()

    # ------------------------------------------------------------------ UI

    def setup_inputs(self):
        title = ttk.Label(self.left_frame, text="System Parameters",
                          font=("Arial", 14, "bold"), foreground="#58a6ff")
        title.pack(anchor="w", pady=(5, 10))

        def create_input(label_text, default_val):
            ttk.Label(self.left_frame, text=label_text).pack(anchor="w")
            e = ttk.Entry(self.left_frame, width=25)
            e.insert(0, str(default_val))
            e.pack(fill=tk.X, pady=(0, 6))
            return e

        self.year_label = ttk.Label(
            self.left_frame,
            text="Simulation Years : 0",
            font=("Consolas", 11, "bold"),
            foreground="#58a6ff",
            justify=tk.LEFT
        )
        self.year_label.pack(fill=tk.X, pady=(0, 10))

        self.m_orange_entry = create_input("Orange Dwarf Mass (M☉):", 0.85)
        self.m_wd_entry = create_input("White Dwarf Mass (M☉):", 0.70)
        self.age_entry = create_input("White Dwarf Cooling Age (Gyr):", 0.1)
        self.a_wd_entry = create_input("White Dwarf Semi-Major Axis (AU):", 115)
        self.e_wd_entry = create_input("White Dwarf Eccentricity:", 0.875)
        self.i_wd_entry = create_input("White Dwarf Inclination:", 75)
        self.a_p_entry = create_input("Planet Semi-Major Axis (AU):", 0.725)

        self.btn_calc = ttk.Button(self.left_frame, text="Apply Changes",
                                   command=self.update_parameters)
        self.btn_calc.pack(fill=tk.X, pady=(8, 12))

        ttk.Label(self.left_frame, text="Calculated Metrics",
                  font=("Arial", 11, "bold"),
                  foreground="#58a6ff").pack(anchor="w")

        self.output_text = tk.Text(self.left_frame, height=12, bg="#161b22",
                                   fg="#c9d1d9", font=("Consolas", 10), bd=0)
        self.output_text.pack(fill=tk.BOTH, expand=True)

        self.zoom_factor = 0.15

    def setup_plot(self):
        self.control_frame = ttk.Frame(self.right_frame)
        self.control_frame.pack(fill=tk.X, padx=4, pady=4)

        self.row1 = ttk.Frame(self.control_frame)
        self.row1.pack(fill=tk.X)
        self.row2 = ttk.Frame(self.control_frame)
        self.row2.pack(fill=tk.X)

        # ---------- Row 1 ----------
        self.btn_toggle = ttk.Button(self.row1, text="Pause Simulation",
                                     command=self.toggle_animation)
        self.btn_toggle.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        ttk.Button(self.row1, text="Fast Forward",
                   command=self.fast_forward).pack(
            side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        ttk.Button(self.row1, text="Next Periastron",
                   command=self.next_periastron).pack(
            side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        self.btn_view = ttk.Button(self.row1, text="View: Barycentric",
                                   command=self.toggle_view)
        self.btn_view.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=2)

        # ---------- Row 2 ----------
        ttk.Button(self.row2, text="Zoom In",
                   command=lambda: self.change_zoom(0.8)).pack(
            side=tk.LEFT, padx=2)

        ttk.Button(self.row2, text="Zoom Out",
                   command=lambda: self.change_zoom(1.25)).pack(
            side=tk.LEFT, padx=2)

        ttk.Label(self.row2, text="Warp:").pack(side=tk.LEFT, padx=(10, 2))

        self.speed_slider = tk.Scale(self.row2, from_=1, to=20,
                                     orient=tk.HORIZONTAL, bg="#161b22",
                                     fg="white", highlightthickness=0,
                                     length=180)
        self.speed_slider.set(1)
        self.speed_slider.pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(self.row2, text="FF WD Orbits:").pack(
            side=tk.LEFT, padx=(5, 2))

        self.ff_years_entry = ttk.Entry(self.row2, width=8)
        self.ff_years_entry.insert(0, "0.25")
        self.ff_years_entry.pack(side=tk.LEFT)

        # ---------- Plot ----------
        self.fig = plt.figure(figsize=(8, 8), facecolor="#0d1117")
        self.ax = self.fig.add_subplot(111, projection="3d")
        self.ax.set_facecolor("#0d1117")

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.right_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def change_zoom(self, factor):
        self.zoom_factor *= factor
        self.update_axes_limits()
        self.canvas.draw_idle()

    def update_axes_limits(self):
        max_range = self.a_wd * (1 + self.e_wd) * self.zoom_factor
        self.ax.set_xlim(-max_range, max_range)
        self.ax.set_ylim(-max_range, max_range)
        self.ax.set_zlim(-max_range, max_range)

    # ------------------------------------------------------ Core physics

    def solve_kepler(self, M, e, tol=1e-12, max_iter=30):
        """Newton-Raphson on Kepler's equation. Starting guess E = M + e*sin(M)
        keeps Newton well-behaved even at e = 0.875 near periastron, where a
        plain E0 = M start converges slowly or overshoots."""
        M = np.mod(M, 2.0 * np.pi)
        E = M + e * np.sin(M)
        for _ in range(max_iter):
            dE = (E - e * np.sin(E) - M) / (1.0 - e * np.cos(E))
            E -= dE
            if abs(dE) < tol:
                break
        return E

    def binary_positions(self, time_years):
        """Barycentric positions of both stars at time t (years).
        Relative orbit solved in its own plane, inclined by rotation about
        the x axis, then split by mass fractions:
            r_orange = -(m_wd / M_tot) * r_rel
            r_wd     = +(m_orange / M_tot) * r_rel
        t = 0 is periastron (M = 0)."""
        M = 2.0 * np.pi * time_years / self.period_wd_yr
        E = self.solve_kepler(M, self.e_wd)

        x_rel = self.a_wd * (np.cos(E) - self.e_wd)
        y_rel = self.a_wd * np.sqrt(1.0 - self.e_wd ** 2) * np.sin(E)

        x3 = x_rel
        y3 = y_rel * np.cos(self.i_wd_rad)
        z3 = y_rel * np.sin(self.i_wd_rad)

        f_orange = self.m_wd / (self.m_orange + self.m_wd)
        f_wd = self.m_orange / (self.m_orange + self.m_wd)

        return (-f_orange * x3, -f_orange * y3, -f_orange * z3,
                f_wd * x3, f_wd * y3, f_wd * z3)

    def binary_velocity(self, time_years, body="orange"):
        """Barycentric velocity by central finite difference (error O(h^2);
        the old forward difference was O(h))."""
        h = 1e-4
        p1 = self.binary_positions(time_years - h)
        p2 = self.binary_positions(time_years + h)
        i = 0 if body == "orange" else 3
        return ((p2[i] - p1[i]) / (2 * h),
                (p2[i + 1] - p1[i + 1]) / (2 * h),
                (p2[i + 2] - p1[i + 2]) / (2 * h))

    def planet_acceleration(self, px, py, pz, stars):
        G = 4.0 * np.pi ** 2
        x_o, y_o, z_o, x_w, y_w, z_w = stars

        dx1, dy1, dz1 = px - x_o, py - y_o, pz - z_o
        r1 = np.sqrt(dx1 ** 2 + dy1 ** 2 + dz1 ** 2)

        dx2, dy2, dz2 = px - x_w, py - y_w, pz - z_w
        r2 = np.sqrt(dx2 ** 2 + dy2 ** 2 + dz2 ** 2)

        ax = -G * self.m_orange * dx1 / r1 ** 3 - G * self.m_wd * dx2 / r2 ** 3
        ay = -G * self.m_orange * dy1 / r1 ** 3 - G * self.m_wd * dy2 / r2 ** 3
        az = -G * self.m_orange * dz1 / r1 ** 3 - G * self.m_wd * dz2 / r2 ** 3
        return ax, ay, az

    def integrate_planet_step(self, t, dt):
        """One leapfrog KDK step from t to t+dt.
        First kick uses star positions at t, second kick uses star positions
        at t+dt. The old version used the same star snapshot for both kicks,
        which silently degrades the method to first order in the binary's
        motion."""
        stars0 = self.binary_positions(t)
        ax, ay, az = self.planet_acceleration(self.px, self.py, self.pz, stars0)

        self.vx += 0.5 * ax * dt
        self.vy += 0.5 * ay * dt
        self.vz += 0.5 * az * dt

        self.px += self.vx * dt
        self.py += self.vy * dt
        self.pz += self.vz * dt

        stars1 = self.binary_positions(t + dt)
        ax, ay, az = self.planet_acceleration(self.px, self.py, self.pz, stars1)

        self.vx += 0.5 * ax * dt
        self.vy += 0.5 * ay * dt
        self.vz += 0.5 * az * dt

    def advance(self, span_years):
        """Advance the simulation by span_years using the fixed physics dt.
        Warp/fast-forward only change how much time this covers, never the
        step size, so accuracy is warp-independent."""
        n = max(1, int(round(span_years / self.dt)))
        h = span_years / n
        for _ in range(n):
            self.integrate_planet_step(self.time_step, h)
            self.time_step += h

    # ------------------------------------------------------ Time controls

    def fast_forward(self):
        if self.ff_in_progress:
            return
        try:
            fraction = float(self.ff_years_entry.get())
        except ValueError:
            messagebox.showerror("Input Error", "FF WD Orbits must be a number")
            return
        self.ff_remaining = fraction * self.period_wd_yr
        self.ff_in_progress = True
        self.ff_was_running = self.is_running
        # Pause the animation so frames don't double-advance during FF
        if self.is_running:
            self.is_running = False
            if self.animation_id:
                self.root.after_cancel(self.animation_id)
        self.fast_forward_step()

    def fast_forward_step(self):
        chunk = min(2000 * self.dt, self.ff_remaining)  # ~1 yr per UI tick
        self.advance(chunk)
        self.ff_remaining -= chunk
        if self.ff_remaining > 1e-9:
            self.root.after(1, self.fast_forward_step)
        else:
            self.ff_in_progress = False
            self.render_frame()
            if self.ff_was_running:
                self.is_running = True
                self.btn_toggle.config(text="Pause Simulation")
                self.animate_loop()

    def next_periastron(self):
        """Integrate the planet forward to the binary's next periastron
        (t = 0 mod P is periastron). The old version teleported the clock
        without moving the planet, which desynchronized the planet's phase
        from the binary."""
        if self.ff_in_progress:
            return
        remaining = self.period_wd_yr - np.mod(self.time_step,
                                               self.period_wd_yr)
        self.ff_remaining = remaining
        self.ff_in_progress = True
        self.ff_was_running = self.is_running
        if self.is_running:
            self.is_running = False
            if self.animation_id:
                self.root.after_cancel(self.animation_id)
        self.fast_forward_step()

    def toggle_animation(self):
        if self.ff_in_progress:
            return
        self.is_running = not self.is_running
        if self.is_running:
            self.btn_toggle.config(text="Pause Simulation")
            self.animate_loop()
        else:
            self.btn_toggle.config(text="Play Simulation")
            if self.animation_id:
                self.root.after_cancel(self.animation_id)

    # ------------------------------------------------------ View modes

    def toggle_view(self):
        """Switch rendering frame. Pure coordinate transform at draw time:
        simulation state, time, and trails are untouched."""
        if self.view_mode == "barycentric":
            self.view_mode = "orange"
            self.btn_view.config(text="View: Orange Fixed")
        else:
            self.view_mode = "barycentric"
            self.btn_view.config(text="View: Barycentric")
        self.force_plot_redraw()
        self.render_frame()

    def frame_offset(self, stars):
        """Coordinates to subtract from every rendered point."""
        if self.view_mode == "orange":
            return stars[0], stars[1], stars[2]
        return 0.0, 0.0, 0.0

    # ------------------------------------------------------ Parameters

    def update_parameters(self):
        try:
            self.m_orange = float(self.m_orange_entry.get())
            self.m_wd = float(self.m_wd_entry.get())
            age_gyr = float(self.age_entry.get())
            self.a_wd = float(self.a_wd_entry.get())
            self.e_wd = float(self.e_wd_entry.get())
            self.i_wd_deg = float(self.i_wd_entry.get())
            self.a_p = float(self.a_p_entry.get())

            if self.e_wd < 0 or self.e_wd >= 1:
                raise ValueError("Eccentricity must be between 0 and 0.99")
            if age_gyr <= 0:
                raise ValueError("Cooling age must be positive")

            self.i_wd_rad = np.radians(self.i_wd_deg)

            # ---- FULL time reset ----
            self.time_step = 0.0
            self.ff_in_progress = False

            # Stellar properties
            L_orange = self.m_orange ** 4
            # Mestel cooling: L ~ M * t^(-7/5). (Previous version had the
            # mass dependence inverted: M^-1.)
            L_wd = 1e-3 * self.m_wd * age_gyr ** -1.4

            r_peri_wd = self.a_wd * (1 - self.e_wd)
            r_apa_wd = self.a_wd * (1 + self.e_wd)

            self.period_p_yr = np.sqrt(self.a_p ** 3 / self.m_orange)
            self.period_wd_yr = np.sqrt(
                self.a_wd ** 3 / (self.m_orange + self.m_wd))

            # Holman & Wiegert (1999) S-type critical semi-major axis.
            # mu is the COMPANION mass fraction: the planet orbits the
            # Orange dwarf, so mu = m_wd / (m_orange + m_wd).
            # (Previous version used the primary's fraction.)
            mu = self.m_wd / (self.m_orange + self.m_wd)
            a_crit = self.a_wd * (
                0.464
                - 0.380 * mu
                - 0.631 * self.e_wd
                + 0.586 * mu * self.e_wd
                + 0.150 * self.e_wd ** 2
                - 0.198 * mu * self.e_wd ** 2
            )
            stability_status = "STABLE" if self.a_p < a_crit else "UNSTABLE!"

            kozai_term = 1 - (5 / 3) * np.cos(self.i_wd_rad) ** 2
            e_max_kozai = np.sqrt(kozai_term) if kozai_term > 0 else 0

            self.output_text.delete("1.0", tk.END)
            self.output_text.insert(tk.END, (
                f"Orange L☉  : {L_orange:.4f}\n"
                f"WD L☉      : {L_wd:.4f}\n"
                f"Planet Year: {self.period_p_yr * 365.25:.1f} Days\n"
                f"Binary Year: {self.period_wd_yr:.1f} Years\n"
                f"WD Closest : {r_peri_wd:.2f} AU\n"
                f"WD Farthest: {r_apa_wd:.2f} AU\n"
                f"Stability  : {stability_status}\n"
                f"(Limit: {a_crit:.2f} AU)\n"
                f"Max Kozai e: {e_max_kozai:.3f}"
            ))

            # ---- Static orbit tracks (one binary period) ----
            times = np.linspace(0, self.period_wd_yr, 2000)
            tr = np.array([self.binary_positions(t) for t in times])
            self.track_orange = tr[:, 0:3]           # barycentric, orange
            self.track_wd = tr[:, 3:6]               # barycentric, WD
            self.track_rel = tr[:, 3:6] - tr[:, 0:3]  # WD relative to orange

            # ---- Planet initialization (t = 0) ----
            stars0 = self.binary_positions(0.0)
            G = 4.0 * np.pi ** 2
            self.px = stars0[0] + self.a_p
            self.py = stars0[1]
            self.pz = stars0[2]

            v_circ = np.sqrt(G * self.m_orange / self.a_p)
            vx_o, vy_o, vz_o = self.binary_velocity(0.0, "orange")
            self.vx = vx_o
            self.vy = vy_o + v_circ
            self.vz = vz_o

            # ---- Reset ALL trails and the clock display ----
            self.planet_history = []
            self.orange_history = []
            self.wd_history = []
            self.year_label.config(text="Simulation Years : 0")

            self.force_plot_redraw()
            self.render_frame()

        except ValueError as e:
            messagebox.showerror("Input Error",
                                 f"Invalid parameters entered:\n{e}")

    # ------------------------------------------------------ Rendering

    def force_plot_redraw(self):
        """Rebuild static plot elements for the current view mode."""
        self.ax.clear()

        self.ax.xaxis.label.set_color('#8b949e')
        self.ax.yaxis.label.set_color('#8b949e')
        self.ax.zaxis.label.set_color('#8b949e')
        self.ax.tick_params(colors='#8b949e')
        self.update_axes_limits()

        if self.view_mode == "barycentric":
            # Barycenter is a fixed point here
            self.ax.scatter(0, 0, 0, color="yellow", marker="+", s=350,
                            linewidths=3, label="Barycenter")
            self.ax.plot(self.track_orange[:, 0], self.track_orange[:, 1],
                         self.track_orange[:, 2], color="#f97316",
                         linestyle=":", linewidth=1.5,
                         label="Orange Dwarf Orbit")
            self.ax.plot(self.track_wd[:, 0], self.track_wd[:, 1],
                         self.track_wd[:, 2], color="white", linestyle=":",
                         linewidth=1.5, label="White Dwarf Orbit")
        else:
            # Orange fixed at origin; WD relative orbit is a closed static
            # ellipse; barycenter now moves, drawn as a dynamic marker below
            self.ax.plot(self.track_rel[:, 0], self.track_rel[:, 1],
                         self.track_rel[:, 2], color="white", linestyle=":",
                         linewidth=1.5, label="WD Orbit (rel. to Orange)")

        self.ax.set_xlabel("X (AU)")
        self.ax.set_ylabel("Y (AU)")
        self.ax.set_zlabel("Z (AU)")
        self.ax.view_init(elev=25, azim=40)

        # Dynamic objects
        self.bary_dot, = self.ax.plot([], [], [], '+', color='yellow',
                                      markersize=14, markeredgewidth=2)
        self.orange_dot, = self.ax.plot([], [], [], 'o', color='#f97316',
                                        markersize=10, label='Orange Dwarf')
        self.wd_dot, = self.ax.plot([], [], [], 'o', color='white',
                                    markersize=8, markeredgecolor='#58a6ff',
                                    label='White Dwarf')
        self.planet_dot, = self.ax.plot([], [], [], 'o', color='#58a6ff',
                                        markersize=6, label='Planet')

        self.planet_trail, = self.ax.plot([], [], [], color='#58a6ff',
                                          linewidth=1.2, alpha=0.7)
        self.orange_trail, = self.ax.plot([], [], [], color='#f97316',
                                          linewidth=1.0, alpha=0.6)
        self.wd_trail, = self.ax.plot([], [], [], color='white',
                                      linewidth=1.0, alpha=0.6)

        self.ax.legend(facecolor="#161b22", edgecolor="none",
                       labelcolor="white", loc="upper left")
        self.canvas.draw_idle()

    def record_history(self, stars):
        """Append synchronized samples for all three bodies (same frame, same
        index) so trails can be re-based into any view frame later."""
        self.planet_history.append((self.px, self.py, self.pz))
        self.orange_history.append(stars[0:3])
        self.wd_history.append(stars[3:6])

        max_history = 2000
        if len(self.planet_history) > max_history:
            self.planet_history.pop(0)
            self.orange_history.pop(0)
            self.wd_history.pop(0)

    def render_frame(self):
        """Draw current state in the active view frame."""
        stars = self.binary_positions(self.time_step)
        ox, oy, oz = self.frame_offset(stars)

        self.bary_dot.set_data_3d([-ox], [-oy], [-oz])
        self.orange_dot.set_data_3d([stars[0] - ox], [stars[1] - oy],
                                    [stars[2] - oz])
        self.wd_dot.set_data_3d([stars[3] - ox], [stars[4] - oy],
                                [stars[5] - oz])
        self.planet_dot.set_data_3d([self.px - ox], [self.py - oy],
                                    [self.pz - oz])

        if self.planet_history:
            p = np.array(self.planet_history)
            o = np.array(self.orange_history)
            w = np.array(self.wd_history)

            if self.view_mode == "orange":
                # Re-base every stored sample onto the orange dwarf's
                # position AT THAT SAMPLE'S TIME - this is what makes the
                # trail correct in the rotating-origin frame.
                p = p - o
                w = w - o
                o = o - o  # orange trail collapses to the origin

            self.planet_trail.set_data_3d(p[:, 0], p[:, 1], p[:, 2])
            self.orange_trail.set_data_3d(o[:, 0], o[:, 1], o[:, 2])
            self.wd_trail.set_data_3d(w[:, 0], w[:, 1], w[:, 2])

        self.canvas.draw_idle()

    # ------------------------------------------------------ Animation

    def animate_loop(self):
        if not self.is_running:
            return

        span = self.speed_slider.get() * 0.03  # years per frame
        self.advance(span)

        stars = self.binary_positions(self.time_step)
        self.record_history(stars)

        # Stats
        rx = self.px - stars[0]
        ry = self.py - stars[1]
        rz = self.pz - stars[2]
        r_planet = np.sqrt(rx ** 2 + ry ** 2 + rz ** 2)

        self.year_label.config(text=(
            f"Simulation Years : {self.time_step:.1f}\n"
            f"Planet Orbits    : {self.time_step / self.period_p_yr:.2f}\n"
            f"WD Orbits        : {self.time_step / self.period_wd_yr:.4f}\n"
            f"Planet Radius    : {r_planet:.3f} AU\n"
            f"Warp             : {self.speed_slider.get()}\n"
            f"View             : {self.view_mode}"
        ))

        self.render_frame()
        self.animation_id = self.root.after(100, self.animate_loop)


if __name__ == "__main__":
    root = tk.Tk()
    app = AnimatedOrbitalSimApp(root)
    root.mainloop()
