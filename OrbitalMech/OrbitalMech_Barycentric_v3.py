import tkinter as tk
from tkinter import ttk, messagebox
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


# ---------------------------------------------------------------- Constants
# Units everywhere: AU, years, solar masses -> G = 4*pi^2.

G_SIM = 4.0 * np.pi ** 2

M_MOON_MSUN = 3.69e-8        # lunar mass in M(sun)
D_MOON_AU = 0.002570         # Earth-Moon distance in AU
R_SUN_AU = 0.00465           # solar radius in AU
T_SUN = 5772.0               # solar effective temperature, K

# 1 (M_sun * AU^2 / yr^3) expressed in solar luminosities
LUM_UNIT_LSUN = 3702.0

# Host stellar wind assumptions (solar-calibrated; K dwarfs are typically
# windier when young, so treat these as a quiet lower bound)
MDOT_WIND = 2.0e-14          # host wind mass loss, M(sun)/yr
V_WIND_AU_YR = 84.2          # wind speed ~400 km/s in AU/yr

# Lunar tidal acceleration gradient on Earth, in sim units (2*G*m/d^3).
# Sanity anchor: the Sun's tide on Earth computes to 0.46 of this, the
# textbook value.
TIDE_MOON = 2.0 * G_SIM * M_MOON_MSUN / D_MOON_AU ** 3


def planck_band_fraction(T, lam1=100e-9, lam2=400e-9, n=400):
    """Fraction of a blackbody's total output emitted between lam1 and lam2
    (default: 100-400 nm, the UV band). Numerical integral of the Planck
    function normalized by sigma*T^4."""
    h = 6.626e-34
    c = 2.998e8
    kB = 1.381e-23
    sigma = 5.670e-8
    lam = np.linspace(lam1, lam2, n)
    B = (2 * np.pi * h * c ** 2 / lam ** 5
         / (np.exp(h * c / (lam * kB * T)) - 1.0))
    return np.trapz(B, lam) / (sigma * T ** 4)


# UV output of the Sun per unit luminosity, the normalization for
# "Earth UV units" (UV flux at Earth = 1 by construction)
F_UV_SUN = planck_band_fraction(T_SUN)


class AnimatedOrbitalSimApp:
    """
    Hierarchical binary + S-type planet, restricted 3-body.

    Physics model:
      - Binary (Orange dwarf + White dwarf) on Keplerian rails around the
        barycenter; a_wd is the RELATIVE semi-major axis of the pair.
      - Planet is a massless test particle, leapfrog (KDK) in the
        barycentric inertial frame, pulled by both stars.
      - View mode ("barycentric" / "orange") is a pure rendering transform.

    v3 planet environment block (strictly physical, fixed Earth-like planet:
    1 R_earth, Earth-strength magnetosphere, albedo 0.3):

      TIDES  - tidal acceleration gradient 2*G*m/d^3 from each star, in
               units of the Moon's tide on Earth. Host ~1 lunar tide at
               0.725 AU; the WD at 14 AU periastron contributes ~1e-4.
      UV     - blackbody band flux 100-400 nm at the planet, in Earth UV
               units. Host T_eff from the main-sequence relation
               T = 5772*M^0.505; WD T_eff from its cooling luminosity and
               mass-radius relation R = 0.0127*(M/0.6)^(-1/3) R_sun. A
               0.1 Gyr WD runs ~20,000 K, so per watt it is strongly
               UV-weighted; distance decides whether that matters.
      MAG    - magnetopause standoff distance from host wind ram pressure
               (P ~ 1/r^2, standoff ~ P^(-1/6), Earth = 10 R_E at 1 AU),
               classified QUIET/ELEVATED/ACTIVE/SEVERE. The WD's
               Bondi-Hoyle accretion of the host wind is computed honestly
               and shown as an X-ray luminosity - at 14 AU it is ~1e-13
               L_sun, i.e. negligible, and the readout says so.
      CLIMATE- bolometric instellation S from both stars in Earth units,
               equilibrium temperature T_eq = 278.5*(S*(1-A))^0.25 K, and a
               phase bin: RUNAWAY >= 1.06 / HOT >= 0.9 / TEMPERATE >= 0.42
               / COLD >= 0.32 / SNOWBALL below (Kopparapu-style limits for
               a Sun-like spectrum; K-dwarf limits shift a few percent).
               Also shows the orbit-averaged S, which scales as
               1/sqrt(1-e^2) and therefore creeps up as Kozai-Lidov pumps
               the planet's eccentricity.
    """

    def __init__(self, root):
        self.root = root
        self.root.title("Animated Hierarchical Binary Orbital Simulator")
        self.root.geometry("1200x990+25+0")
        self.root.configure(bg="#0d1117")

        self.is_running = True
        self.time_step = 0.0          # simulation time, years
        self.animation_id = None
        self.ff_in_progress = False

        # Fixed physics timestep (years); warp changes substep count only
        self.dt = 0.0005

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

        self.left_frame = ttk.Frame(root, padding=0, width=300)
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
        title.pack(anchor="w", pady=(5, 6))

        def create_input(label_text, default_val):
            ttk.Label(self.left_frame, text=label_text).pack(anchor="w")
            e = ttk.Entry(self.left_frame, width=25)
            e.insert(0, str(default_val))
            e.pack(fill=tk.X, pady=(0, 4))
            return e

        self.year_label = ttk.Label(
            self.left_frame,
            text="Simulation Years : 0",
            font=("Consolas", 9, "bold"),
            foreground="#58a6ff",
            justify=tk.LEFT
        )
        self.year_label.pack(fill=tk.X, pady=(0, 6))

        self.m_orange_entry = create_input("Orange Dwarf Mass (M☉):", 0.85)
        self.m_wd_entry = create_input("White Dwarf Mass (M☉):", 0.70)
        self.age_entry = create_input("White Dwarf Cooling Age (Gyr):", 0.1)
        self.a_wd_entry = create_input("White Dwarf Semi-Major Axis (AU):", 115)
        self.e_wd_entry = create_input("White Dwarf Eccentricity:", 0.875)
        self.i_wd_entry = create_input("White Dwarf Inclination:", 75)
        self.a_p_entry = create_input("Planet Semi-Major Axis (AU):", 0.725)

        self.btn_calc = ttk.Button(self.left_frame, text="Apply Changes",
                                   command=self.update_parameters)
        self.btn_calc.pack(fill=tk.X, pady=(6, 6))

        ttk.Label(self.left_frame, text="Planet Environment",
                  font=("Arial", 11, "bold"),
                  foreground="#58a6ff").pack(anchor="w")

        self.env_text = tk.Text(self.left_frame, height=13, bg="#161b22",
                                fg="#c9d1d9", font=("Consolas", 9), bd=0)
        self.env_text.pack(fill=tk.X, pady=(0, 6))
        # Status color tags
        self.env_text.tag_configure("quiet", foreground="#3fb950")
        self.env_text.tag_configure("elevated", foreground="#d29922")
        self.env_text.tag_configure("active", foreground="#f97316")
        self.env_text.tag_configure("severe", foreground="#f85149")

        ttk.Label(self.left_frame, text="Calculated Metrics",
                  font=("Arial", 11, "bold"),
                  foreground="#58a6ff").pack(anchor="w")

        self.output_text = tk.Text(self.left_frame, height=11, bg="#161b22",
                                   fg="#c9d1d9", font=("Consolas", 9), bd=0)
        self.output_text.pack(fill=tk.BOTH, expand=True)

        self.zoom_factor = 0.15

    def setup_plot(self):
        self.control_frame = ttk.Frame(self.right_frame)
        self.control_frame.pack(fill=tk.X, padx=4, pady=4)

        self.row1 = ttk.Frame(self.control_frame)
        self.row1.pack(fill=tk.X)
        self.row2 = ttk.Frame(self.control_frame)
        self.row2.pack(fill=tk.X)

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
        """Newton-Raphson on Kepler's equation, guess E = M + e*sin(M)."""
        M = np.mod(M, 2.0 * np.pi)
        E = M + e * np.sin(M)
        for _ in range(max_iter):
            dE = (E - e * np.sin(E) - M) / (1.0 - e * np.cos(E))
            E -= dE
            if abs(dE) < tol:
                break
        return E

    def binary_positions(self, time_years):
        """Barycentric positions of both stars; t = 0 is periastron."""
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
        """Barycentric velocity, central finite difference O(h^2)."""
        h = 1e-4
        p1 = self.binary_positions(time_years - h)
        p2 = self.binary_positions(time_years + h)
        i = 0 if body == "orange" else 3
        return ((p2[i] - p1[i]) / (2 * h),
                (p2[i + 1] - p1[i + 1]) / (2 * h),
                (p2[i + 2] - p1[i + 2]) / (2 * h))

    def planet_acceleration(self, px, py, pz, stars):
        x_o, y_o, z_o, x_w, y_w, z_w = stars

        dx1, dy1, dz1 = px - x_o, py - y_o, pz - z_o
        r1 = np.sqrt(dx1 ** 2 + dy1 ** 2 + dz1 ** 2)

        dx2, dy2, dz2 = px - x_w, py - y_w, pz - z_w
        r2 = np.sqrt(dx2 ** 2 + dy2 ** 2 + dz2 ** 2)

        ax = (-G_SIM * self.m_orange * dx1 / r1 ** 3
              - G_SIM * self.m_wd * dx2 / r2 ** 3)
        ay = (-G_SIM * self.m_orange * dy1 / r1 ** 3
              - G_SIM * self.m_wd * dy2 / r2 ** 3)
        az = (-G_SIM * self.m_orange * dz1 / r1 ** 3
              - G_SIM * self.m_wd * dz2 / r2 ** 3)
        return ax, ay, az

    def integrate_planet_step(self, t, dt):
        """Leapfrog KDK; kicks use star positions at t and t+dt."""
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
        """Advance by span_years at fixed dt; warp never changes step size."""
        n = max(1, int(round(span_years / self.dt)))
        h = span_years / n
        for _ in range(n):
            self.integrate_planet_step(self.time_step, h)
            self.time_step += h

    def osculating_elements(self):
        """Planet's instantaneous Keplerian elements relative to the Orange
        dwarf; constant for two bodies, so drift here = WD perturbation."""
        stars = self.binary_positions(self.time_step)
        vo = self.binary_velocity(self.time_step, "orange")

        r = np.array([self.px - stars[0], self.py - stars[1],
                      self.pz - stars[2]])
        v = np.array([self.vx - vo[0], self.vy - vo[1], self.vz - vo[2]])

        mu = G_SIM * self.m_orange
        rn = np.linalg.norm(r)
        energy = 0.5 * np.dot(v, v) - mu / rn
        a_osc = -mu / (2.0 * energy) if energy < 0 else float("inf")

        h = np.cross(r, v)
        e_vec = np.cross(v, h) / mu - r / rn
        e_osc = np.linalg.norm(e_vec)
        i_osc = np.degrees(np.arccos(np.clip(h[2] / np.linalg.norm(h),
                                             -1.0, 1.0)))

        sep = np.sqrt((stars[3] - stars[0]) ** 2 +
                      (stars[4] - stars[1]) ** 2 +
                      (stars[5] - stars[2]) ** 2)
        return a_osc, e_osc, i_osc, rn, sep

    # ------------------------------------------------- Planet environment

    def compute_environment(self):
        """All four v3 indicators, strictly physical, per current state."""
        stars = self.binary_positions(self.time_step)

        # Distances: planet to host, planet to WD, star-star separation
        r_o = np.sqrt((self.px - stars[0]) ** 2 + (self.py - stars[1]) ** 2 +
                      (self.pz - stars[2]) ** 2)
        r_w = np.sqrt((self.px - stars[3]) ** 2 + (self.py - stars[4]) ** 2 +
                      (self.pz - stars[5]) ** 2)
        sep = np.sqrt((stars[3] - stars[0]) ** 2 +
                      (stars[4] - stars[1]) ** 2 +
                      (stars[5] - stars[2]) ** 2)

        # ---- 1. Tidal forcing (units: lunar tide on Earth) ----
        tide_host = 2.0 * G_SIM * self.m_orange / r_o ** 3 / TIDE_MOON
        tide_wd = 2.0 * G_SIM * self.m_wd / r_w ** 3 / TIDE_MOON

        # ---- 2. UV flux (Earth UV units; band 100-400 nm) ----
        # Precomputed at Apply: self.uv_lum_host / self.uv_lum_wd are each
        # star's UV output relative to the Sun's UV output.
        uv_host = self.uv_lum_host / r_o ** 2
        uv_wd = self.uv_lum_wd / r_w ** 2
        uv_total = uv_host + uv_wd
        uv_wd_share = uv_wd / uv_total * 100 if uv_total > 0 else 0

        # ---- 3. Magnetic storm indicator ----
        # Host wind ram pressure scales as 1/r^2 (Earth value at 1 AU for a
        # solar-strength wind). Magnetopause standoff ~ P^(-1/6), Earth
        # standoff = 10 R_E.
        p_wind = (1.0 / r_o) ** 2
        standoff = 10.0 * p_wind ** (-1.0 / 6.0)
        if standoff > 9.0:
            mag_status, mag_tag = "QUIET", "quiet"
        elif standoff > 7.0:
            mag_status, mag_tag = "ELEVATED", "elevated"
        elif standoff > 5.0:
            mag_status, mag_tag = "ACTIVE", "active"
        else:
            mag_status, mag_tag = "SEVERE", "severe"

        # WD Bondi-Hoyle accretion of the host wind -> X-ray luminosity.
        # Captured fraction = (G*M_wd / (sep * v_rel^2))^2 of the wind;
        # v_rel^2 = wind speed^2 + binary orbital speed^2 (vis-viva).
        v_orb2 = G_SIM * (self.m_orange + self.m_wd) * (2.0 / sep
                                                        - 1.0 / self.a_wd)
        v_rel2 = V_WIND_AU_YR ** 2 + v_orb2
        f_capture = (G_SIM * self.m_wd / (sep * v_rel2)) ** 2
        mdot_acc = MDOT_WIND * f_capture
        l_acc = (G_SIM * self.m_wd * mdot_acc
                 / (self.r_wd_au) * LUM_UNIT_LSUN)   # in L_sun

        # ---- 4. Climate phase (bolometric instellation, Earth units) ----
        s_now = self.L_orange / r_o ** 2 + self.L_wd / r_w ** 2
        a_osc, e_osc, _, _, _ = self.osculating_elements()
        e_c = min(e_osc, 0.99)
        s_avg = (self.L_orange / (a_osc ** 2 * np.sqrt(1.0 - e_c ** 2))
                 if np.isfinite(a_osc) else s_now)
        t_eq = 278.5 * (s_now * 0.7) ** 0.25    # albedo 0.3

        if s_now >= 1.06:
            cli_status, cli_tag = "RUNAWAY", "severe"
        elif s_now >= 0.90:
            cli_status, cli_tag = "HOT", "active"
        elif s_now >= 0.42:
            cli_status, cli_tag = "TEMPERATE", "quiet"
        elif s_now >= 0.32:
            cli_status, cli_tag = "COLD", "elevated"
        else:
            cli_status, cli_tag = "SNOWBALL", "severe"

        return {
            "tide_host": tide_host, "tide_wd": tide_wd,
            "uv_total": uv_total, "uv_wd_share": uv_wd_share,
            "standoff": standoff, "mag_status": mag_status,
            "mag_tag": mag_tag, "l_acc": l_acc,
            "s_now": s_now, "s_avg": s_avg, "t_eq": t_eq,
            "cli_status": cli_status, "cli_tag": cli_tag,
        }

    def update_env_display(self):
        env = self.compute_environment()
        self.env_text.delete("1.0", tk.END)
        self.env_text.insert(tk.END, (
            f"Tide (host): {env['tide_host']:.3f} lunar\n"
            f"Tide (WD)  : {env['tide_wd']:.2e} lunar\n"
            f"UV flux    : {env['uv_total']:.3f} x Earth\n"
            f"  WD share : {env['uv_wd_share']:.2f} %\n"
            f"Magnetopause: {env['standoff']:.1f} R⊕\n"
            f"Storm level: "))
        self.env_text.insert(tk.END, env["mag_status"], env["mag_tag"])
        self.env_text.insert(tk.END, (
            f"\nWD accr. Lx: {env['l_acc']:.2e} L☉\n"
            f"Instellation: {env['s_now']:.4f} S⊕\n"
            f"  orbit avg : {env['s_avg']:.4f} S⊕\n"
            f"T_eq (A=0.3): {env['t_eq']:.1f} K\n"
            f"Climate    : "))
        self.env_text.insert(tk.END, env["cli_status"], env["cli_tag"])

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
        if self.is_running:
            self.is_running = False
            if self.animation_id:
                self.root.after_cancel(self.animation_id)
        self.fast_forward_step()

    def fast_forward_step(self):
        chunk = min(2000 * self.dt, self.ff_remaining)
        self.advance(chunk)
        self.ff_remaining -= chunk
        if self.ff_remaining > 1e-9:
            self.root.after(1, self.fast_forward_step)
        else:
            self.ff_in_progress = False
            self.update_stats_label()
            self.update_env_display()
            self.render_frame()
            if self.ff_was_running:
                self.is_running = True
                self.btn_toggle.config(text="Pause Simulation")
                self.animate_loop()

    def next_periastron(self):
        """Integrate forward to the binary's next periastron (t = 0 mod P)."""
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
        """Pure rendering transform; simulation state untouched."""
        if self.view_mode == "barycentric":
            self.view_mode = "orange"
            self.btn_view.config(text="View: Orange Fixed")
        else:
            self.view_mode = "barycentric"
            self.btn_view.config(text="View: Barycentric")
        self.force_plot_redraw()
        self.render_frame()

    def frame_offset(self, stars):
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

            # ---- Stellar properties ----
            self.L_orange = self.m_orange ** 4
            # Mestel cooling: L ~ M * t^(-7/5)
            self.L_wd = 1e-3 * self.m_wd * age_gyr ** -1.4

            # Host effective temperature, main-sequence relation
            self.T_orange = T_SUN * self.m_orange ** 0.505

            # WD radius (mass-radius relation) and effective temperature
            self.r_wd_rsun = 0.0127 * (self.m_wd / 0.6) ** (-1.0 / 3.0)
            self.r_wd_au = self.r_wd_rsun * R_SUN_AU
            self.T_wd = T_SUN * (self.L_wd / self.r_wd_rsun ** 2) ** 0.25

            # UV luminosities relative to the Sun's UV output
            self.uv_lum_host = (planck_band_fraction(self.T_orange)
                                / F_UV_SUN * self.L_orange)
            self.uv_lum_wd = (planck_band_fraction(self.T_wd)
                              / F_UV_SUN * self.L_wd)

            r_peri_wd = self.a_wd * (1 - self.e_wd)
            r_apa_wd = self.a_wd * (1 + self.e_wd)

            self.period_p_yr = np.sqrt(self.a_p ** 3 / self.m_orange)
            self.period_wd_yr = np.sqrt(
                self.a_wd ** 3 / (self.m_orange + self.m_wd))

            # Holman & Wiegert (1999); mu = companion mass fraction
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

            t_kozai = (2.0 / (3.0 * np.pi)
                       * self.period_wd_yr ** 2 / self.period_p_yr
                       * (self.m_orange + self.m_wd) / self.m_wd
                       * (1 - self.e_wd ** 2) ** 1.5)

            tidal_param = (2.0 * self.m_wd / self.m_orange
                           * (self.a_p / r_peri_wd) ** 3)

            self.output_text.delete("1.0", tk.END)
            self.output_text.insert(tk.END, (
                f"Orange L☉ : {self.L_orange:.4f}  "
                f"T:{self.T_orange:.0f}K\n"
                f"WD L☉     : {self.L_wd:.4f}  "
                f"T:{self.T_wd:.0f}K\n"
                f"Planet Year: {self.period_p_yr * 365.25:.1f} Days\n"
                f"Binary Year: {self.period_wd_yr:.1f} Years\n"
                f"WD Closest : {r_peri_wd:.2f} AU\n"
                f"WD Farthest: {r_apa_wd:.2f} AU\n"
                f"Stability  : {stability_status}"
                f" (Lim {a_crit:.2f} AU)\n"
                f"Max Kozai e: {e_max_kozai:.3f}\n"
                f"Kozai T    : {t_kozai:.2e} yr\n"
                f"Tidal Param: {tidal_param:.2e}"
            ))

            # ---- Static orbit tracks (one binary period) ----
            times = np.linspace(0, self.period_wd_yr, 2000)
            tr = np.array([self.binary_positions(t) for t in times])
            self.track_orange = tr[:, 0:3]
            self.track_wd = tr[:, 3:6]
            self.track_rel = tr[:, 3:6] - tr[:, 0:3]

            # ---- Planet initialization (t = 0) ----
            stars0 = self.binary_positions(0.0)
            self.px = stars0[0] + self.a_p
            self.py = stars0[1]
            self.pz = stars0[2]

            v_circ = np.sqrt(G_SIM * self.m_orange / self.a_p)
            vx_o, vy_o, vz_o = self.binary_velocity(0.0, "orange")
            self.vx = vx_o
            self.vy = vy_o + v_circ
            self.vz = vz_o

            # ---- Reset trails and clock ----
            self.planet_history = []
            self.orange_history = []
            self.wd_history = []
            self.year_label.config(text="Simulation Years : 0")

            self.force_plot_redraw()
            self.update_env_display()
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
            self.ax.plot(self.track_rel[:, 0], self.track_rel[:, 1],
                         self.track_rel[:, 2], color="white", linestyle=":",
                         linewidth=1.5, label="WD Orbit (rel. to Orange)")

        self.ax.set_xlabel("X (AU)")
        self.ax.set_ylabel("Y (AU)")
        self.ax.set_zlabel("Z (AU)")
        self.ax.view_init(elev=25, azim=40)

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
        """Synchronized samples for all three bodies (same frame, same index)
        so trails can be re-based into any view frame."""
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
                # Re-base each stored sample onto the orange dwarf's position
                # AT THAT SAMPLE'S TIME
                p = p - o
                w = w - o
                o = o - o

            self.planet_trail.set_data_3d(p[:, 0], p[:, 1], p[:, 2])
            self.orange_trail.set_data_3d(o[:, 0], o[:, 1], o[:, 2])
            self.wd_trail.set_data_3d(w[:, 0], w[:, 1], w[:, 2])

        self.canvas.draw_idle()

    def update_stats_label(self):
        a_osc, e_osc, i_osc, r_planet, sep = self.osculating_elements()
        self.year_label.config(text=(
            f"Simulation Years : {self.time_step:.1f}\n"
            f"Planet Orbits    : {self.time_step / self.period_p_yr:.2f}\n"
            f"WD Orbits        : {self.time_step / self.period_wd_yr:.4f}\n"
            f"Binary Sep       : {sep:.1f} AU\n"
            f"Planet r         : {r_planet:.4f} AU\n"
            f"Osc. a           : {a_osc:.6f} AU\n"
            f"Osc. e           : {e_osc:.6f}\n"
            f"Osc. i           : {i_osc:.4f}°\n"
            f"Warp             : {self.speed_slider.get()}"
            f"   View: {self.view_mode}"
        ))

    # ------------------------------------------------------ Animation

    def animate_loop(self):
        if not self.is_running:
            return

        span = self.speed_slider.get() * 0.01  # years per frame
        self.advance(span)

        stars = self.binary_positions(self.time_step)
        self.record_history(stars)

        self.update_stats_label()
        self.update_env_display()
        self.render_frame()
        self.animation_id = self.root.after(100, self.animate_loop)


if __name__ == "__main__":
    root = tk.Tk()
    app = AnimatedOrbitalSimApp(root)
    root.mainloop()
