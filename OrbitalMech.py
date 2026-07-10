import tkinter as tk
from tkinter import ttk, messagebox
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

class AnimatedOrbitalSimApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Animated Hierarchical Binary Orbital Simulator")
        self.root.geometry("1150x800")
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
        self.left_frame = ttk.Frame(root, padding=20)
        self.left_frame.pack(side=tk.LEFT, fill=tk.Y)

        self.right_frame = ttk.Frame(root, padding=10)
        self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

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

        # Setup input boxes
        self.m_orange_entry = create_input("Orange Dwarf Mass (M☉):", 0.85)
        self.m_wd_entry = create_input("White Dwarf Mass (M☉):", 0.70)
        self.age_entry = create_input("White Dwarf Cooling Age (Gyr):", 0.1)
        self.a_wd_entry = create_input("White Dwarf Semi-Major Axis (AU):", 115)
        self.e_wd_entry = create_input("White Dwarf Eccentricity (0-0.99):", 0.875)
        self.i_wd_entry = create_input("White Dwarf Inclination (Degrees):", 75)
        self.a_p_entry = create_input("Planet Semi-Major Axis (AU):", 0.725)

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
        self.speed_slider.set(5)
        self.speed_slider.pack(fill=tk.X, pady=(0, 15))

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

    def setup_plot(self):
        self.fig = plt.figure(figsize=(7, 7), facecolor='#0d1117')
        self.ax = self.fig.add_subplot(111, projection='3d')
        self.ax.set_facecolor('#0d1117')

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.right_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def update_parameters(self):
        try:
            # Parse metrics safely
            self.m_orange = float(self.m_orange_entry.get())
            self.m_wd = float(self.m_wd_entry.get())
            age_gyr = float(self.age_entry.get())
            self.a_wd = float(self.a_wd_entry.get())
            self.e_wd = float(self.e_wd_entry.get())
            self.i_wd_deg = float(self.i_wd_entry.get())
            self.a_p = float(self.a_p_entry.get())

            if self.e_wd < 0 or self.e_wd >= 1:
                raise ValueError("Eccentricity must be between 0 and 0.99")

            self.i_wd_rad = np.radians(self.i_wd_deg)

            # Physics Math
            L_orange = self.m_orange ** 4
            L_wd = 1e-3 * (self.m_wd ** -1) * (age_gyr ** -1.4)
            r_peri_wd = self.a_wd * (1 - self.e_wd)
            r_apa_wd = self.a_wd * (1 + self.e_wd)
            mu = self.m_orange / ( self.m_orange + self.m_wd)

            # Keep track of orbital frequencies
            self.period_p_yr = np.sqrt(self.a_p ** 3 / self.m_orange)
            self.period_wd_yr = np.sqrt(self.a_wd ** 3 / (self.m_orange + self.m_wd))

            #a_crit = self.a_wd * (0.464 - 0.380 * self.e_wd) * (1 - 0.02 * self.i_wd_rad)

            # Holman & Wiegert criterion for S-type orbit - (planet orbiting one star of a binary)
            # a_crit=a_wd(0.464−0.380μ−0.631eb+0.586μeb+0.150eb^2-0.198μeb^2)
            # μ = M2/(M1+M2)
            a_crit = self.a_wd * (
                    0.464
                    - 0.380 * mu
                    - 0.631 * self.e_wd
                    + 0.586 * mu * self.e_wd
                    + 0.150 * self.e_wd ** 2
                    - 0.198 * mu * self.e_wd ** 2
            )

            stability_status = "STABLE" if self.a_p < a_crit else "UNSTABLE!"

            kozai_term = 1 - (5 / 3) * (np.cos(self.i_wd_rad) ** 2)

            if kozai_term > 0:
                e_max_kozai = np.sqrt(kozai_term)
            else:
                e_max_kozai = 0

            # Render calculations text
            self.output_text.delete("1.0", tk.END)
            metrics_str = (
                f"Orange L☉  : {L_orange:.4f}\n"
                f"WD L☉      : {L_wd:.4f}\n"
                f"Planet Year: {self.period_p_yr * 365.25:.1f} Days\n"
                f"Binary Year: {self.period_wd_yr:.1f} Years\n"
                f"WD Closest : {r_peri_wd:.2f} AU\n"
                f"WD Farthest: {r_apa_wd:.2f} AU\n"
                f"Stability  : {stability_status}\n"
                f" (Limit: {a_crit:.2f} AU)\n"
                f"Max Kozai e: {e_max_kozai:.3f}"
            )
            self.output_text.insert(tk.END, metrics_str)

            # Compute trace tracks
            theta = np.linspace(0, 2 * np.pi, 500)

            # Static tracing for background orbits
            self.visual_scale = self.a_wd * 0.15 / self.a_p
            self.track_x_p = self.a_p * np.cos(theta) * self.visual_scale
            self.track_y_p = self.a_p * np.sin(theta) * self.visual_scale
            self.track_z_p = np.zeros_like(theta)

            r_wd_vec = (self.a_wd * (1 - self.e_wd ** 2)) / (1 + self.e_wd * np.cos(theta))
            self.track_x_wd = r_wd_vec * np.cos(theta)
            y_wd_flat = r_wd_vec * np.sin(theta)
            self.track_y_wd = y_wd_flat * np.cos(self.i_wd_rad)
            self.track_z_wd = y_wd_flat * np.sin(self.i_wd_rad)

            self.force_plot_redraw()

        except ValueError as e:
            messagebox.showerror("Input Error", f"Invalid parameters entered:\n{e}")

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
        # Clears plot window elements and resets boundaries cleanly
        self.ax.clear()
        self.ax.xaxis.label.set_color('#8b949e')
        self.ax.yaxis.label.set_color('#8b949e')
        self.ax.zaxis.label.set_color('#8b949e')
        self.ax.tick_params(colors='#8b949e')

        # Static background helper paths
        self.ax.plot(self.track_x_wd, self.track_y_wd, self.track_z_wd, color='#8000FF', linestyle=':',
                     label="White Dwarf Path")
        self.ax.plot(self.track_x_p, self.track_y_p, self.track_z_p, color='#64FF00', linestyle=':', alpha=0.7,
                     label=f"Planet Path (Scaled x{self.visual_scale:.1f})")

        # Center Primary Star marker
        self.ax.scatter(0, 0, 0, color='#f97316', s=180, edgecolors='none', label="Orange Dwarf (System Hub)")

        # Persistent plot canvas limits
        max_range = self.a_wd * (1 + self.e_wd)
        self.ax.set_xlim(-max_range, max_range * 0.4)
        self.ax.set_ylim(-max_range * 0.7, max_range * 0.7)
        self.ax.set_zlim(-max_range * 0.7, max_range * 0.7)
        self.ax.set_xlabel("X (AU)")
        self.ax.set_ylabel("Y (AU)")
        self.ax.set_zlabel("Z (AU)")
        self.ax.legend(facecolor='#161b22', edgecolor='none', labelcolor='white', loc="upper left")
        self.ax.view_init(elev=25, azim=40)

        # Establish blank dynamic elements we can update rapidly later
        self.planet_dot, = self.ax.plot([], [], [], 'o', color='#58a6ff', markersize=7, label="Planet Position")
        self.wd_dot, = self.ax.plot([], [], [], 'o', color='#ffffff', markersize=8, markeredgecolor='#58a6ff',
                                    label="White Dwarf Position")

    def animate_loop(self):
        if not self.is_running:
            return

        # Advance running configuration step speed
        speed_modifier = self.speed_slider.get() * 0.02
        self.time_step += speed_modifier

        # 1. Evaluate Planet Position (Fast-moving inner circle)
        # Angular speed scales inversely with orbital year period
        theta_p = (self.time_step / self.period_p_yr) % (2 * np.pi)
        xp = self.a_p * np.cos(theta_p) * self.visual_scale
        yp = self.a_p * np.sin(theta_p) * self.visual_scale
        zp = 0





if __name__ == "__main__":
    root = tk.Tk()
    app = AnimatedOrbitalSimApp(root)
    root.mainloop()