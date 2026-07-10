import tkinter as tk
from tkinter import ttk, messagebox
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

class AnimatedOrbitalSimApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Animated Hierarchical Binary Orbital Simulator")
        self.root.geometry("1200x990+25+0")
        self.root.configure(bg="#0d1117")

        # Animation state variables
        self.is_running = True
        self.time_step = 0.0  # Normalized system time unit
        self.animation_id = None

        # Custom Dark Theme Styling
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure(".", background="#0d1117", foreground="white", fieldbackground="#161b22")
        self.style.configure("TLabel", background="#0d1117", foreground="#c9d1d9", font=("Arial", 10))
        self.style.configure("TButton", background="#21262d", foreground="white", font=("Arial", 10, "bold"))
        self.style.map("TButton", background=[("active", "#30363d")])

        # Layout Frames
        self.left_frame = ttk.Frame(root, padding=0, width=280)
        self.left_frame.pack(side=tk.LEFT, fill=tk.Y)
        self.left_frame.pack_propagate(False)

        self.right_frame = ttk.Frame(root, padding=1)
        self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.ff_years_entry = ttk.Entry( self.left_frame, width=10 )
        self.ff_years_entry.insert(0,"0.25")
        self.ff_years_entry.pack(fill=tk.X)

        self.setup_inputs()
        self.setup_plot()

        # Start core calculation and kick off animation loop
        self.update_parameters()
        self.animate_loop()

    def setup_inputs(self):
        title = ttk.Label(self.left_frame, text="System Parameters", font=("Arial", 14, "bold"), foreground="#58a6ff")
        title.pack(pady=(0, 15), anchor="w")

        def create_input(label_text, default_val):
            lbl = ttk.Label(self.left_frame, text=label_text)
            lbl.pack(anchor="w", pady=(2, 1))
            entry = ttk.Entry(self.left_frame, width=25)
            entry.insert(0, str(default_val))
            entry.pack(anchor="w", pady=(0, 8))
            return entry

        self.year_label = ttk.Label(
            self.left_frame,
            text="Planet Year: 0.00",
            font=("Arial", 11, "bold"),
            foreground="#58a6ff"
        )
        self.year_label.pack(fill=tk.X, pady=10)

        # Setup input boxes
        self.m_orange_entry = create_input("Orange Dwarf Mass (M☉):", 0.85)
        self.m_wd_entry = create_input("White Dwarf Mass (M☉):", 0.70)
        self.age_entry = create_input("White Dwarf Cooling Age (Gyr):", 0.1)
        self.a_wd_entry = create_input("White Dwarf Semi-Major Axis (AU):", 115)
        self.e_wd_entry = create_input("White Dwarf Eccentricity (0-0.99):", 0.875)
        self.i_wd_entry = create_input("White Dwarf Inclination (Degrees):", 75)
        self.a_p_entry = create_input("Planet Semi-Major Axis (AU):", 0.725)
        self.zoom_factor = 0.15

        # Update Parameters Button
        self.btn_calc = ttk.Button(self.left_frame, text="Apply Changes", command=self.update_parameters)
        self.btn_calc.pack(fill=tk.X, pady=10)

        # ANIMATION INTERACTIVE CONTROLS
        anim_title = ttk.Label(self.left_frame, text="Animation Engine", font=("Arial", 11, "bold"),
                               foreground="#58a6ff")
        anim_title.pack(anchor="w", pady=(10, 5))

        self.btn_toggle = ttk.Button(self.left_frame, text="Pause Simulation", command=self.toggle_animation)
        self.btn_toggle.pack(fill=tk.X, pady=5)

        lbl_speed = ttk.Label(self.left_frame, text="Simulation Warp Speed:")
        lbl_speed.pack(anchor="w", pady=(5, 2))
        self.speed_slider = tk.Scale(self.left_frame, from_=1, to=20, orient=tk.HORIZONTAL, bg="#161b22", fg="white",
                                     highlightthickness=0)
        self.speed_slider.set(1)
        self.speed_slider.pack(fill=tk.X, pady=(0, 15))

        ttk.Button(
            self.left_frame,
            text="Fast Forward",
            command=self.fast_forward
        ).pack(fill=tk.X)

        ttk.Button(
            self.left_frame,
            text="Zoom In",
            command=lambda: self.change_zoom(0.8)
        ).pack(fill=tk.X, pady=2)

        ttk.Button(
            self.left_frame,
            text="Zoom Out",
            command=lambda: self.change_zoom(1.25)
        ).pack(fill=tk.X, pady=2)

        ttk.Button(
            self.left_frame,
            text="Next Periastron",
            command=self.next_periastron
        )

        # Metrics Panel
        self.output_lbl = ttk.Label(self.left_frame, text="Calculated Metrics:", font=("Arial", 11, "bold"),
                                    foreground="#58a6ff")
        self.output_lbl.pack(anchor="w", pady=(5, 2))

        self.output_text = tk.Text(
            self.left_frame,
            width=32,
            height=10,
            bg="#161b22",
            fg="#c9d1d9",
            font=("Consolas", 10),
            bd=0,
            padx=5,
            pady=5
        )
        self.output_text.pack(fill=tk.BOTH, expand=True)

    def fast_forward(self,remaining):

        binary_years = float(
            self.ff_years_entry.get()
        )

        target = (
                binary_years
                * self.period_wd_yr
        )

        steps = int(
            target /
            self.dt
        )

        for _ in range(steps):
            theta_wd, _ = self.true_anomaly(
                self.time_step
            )

            (
                x_orange,
                y_orange,
                z_orange,
                x_wd,
                y_wd,
                z_wd
            ) = self.binary_positions(
                self.time_step
            )

            self.integrate_planet(
                x_orange,
                y_orange,
                z_orange,
                x_wd,
                y_wd,
                z_wd
            )

            self.time_step += self.dt

    def next_periastron(self):

        cycles = (
                self.time_step /
                self.period_wd_yr
        )

        next_cycle = int(cycles) + 1

        self.time_step = (
                next_cycle
                * self.period_wd_yr
        )

    def setup_plot(self):
        self.fig = plt.figure(figsize=(8, 8), facecolor='#0d1117')
        self.ax = self.fig.add_subplot(111, projection='3d')
        self.ax.set_facecolor('#0d1117')
        self.ax.scatter(
            14.4,
            0,
            0,
            color='red',
            s=80,
            label='WD Periastron'
        )

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

    def binary_positions(self, t_years):

        M = (
                2 * np.pi *
                t_years /
                self.period_wd_yr
        )

        M = np.mod(M, 2 * np.pi)

        E = M

        for _ in range(8):
            E -= (
                         E -
                         self.e_wd * np.sin(E) -
                         M
                 ) / (
                         1 -
                         self.e_wd * np.cos(E)
                 )

        x_rel = self.a_wd * (
                np.cos(E)
                - self.e_wd
        )

        y_rel = (
                self.a_wd
                * np.sqrt(1 - self.e_wd ** 2)
                * np.sin(E)
        )

        x_rel3 = x_rel

        y_rel3 = (
                y_rel
                * np.cos(self.i_wd_rad)
        )

        z_rel3 = (
                y_rel
                * np.sin(self.i_wd_rad)
        )

        f_orange = (
                self.m_wd /
                (self.m_orange + self.m_wd)
        )

        f_wd = (
                self.m_orange /
                (self.m_orange + self.m_wd)
        )

        x_orange = -f_orange * x_rel3
        y_orange = -f_orange * y_rel3
        z_orange = -f_orange * z_rel3

        x_wd = f_wd * x_rel3
        y_wd = f_wd * y_rel3
        z_wd = f_wd * z_rel3

        print( "M=", M, "E=", E )

        return (
            x_orange,
            y_orange,
            z_orange,
            x_wd,
            y_wd,
            z_wd
        )

    def planet_acceleration(
            self,
            px, py, pz,
            x_orange, y_orange, z_orange,
            x_wd, y_wd, z_wd
    ):
        G = 4 * np.pi ** 2

        dx1 = px - x_orange
        dy1 = py - y_orange
        dz1 = pz - z_orange

        r1 = np.sqrt(dx1 ** 2 + dy1 ** 2 + dz1 ** 2)

        dx2 = px - x_wd
        dy2 = py - y_wd
        dz2 = pz - z_wd

        r2 = np.sqrt(dx2 ** 2 + dy2 ** 2 + dz2 ** 2)

        ax = (
                -G * self.m_orange * dx1 / r1 ** 3
                - G * self.m_wd * dx2 / r2 ** 3
        )

        ay = (
                -G * self.m_orange * dy1 / r1 ** 3
                - G * self.m_wd * dy2 / r2 ** 3
        )

        az = (
                -G * self.m_orange * dz1 / r1 ** 3
                - G * self.m_wd * dz2 / r2 ** 3
        )

        return ax, ay, az

    def integrate_planet(
            self,
            x_orange, y_orange, z_orange,
            x_wd, y_wd, z_wd
    ):

        ax, ay, az = self.planet_acceleration(
            self.px, self.py, self.pz,
            x_orange, y_orange, z_orange,
            x_wd, y_wd, z_wd
        )

        # half kick
        self.vx += 0.5 * ax * self.dt
        self.vy += 0.5 * ay * self.dt
        self.vz += 0.5 * az * self.dt

        # drift
        self.px += self.vx * self.dt
        self.py += self.vy * self.dt
        self.pz += self.vz * self.dt

        ax, ay, az = self.planet_acceleration(
            self.px, self.py, self.pz,
            x_orange, y_orange, z_orange,
            x_wd, y_wd, z_wd
        )

        # second half kick
        self.vx += 0.5 * ax * self.dt
        self.vy += 0.5 * ay * self.dt
        self.vz += 0.5 * az * self.dt

    def true_anomaly(self, t_years):

        M = (
                2 * np.pi *
                t_years /
                self.period_wd_yr
        )

        M = np.mod(M, 2 * np.pi)

        E = M

        for _ in range(8):
            E = E - (
                    E
                    - self.e_wd * np.sin(E)
                    - M
            ) / (
                        1 - self.e_wd * np.cos(E)
                )

        theta = 2 * np.arctan2(
            np.sqrt(1 + self.e_wd) * np.sin(E / 2),
            np.sqrt(1 - self.e_wd) * np.cos(E / 2)
        )

        return theta, E

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
                raise ValueError(
                    "Eccentricity must be between 0 and 0.99"
                )

            self.i_wd_rad = np.radians(
                self.i_wd_deg
            )

            # ---------------------------------------
            # Stellar properties
            # ---------------------------------------

            L_orange = self.m_orange ** 4

            L_wd = (
                    1e-3
                    * (self.m_wd ** -1)
                    * (age_gyr ** -1.4)
            )

            r_peri_wd = self.a_wd * (
                    1 - self.e_wd
            )

            r_apa_wd = self.a_wd * (
                    1 + self.e_wd
            )

            mu = (
                    self.m_orange /
                    (self.m_orange + self.m_wd)
            )

            self.period_p_yr = np.sqrt(
                self.a_p ** 3 /
                self.m_orange
            )

            self.period_wd_yr = np.sqrt(
                self.a_wd ** 3 /
                (self.m_orange + self.m_wd)
            )

            # ---------------------------------------
            # Stability estimate
            # ---------------------------------------

            a_crit = self.a_wd * (
                    0.464
                    - 0.380 * mu
                    - 0.631 * self.e_wd
                    + 0.586 * mu * self.e_wd
                    + 0.150 * self.e_wd ** 2
                    - 0.198 * mu * self.e_wd ** 2
            )

            stability_status = (
                "STABLE"
                if self.a_p < a_crit
                else "UNSTABLE!"
            )

            kozai_term = (
                    1
                    - (5 / 3)
                    * np.cos(self.i_wd_rad) ** 2
            )

            if kozai_term > 0:
                e_max_kozai = np.sqrt(
                    kozai_term
                )
            else:
                e_max_kozai = 0

            # ---------------------------------------
            # Output text
            # ---------------------------------------

            self.output_text.delete(
                "1.0",
                tk.END
            )

            metrics_str = (
                f"Orange L☉  : {L_orange:.4f}\n"
                f"WD L☉      : {L_wd:.4f}\n"
                f"Planet Year: {self.period_p_yr * 365.25:.1f} Days\n"
                f"Binary Year: {self.period_wd_yr:.1f} Years\n"
                f"WD Closest : {r_peri_wd:.2f} AU\n"
                f"WD Farthest: {r_apa_wd:.2f} AU\n"
                f"Stability  : {stability_status}\n"
                f"(Limit: {a_crit:.2f} AU)\n"
                f"Max Kozai e: {e_max_kozai:.3f}"
            )

            self.output_text.insert(
                tk.END,
                metrics_str
            )

            # =======================================
            # BARYCENTRIC ORBIT TRACKS
            # =======================================

            E_grid = np.linspace(
                0,
                2 * np.pi,
                2000
            )

            self.track_x_orange = []
            self.track_y_orange = []
            self.track_z_orange = []

            self.track_x_wd = []
            self.track_y_wd = []
            self.track_z_wd = []

            f_orange = (
                    self.m_wd /
                    (self.m_orange + self.m_wd)
            )

            f_wd = (
                    self.m_orange /
                    (self.m_orange + self.m_wd)
            )

            for E in E_grid:
                x_rel = (
                        self.a_wd *
                        (np.cos(E) - self.e_wd)
                )

                y_rel = (
                        self.a_wd
                        * np.sqrt(
                    1 - self.e_wd ** 2
                )
                        * np.sin(E)
                )

                y3 = (
                        y_rel *
                        np.cos(self.i_wd_rad)
                )

                z3 = (
                        y_rel *
                        np.sin(self.i_wd_rad)
                )

                self.track_x_orange.append(
                    -f_orange * x_rel
                )

                self.track_y_orange.append(
                    -f_orange * y3
                )

                self.track_z_orange.append(
                    -f_orange * z3
                )

                self.track_x_wd.append(
                    f_wd * x_rel
                )

                self.track_y_wd.append(
                    f_wd * y3
                )

                self.track_z_wd.append(
                    f_wd * z3
                )

            # =======================================
            # N-BODY PLANET INITIALIZATION
            # =======================================

            (
                x_orange0,
                y_orange0,
                z_orange0,
                _,
                _,
                _
            ) = self.binary_positions(
                0.0
            )

            G = 4 * np.pi ** 2

            self.px = (
                    x_orange0
                    + self.a_p
            )

            self.py = y_orange0
            self.pz = z_orange0

            v_circ = np.sqrt(
                G *
                self.m_orange /
                self.a_p
            )

            self.vx = 0.0
            self.vy = v_circ
            self.vz = 0.0

            self.dt = 0.0002

            # reset trail

            self.planet_history_x = []
            self.planet_history_y = []
            self.planet_history_z = []

            # default zoom

            self.visual_scale = (
                    self.a_wd
                    * 0.15
                    / self.a_p
            )

            self.force_plot_redraw()

        except ValueError as e:
            messagebox.showerror(
                "Input Error",
                f"Invalid parameters entered:\n{e}"
            )

    def toggle_animation(self):
        self.is_running = not self.is_running
        if self.is_running:
            self.btn_toggle.config(text="Pause Simulation")
            self.animate_loop()
        else:
            self.btn_toggle.config(text="Play Simulation")
            if self.animation_id:
                self.root.after_cancel(self.animation_id)

    def force_plot_redraw(self):

        self.ax.clear()

        self.ax.xaxis.label.set_color('#8b949e')
        self.ax.yaxis.label.set_color('#8b949e')
        self.ax.zaxis.label.set_color('#8b949e')

        self.ax.tick_params(colors='#8b949e')

        self.update_axes_limits()

        # -----------------------------------
        # Barycenter
        # -----------------------------------

        self.ax.scatter(
            0,
            0,
            0,
            color="yellow",
            marker="+",
            s=350,
            linewidths=3,
            label="Barycenter"
        )

        # -----------------------------------
        # Orange dwarf orbit
        # -----------------------------------

        self.ax.plot(
            self.track_x_orange,
            self.track_y_orange,
            self.track_z_orange,
            color="#f97316",
            linestyle=":",
            linewidth=1.5,
            label="Orange Dwarf Orbit"
        )

        # -----------------------------------
        # White dwarf orbit
        # -----------------------------------

        self.ax.plot(
            self.track_x_wd,
            self.track_y_wd,
            self.track_z_wd,
            color="white",
            linestyle=":",
            linewidth=1.5,
            label="White Dwarf Orbit"
        )

        # -----------------------------------
        # Labels
        # -----------------------------------

        self.ax.set_xlabel("X (AU)")
        self.ax.set_ylabel("Y (AU)")
        self.ax.set_zlabel("Z (AU)")

        self.ax.legend(
            facecolor="#161b22",
            edgecolor="none",
            labelcolor="white",
            loc="upper left"
        )

        self.ax.view_init(
            elev=25,
            azim=40
        )

        # -----------------------------------
        # Dynamic objects
        # -----------------------------------

        self.orange_dot, = self.ax.plot(
            [], [], [],
            'o',
            color='#f97316',
            markersize=10,
            label='Orange Dwarf'
        )

        self.wd_dot, = self.ax.plot(
            [], [], [],
            'o',
            color='white',
            markersize=8,
            markeredgecolor='#58a6ff',
            label='White Dwarf'
        )

        self.planet_dot, = self.ax.plot(
            [], [], [],
            'o',
            color='#58a6ff',
            markersize=6,
            label='Planet'
        )

        self.planet_trail, = self.ax.plot(
            [], [], [],
            color='#58a6ff',
            linewidth=1.2,
            alpha=0.7
        )

        self.orange_trail, = self.ax.plot(
            [], [], [],
            color='#f97316',
            linewidth=1.0,
            alpha=0.6
        )

        self.wd_trail, = self.ax.plot(
            [], [], [],
            color='white',
            linewidth=1.0,
            alpha=0.6
        )

        self.canvas.draw_idle()

    def animate_loop(self):

        if not self.is_running:
            return

        # Advance simulation time
        speed_modifier = self.speed_slider.get() * 0.03
        self.time_step += speed_modifier

        # White dwarf orbital phase
        M = 2 * np.pi * self.time_step / self.period_wd_yr

        E = M
        for _ in range(5):
            E -= (
                         E
                         - self.e_wd * np.sin(E)
                         - M
                 ) / (
                         1 - self.e_wd * np.cos(E)
                 )

        theta_wd, E = self.true_anomaly(
            self.time_step
        )

        (
            x_orange,
            y_orange,
            z_orange,
            x_wd,
            y_wd,
            z_wd
        ) = self.binary_positions(self.time_step)

        # -----------------------------------------
        # Integrate planet
        # -----------------------------------------

        substeps = 20

        for _ in range(substeps):
            self.integrate_planet(
                x_orange,
                y_orange,
                z_orange,
                x_wd,
                y_wd,
                z_wd
            )

        xp = self.px
        yp = self.py
        zp = self.pz

        # -----------------------------------------
        # Statistics
        # -----------------------------------------

        rx = xp - x_orange
        ry = yp - y_orange
        rz = zp - z_orange

        r_planet = np.sqrt(
            rx ** 2 +
            ry ** 2 +
            rz ** 2
        )

        planet_orbits = (
                self.time_step /
                self.period_p_yr
        )

        wd_orbits = (
                self.time_step /
                self.period_wd_yr
        )

        self.year_label.config(
            text=(
                f"Simulation Years : {self.time_step:.1f}\n"
                f"Planet Orbits    : {planet_orbits:.2f}\n"
                f"WD Orbits        : {wd_orbits:.4f}\n"
                f"Planet Radius    : {r_planet:.3f} AU\n"
                f"Warp             : {self.speed_slider.get()}"
            )
        )

        # -----------------------------------------
        # Update markers
        # -----------------------------------------

        self.orange_dot.set_data_3d(
            [x_orange],
            [y_orange],
            [z_orange]
        )

        self.wd_dot.set_data_3d(
            [x_wd],
            [y_wd],
            [z_wd]
        )

        self.planet_dot.set_data_3d(
            [xp],
            [yp],
            [zp]
        )

        # Optional trajectory trail
        if not hasattr(self, "planet_history_x"):
            self.planet_history_x = []
            self.planet_history_y = []
            self.planet_history_z = []

        self.planet_history_x.append(xp)
        self.planet_history_y.append(yp)
        self.planet_history_z.append(zp)

        max_history = 2000

        if len(self.planet_history_x) > max_history:
            self.planet_history_x.pop(0)
            self.planet_history_y.pop(0)
            self.planet_history_z.pop(0)

        if hasattr(self, "planet_trail"):
            self.planet_trail.set_data_3d(
                self.planet_history_x,
                self.planet_history_y,
                self.planet_history_z
            )

        if not hasattr(self, "orange_history_x"):
            self.orange_history_x = []
            self.orange_history_y = []
            self.orange_history_z = []

        if not hasattr(self, "wd_history_x"):
            self.wd_history_x = []
            self.wd_history_y = []
            self.wd_history_z = []

        self.orange_history_x.append(x_orange)
        self.orange_history_y.append(y_orange)
        self.orange_history_z.append(z_orange)

        self.wd_history_x.append(x_wd)
        self.wd_history_y.append(y_wd)
        self.wd_history_z.append(z_wd)


        self.orange_trail.set_data_3d(
            self.orange_history_x,
            self.orange_history_y,
            self.orange_history_z
        )

        self.wd_trail.set_data_3d(
            self.wd_history_x,
            self.wd_history_y,
            self.wd_history_z
        )
        print(
            "t =", self.time_step,
            "P =", self.period_wd_yr
        )
        # Refresh display
        self.canvas.draw_idle()

        self.animation_id = self.root.after(
            30,
            self.animate_loop
        )


if __name__ == "__main__":
    root = tk.Tk()
    app = AnimatedOrbitalSimApp(root)
    root.mainloop()