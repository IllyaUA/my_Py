import json
import os
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "configs")


# Constants
# Units everywhere: AU, years, solar masses -> G = 4*pi^2.

G_SIM = 4.0 * np.pi ** 2

M_MOON_MSUN = 3.69e-8        # lunar mass in M(sun)
M_EARTH_MSUN = 3.0035e-6     # Earth mass in M(sun)
M_JUP_MSUN = 9.5458e-4       # Jupiter mass in M(sun)
M_MARS_MSUN = 3.226e-7       # Mars mass in M(sun)
D_MOON_AU = 0.002570         # Earth-Moon distance in AU
R_EARTH_AU = 4.2635e-5       # Earth radius in AU
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

# Domingos, Winter & Neto (2006) prograde satellite stability coefficient
SAT_STABILITY_C = 0.4895

try:
    TRAPZ = np.trapezoid
except AttributeError:          # numpy < 2.0
    TRAPZ = np.trapz


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
    return TRAPZ(B, lam) / (sigma * T ** 4)


# UV output of the Sun per unit luminosity, the normalization for
# "Earth UV units" (UV flux at Earth = 1 by construction)
F_UV_SUN = planck_band_fraction(T_SUN)


def kepler_state(a, e, i_deg, f_deg, mu):
    """Position and velocity from orbital elements, node = 0, argument of
    periapsis = 0, inclination measured about the +x axis (same convention
    as binary_positions). Returns two length-3 arrays."""
    i = np.radians(i_deg)
    f = np.radians(f_deg)
    p = a * (1.0 - e ** 2)
    r = p / (1.0 + e * np.cos(f))

    x_p = r * np.cos(f)
    y_p = r * np.sin(f)

    vfac = np.sqrt(mu / p)
    vx_p = -vfac * np.sin(f)
    vy_p = vfac * (e + np.cos(f))

    ci, si = np.cos(i), np.sin(i)
    pos = np.array([x_p, y_p * ci, y_p * si])
    vel = np.array([vx_p, vy_p * ci, vy_p * si])
    return pos, vel


# ------------------------------------------------------- Built-in configs
# Written to ./configs/ on first run if absent. They are plain JSON, so you
# can edit them in a text editor or copy them between machines. Anything you
# save from the UI lands in the same folder and appears in the dropdown.

DEFAULT_CONFIG = "Finsternis twin worlds"

BUILTIN_CONFIGS = [
    {
        "name": "Finsternis twin worlds",
        "notes": (
            "The Finsternis secular system plus a second-generation world "
            "orbiting the white dwarf itself. 2 Mars masses at 0.31 AU, "
            "an 81.4 day year, R ~ 0.66 R_E, g ~ 0.49 g. Stable: the "
            "S-type limit around the WD (perturber = the orange dwarf, "
            "mu = 0.586) is 0.687 AU, a 2.2x margin. First-generation "
            "planets this close were engulfed during the progenitor's "
            "giant phase, so this world formed AFTER the white dwarf did, "
            "out of fallback debris - which is also why it is small. "
            "Climate runs on a cooling clock: at WD age 30 Myr it sits at "
            "S=0.85 (temperate, T_eq 244 K), having left the runaway zone "
            "1.3 Myr ago, and it freezes for good in ~19.5 Myr as the WD "
            "fades. Tides from the WD run ~9.3 lunar. UV is ~5x Earth and "
            "with 0.49 g the atmosphere is leaking. Every 26.3 yr the "
            "orange dwarf's approach adds a ~6% flux pulse: a second "
            "summer from the other star. The two worlds mirror each "
            "other: the blue planet's millennial cycle is driven by the "
            "WD, the WD planet's generation-scale fate is set by its own "
            "sun's cooling."),
        "m_orange": 0.85, "m_wd": 0.6, "wd_age_gyr": 0.03,
        "a_wd": 10.0, "e_wd": 0.65, "i_wd": 0.0,
        "blue_mass_e": 1.0, "blue_a": 0.725, "blue_e": 0.0,
        "blue_inc": 0.0, "blue_f0": 0.0,
        "giant_enabled": False,
        "giant_mass_j": 1.0, "giant_a": 1.8, "giant_e": 0.05,
        "giant_inc": 2.0, "giant_f0": 180.0,
        "wdp_enabled": True,
        "wdp_mass_mars": 2.0, "wdp_a": 0.31, "wdp_e": 0.02,
        "wdp_inc": 0.5, "wdp_f0": 90.0,
        "obliquity": 23.4, "spin_azimuth": 0.0,
        "moon_draw_scale": 400,
        "moons": [
            {"enabled": True, "mass_lunar": 1.0, "a": 0.0015,
             "inc": 2.0, "phase": 0.0},
            {"enabled": False, "mass_lunar": 0.1, "a": 0.0009,
             "inc": 0.5, "phase": 90.0},
        ],
    },
    {
        "name": "Finsternis secular",
        "notes": (
            "High-influence configuration. The white dwarf is close (10 AU, "
            "e=0.65) and COPLANAR. It does not heat or tide the planet "
            "directly - at 2.8 AU its tide is 1.3% of the host's. What it "
            "does is force the planet's OWN eccentricity through the "
            "coplanar secular term, cycling e between 0.012 and 0.189 on a "
            "MEASURED 1012 yr envelope (the linear estimate of 1457 yr runs "
            "about 30% long). At the peak: instellation 1.51 -> 0.70 Earth "
            "units, T_eq 282 -> 233 K (a 49 K swing inside one 244-day "
            "year), host tide about 1.9 -> 0.6 lunar. "
            "Between peaks the orbit is nearly circular and the world is "
            "unremarkable. Figures converged at 800+ steps/orbit; coarser "
            "integration inflates the peak badly. "
            "Inclination MUST stay under ~5 deg: at 10 deg the octupole "
            "term pumps e to 0.68, periastron falls to 0.23 AU and the "
            "planet cooks. Stability limit is 0.83 AU, so no gas giant and "
            "no outer planets are possible. A Luna-distance moon is "
            "stripped at peak eccentricity; this one sits at 0.0015 AU "
            "with a ~12 day period."),
        "m_orange": 0.85, "m_wd": 0.6, "wd_age_gyr": 0.03,
        "a_wd": 10.0, "e_wd": 0.65, "i_wd": 0.0,
        "blue_mass_e": 1.0, "blue_a": 0.725, "blue_e": 0.0,
        "blue_inc": 0.0, "blue_f0": 0.0,
        "giant_enabled": False,
        "giant_mass_j": 1.0, "giant_a": 1.8, "giant_e": 0.05,
        "giant_inc": 2.0, "giant_f0": 180.0,
        "obliquity": 23.4, "spin_azimuth": 0.0,
        "moon_draw_scale": 400,
        "moons": [
            {"enabled": True, "mass_lunar": 1.0, "a": 0.0015,
             "inc": 2.0, "phase": 0.0},
            {"enabled": False, "mass_lunar": 0.1, "a": 0.0009,
             "inc": 0.5, "phase": 90.0},
        ],
    },
    {
        "name": "Finsternis secular - safe margin",
        "notes": (
            "Same mechanism, backed off. Binary at 12 AU gives a 1.37x "
            "Holman-Wiegert margin instead of 1.14x, a longer eccentricity "
            "cycle and a lower peak e. Weaker seasons, more headroom."),
        "m_orange": 0.85, "m_wd": 0.6, "wd_age_gyr": 0.03,
        "a_wd": 12.0, "e_wd": 0.65, "i_wd": 0.0,
        "blue_mass_e": 1.0, "blue_a": 0.725, "blue_e": 0.0,
        "blue_inc": 0.0, "blue_f0": 0.0,
        "giant_enabled": False,
        "giant_mass_j": 1.0, "giant_a": 1.8, "giant_e": 0.05,
        "giant_inc": 2.0, "giant_f0": 180.0,
        "obliquity": 23.4, "spin_azimuth": 0.0,
        "moon_draw_scale": 400,
        "moons": [
            {"enabled": True, "mass_lunar": 1.0, "a": 0.0018,
             "inc": 2.0, "phase": 0.0},
            {"enabled": False, "mass_lunar": 0.1, "a": 0.0009,
             "inc": 0.5, "phase": 90.0},
        ],
    },
    {
        "name": "Dark Stars v0.2 - 990 yr binary",
        "notes": (
            "The original wide, inclined architecture. a_wd solved from the "
            "990 yr target: a = (P^2 M)^(1/3) = 112.4293 AU. KNOWN PROBLEM: "
            "at 75 deg the gas giant is itself Kozai-unstable on a ~2e4 yr "
            "timescale and nothing suppresses it. Once its eccentricity "
            "grows, its periastron crosses the blue planet and the planet is "
            "scattered. Kept for reference and comparison, not as a "
            "long-term-stable system."),
        "m_orange": 0.85, "m_wd": 0.6, "wd_age_gyr": 0.1,
        "a_wd": 112.4293, "e_wd": 0.875, "i_wd": 75.0,
        "blue_mass_e": 1.0, "blue_a": 0.725, "blue_e": 0.0,
        "blue_inc": 0.0, "blue_f0": 0.0,
        "giant_enabled": True,
        "giant_mass_j": 1.0, "giant_a": 1.8, "giant_e": 0.05,
        "giant_inc": 2.0, "giant_f0": 180.0,
        "obliquity": 23.4, "spin_azimuth": 0.0,
        "moon_draw_scale": 500,
        "moons": [
            {"enabled": True, "mass_lunar": 1.0, "a": 0.00257,
             "inc": 5.1, "phase": 0.0},
            {"enabled": False, "mass_lunar": 0.1, "a": 0.0009,
             "inc": 0.5, "phase": 90.0},
        ],
    },
]


def write_builtin_configs():
    """Create ./configs/ and drop in the shipped configurations if they are
    not already there. Never overwrites an existing file, so local edits
    survive an upgrade."""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
    except OSError:
        return
    for cfg in BUILTIN_CONFIGS:
        path = AnimatedOrbitalSimApp.config_path(cfg["name"])
        if not os.path.exists(path):
            try:
                with open(path, "w") as fh:
                    json.dump(cfg, fh, indent=2)
            except OSError:
                pass


class AnimatedOrbitalSimApp:
    """
    Hierarchical binary + S-type planetary system, restricted N-body.

    Physics model:
      - Binary (Orange dwarf + White dwarf) on Keplerian rails around the
        barycenter; a_wd is the RELATIVE semi-major axis of the pair.
      - Planets are integrated with leapfrog (KDK) in the barycentric
        inertial frame, pulled by both stars AND by each other. Planet
        masses are real, so a Jupiter-mass companion actually perturbs the
        terrestrial world; the planets do not feed back on the stellar rails.
      - View mode ("barycentric" / "orange") is a pure rendering transform.

    v4 additions over v3:

      WHEEL ZOOM - mouse wheel over the plot scales the view box. Bound
               directly to the Tk canvas widget (<MouseWheel> on Windows
               and macOS, <Button-4>/<Button-5> on X11), so it works
               without touching the matplotlib toolbar.

      GAS GIANT - second planet with its own mass, a, e, i and starting
               true anomaly. Fully integrated, mutually coupled to the
               terrestrial planet. Two readouts matter:
                 * mutual Hill separation between the two planets
                   (Delta = |a_g - a_b| / R_H,mutual; below ~3.5 the pair
                   is Hill-unstable, above ~10 it is comfortable)
                 * secular precession ratio. Both the WD and the giant
                   drive apsidal precession on the inner planet at
                   d(varpi)/dt = (3/4) n (m/M*) (a/a_pert)^3 (1-e^2)^-1.5.
                   When the giant wins, its precession detunes the
                   Kozai-Lidov resonance and the WD can no longer pump the
                   terrestrial planet's eccentricity. This is a real
                   mechanism and it is the cheapest way to make a wide,
                   inclined, eccentric companion survivable for life.

      MOONS  - up to two satellites of the terrestrial planet, on Keplerian
               rails relative to the planet (their orbital periods are ~1e4
               times shorter than the binary period, so integrating them
               directly would dominate the step budget for no gain). Each
               contributes a tide, and each is checked against the planet's
               instantaneous Hill radius using the Domingos (2006) prograde
               criterion a_crit = 0.4895 * r_H * (1 - 1.0305 e_p - 0.2738 e_m).
               Because r_H shrinks as the white dwarf closes in and e_p is
               pumped by Kozai, the margin is not constant. A moon can be
               stable for most of the cycle and stripped at periastron.

      AXIS TILT - planet obliquity and spin-axis azimuth. The spin axis is
               held fixed in the inertial frame (no precession torque model),
               but the ORBIT plane moves under Kozai-Lidov, so the effective
               obliquity measured against the instantaneous orbit normal
               drifts on its own. Readouts give sub-stellar latitude for
               both stars, the effective obliquity, and the polar circle
               latitude. The white dwarf's sub-stellar latitude is the
               interesting one: with a 75 degree binary inclination it can
               pass nearly over the pole.

    v6 additions over v5:

      WD PLANET - an optional Mars-class world (1-3 Mars masses intended)
               orbiting the WHITE DWARF, fully integrated in the N-body
               with the white dwarf as its host. Osculating elements,
               stability (Holman-Wiegert with the orange dwarf as the
               perturber, mu = 0.586), tides, UV, instellation and climate
               all mirror the blue planet's treatment, plus a cooling
               clock: the WD fades as t^-1.4, so the habitable band sweeps
               inward and the readout shows when the world entered the
               temperate band and when it freezes. Second-generation
               provenance (formed from post-AGB fallback debris) is the
               physically defensible origin for a small close-in WD
               planet; first-generation bodies this close were engulfed.
               Enabling it drops the global timestep to ~1/3 (the 81 day
               orbit is now the fastest clock), so fast-forward slows
               accordingly.

    v5 additions over v4:

      CONFIG FILES - every parameter lives in ./configs/*.json, selectable
               from the dropdown, saved with Save / Save As. The SCHEMA
               table drives both directions, so adding a field to the UI
               adds it to save/load automatically. Built-in configs are
               written on first run and never overwritten afterwards.

      ECC. PLOT - the strip under the 3D view traces the blue planet's
               osculating eccentricity. This is the headline diagnostic:
               with a close coplanar companion the planet's own eccentricity
               cycles slowly, and THAT is what moves tides, instellation and
               temperature together. Direct flux and tide from the companion
               are negligible at any separation that is dynamically stable.

      KOZAI WARNINGS - the metrics panel now flags the two failure modes
               that are invisible in a short run: inclination inside the
               39.23-140.77 deg Kozai band, and octupole forcing when
               eps_oct = (a_p/a_b) e_b/(1-e_b^2) exceeds ~0.01. It also
               warns that an enabled gas giant has NO protector of its own
               against Kozai - the terrestrial planet is far too light and
               GR precession is negligible - so in the Kozai band the giant
               is pumped, crosses the inner orbit and ejects the planet.

    v3 planet environment block, retained (fixed Earth-like planet:
    1 R_earth, Earth-strength magnetosphere, albedo 0.3):

      TIDES  - tidal acceleration gradient 2*G*m/d^3 from each body, in
               units of the Moon's tide on Earth.
      UV     - blackbody band flux 100-400 nm at the planet, in Earth UV
               units. Host T_eff from the main-sequence relation
               T = 5772*M^0.505; WD T_eff from its cooling luminosity and
               mass-radius relation R = 0.0127*(M/0.6)^(-1/3) R_sun.
      MAG    - magnetopause standoff distance from host wind ram pressure
               (P ~ 1/r^2, standoff ~ P^(-1/6), Earth = 10 R_E at 1 AU),
               classified QUIET/ELEVATED/ACTIVE/SEVERE, plus the WD's
               Bondi-Hoyle accretion X-ray luminosity.
      CLIMATE- bolometric instellation S from both stars in Earth units,
               equilibrium temperature T_eq = 278.5*(S*(1-A))^0.25 K, and a
               phase bin: RUNAWAY >= 1.06 / HOT >= 0.9 / TEMPERATE >= 0.42
               / COLD >= 0.32 / SNOWBALL below.
    """

    # Parameter schema. Each entry maps a config key to the UI widget that
    # holds it, so save/load stay in sync automatically when fields change.
    SCHEMA = [
        # (config key, attribute name of widget, kind)
        ("m_orange",     "m_orange_entry",   "f"),
        ("m_wd",         "m_wd_entry",       "f"),
        ("wd_age_gyr",   "age_entry",        "f"),
        ("a_wd",         "a_wd_entry",       "f"),
        ("e_wd",         "e_wd_entry",       "f"),
        ("i_wd",         "i_wd_entry",       "f"),
        ("blue_mass_e",  "m_blue_entry",     "f"),
        ("blue_a",       "a_blue_entry",     "f"),
        ("blue_e",       "e_blue_entry",     "f"),
        ("blue_inc",     "i_blue_entry",     "f"),
        ("blue_f0",      "f_blue_entry",     "f"),
        ("giant_mass_j", "m_giant_entry",    "f"),
        ("giant_a",      "a_giant_entry",    "f"),
        ("giant_e",      "e_giant_entry",    "f"),
        ("giant_inc",    "i_giant_entry",    "f"),
        ("giant_f0",     "f_giant_entry",    "f"),
        ("wdp_mass_mars", "m_wdp_entry",     "f"),
        ("wdp_a",        "a_wdp_entry",      "f"),
        ("wdp_e",        "e_wdp_entry",      "f"),
        ("wdp_inc",      "i_wdp_entry",      "f"),
        ("wdp_f0",       "f_wdp_entry",      "f"),
        ("obliquity",    "obliq_entry",      "f"),
        ("spin_azimuth", "spin_node_entry",  "f"),
        ("moon_draw_scale", "moon_vis_entry", "f"),
    ]

    def config_to_dict(self):
        """Snapshot every UI field into a plain dict, ready for JSON."""
        d = {"name": self.current_config_name,
             "notes": getattr(self, "current_config_notes", "")}
        for key, attr, _ in self.SCHEMA:
            d[key] = getattr(self, attr).get()
        d["giant_enabled"] = bool(self.giant_var.get())
        d["wdp_enabled"] = bool(self.wdp_var.get())
        d["moons"] = []
        for k in range(2):
            e = self.moon_entries[k]
            d["moons"].append({
                "enabled": bool(self.moon_vars[k].get()),
                "mass_lunar": e[0].get(), "a": e[1].get(),
                "inc": e[2].get(), "phase": e[3].get(),
            })
        return d

    def apply_config(self, d):
        """Push a config dict into the UI. Missing keys are left alone, so
        a partial or older config file still loads."""
        for key, attr, _ in self.SCHEMA:
            if key in d:
                w = getattr(self, attr)
                w.delete(0, tk.END)
                w.insert(0, str(d[key]))
        if "giant_enabled" in d:
            self.giant_var.set(bool(d["giant_enabled"]))
        # Configs that predate the WD planet mean "no WD planet", so the
        # flag defaults off rather than being left as-is.
        self.wdp_var.set(bool(d.get("wdp_enabled", False)))
        for k, m in enumerate(d.get("moons", [])[:2]):
            if "enabled" in m:
                self.moon_vars[k].set(bool(m["enabled"]))
            for c, key in enumerate(("mass_lunar", "a", "inc", "phase")):
                if key in m:
                    self.moon_entries[k][c].delete(0, tk.END)
                    self.moon_entries[k][c].insert(0, str(m[key]))
        self.current_config_name = d.get("name", "unnamed")
        self.current_config_notes = d.get("notes", "")

    # ------------------------------------------------------ Config files

    @staticmethod
    def sanitize(name):
        """Filename-safe config name that ROUND-TRIPS: sanitize(x) must equal
        sanitize(sanitize(x)), or a saved file cannot be loaded back. Dots
        are allowed (version numbers), but leading dots and path separators
        are not."""
        safe = "".join(c for c in name if c.isalnum() or c in " _-.")
        safe = safe.strip(" .")
        return safe or "config"

    @classmethod
    def config_path(cls, name):
        return os.path.join(CONFIG_DIR, cls.sanitize(name) + ".json")

    @staticmethod
    def list_configs():
        if not os.path.isdir(CONFIG_DIR):
            return []
        return sorted(f[:-5] for f in os.listdir(CONFIG_DIR)
                      if f.endswith(".json"))

    def refresh_config_list(self, select=None):
        names = self.list_configs()
        self.config_box["values"] = names
        if select and select in names:
            self.config_box.set(select)
        elif names and not self.config_box.get():
            self.config_box.set(names[0])

    def load_selected_config(self):
        name = self.config_box.get()
        if not name:
            return
        try:
            with open(self.config_path(name), "r") as fh:
                d = json.load(fh)
        except (OSError, ValueError) as e:
            messagebox.showerror("Config Error", f"Could not read {name}:\n{e}")
            return
        self.apply_config(d)
        self.update_parameters()

    def save_config(self, ask_name=False):
        name = self.current_config_name
        if ask_name or not name or name == "unnamed":
            name = simpledialog.askstring("Save configuration",
                                          "Configuration name:",
                                          initialvalue=name or "my config",
                                          parent=self.root)
            if not name:
                return
        self.current_config_name = name
        d = self.config_to_dict()
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(self.config_path(name), "w") as fh:
                json.dump(d, fh, indent=2)
        except OSError as e:
            messagebox.showerror("Config Error", f"Could not save:\n{e}")
            return
        self.refresh_config_list(select=name)

    def delete_selected_config(self):
        name = self.config_box.get()
        if not name:
            return
        if not messagebox.askyesno("Delete configuration",
                                   f"Delete '{name}' permanently?"):
            return
        try:
            os.remove(self.config_path(name))
        except OSError as e:
            messagebox.showerror("Config Error", f"Could not delete:\n{e}")
            return
        self.config_box.set("")
        self.refresh_config_list()

    def __init__(self, root):
        self.root = root
        self.root.title("Hierarchical Binary Orbital Simulator - v6")
        self.root.geometry("1340x1000+20+0")
        self.root.configure(bg="#0d1117")

        self.is_running = True
        self.time_step = 0.0          # simulation time, years
        self.animation_id = None
        self.ff_in_progress = False

        self.view_mode = "barycentric"
        self.zoom_factor = 0.15
        self.current_config_name = "unnamed"
        self.current_config_notes = ""
        self.e_hist = []              # (time_yr, e_blue) for the cycle plot
        self.e_sample_every = 0.0     # set from the secular period
        self.next_e_sample = 0.0
        write_builtin_configs()

        # Dark theme
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure(".", background="#0d1117", foreground="white",
                             fieldbackground="#161b22")
        self.style.configure("TLabel", background="#0d1117",
                             foreground="#c9d1d9", font=("Arial", 9))
        self.style.configure("TButton", background="#21262d",
                             foreground="white", font=("Arial", 9, "bold"))
        self.style.map("TButton", background=[("active", "#30363d")])
        self.style.configure("TNotebook", background="#0d1117",
                             borderwidth=0)
        self.style.configure("TNotebook.Tab", background="#161b22",
                             foreground="#c9d1d9", padding=(8, 3),
                             font=("Arial", 9))
        self.style.map("TNotebook.Tab",
                       background=[("selected", "#21262d")],
                       foreground=[("selected", "#58a6ff")])
        self.style.configure("TCheckbutton", background="#0d1117",
                             foreground="#c9d1d9", font=("Arial", 9))
        self.style.map("TCheckbutton", background=[("active", "#0d1117")])

        self.left_frame = ttk.Frame(root, padding=0, width=350)
        self.left_frame.pack(side=tk.LEFT, fill=tk.Y)
        self.left_frame.pack_propagate(False)

        self.right_frame = ttk.Frame(root, padding=1)
        self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.setup_inputs()
        self.setup_plot()

        self.refresh_config_list(select=DEFAULT_CONFIG)
        if self.config_box.get():
            self.load_selected_config()
        else:
            self.update_parameters()
        self.animate_loop()

    # ------------------------------------------------------------------ UI

    def setup_inputs(self):
        self.year_label = ttk.Label(
            self.left_frame,
            text="Simulation Years : 0",
            font=("Consolas", 8, "bold"),
            foreground="#58a6ff",
            justify=tk.LEFT
        )
        self.year_label.pack(fill=tk.X, pady=(4, 4))

        nb = ttk.Notebook(self.left_frame)
        nb.pack(fill=tk.X, pady=(0, 4))

        tab_stars = ttk.Frame(nb, padding=4)
        tab_planets = ttk.Frame(nb, padding=4)
        tab_moons = ttk.Frame(nb, padding=4)
        nb.add(tab_stars, text="Stars")
        nb.add(tab_planets, text="Planets")
        nb.add(tab_moons, text="Moons + Tilt")

        def grid_entry(parent, row, col, label, default, width=9):
            ttk.Label(parent, text=label).grid(row=row, column=col * 2,
                                               sticky="w", padx=(0, 3),
                                               pady=1)
            e = ttk.Entry(parent, width=width)
            e.insert(0, str(default))
            e.grid(row=row, column=col * 2 + 1, sticky="w", pady=1)
            return e

        # ---- Stars tab ----
        self.m_orange_entry = grid_entry(tab_stars, 0, 0,
                                         "Orange M(sun):", 0.85)
        self.m_wd_entry = grid_entry(tab_stars, 1, 0, "WD M(sun):", 0.6)
        self.age_entry = grid_entry(tab_stars, 2, 0, "WD age (Gyr):", 0.1)
        self.a_wd_entry = grid_entry(tab_stars, 3, 0, "WD a (AU):", 16)
        self.e_wd_entry = grid_entry(tab_stars, 4, 0, "WD e:", 0.7)
        self.i_wd_entry = grid_entry(tab_stars, 5, 0, "WD incl (deg):", 75)

        # ---- Planets tab ----
        ttk.Label(tab_planets, text="Blue planet",
                  foreground="#58a6ff",
                  font=("Arial", 9, "bold")).grid(row=0, column=0,
                                                  columnspan=4, sticky="w")
        self.m_blue_entry = grid_entry(tab_planets, 1, 0, "mass (M_E):", 1.0)
        self.a_blue_entry = grid_entry(tab_planets, 1, 1, "a (AU):", 0.55)
        self.e_blue_entry = grid_entry(tab_planets, 2, 0, "e:", 0.0)
        self.i_blue_entry = grid_entry(tab_planets, 2, 1, "incl (deg):", 0.0)
        self.f_blue_entry = grid_entry(tab_planets, 3, 0,
                                       "start f (deg):", 0.0)

        ttk.Separator(tab_planets, orient="horizontal").grid(
            row=4, column=0, columnspan=4, sticky="ew", pady=5)

        self.giant_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab_planets, text="Gas giant",
                        variable=self.giant_var).grid(row=5, column=0,
                                                      columnspan=4,
                                                      sticky="w")
        self.m_giant_entry = grid_entry(tab_planets, 6, 0,
                                        "mass (M_J):", 1.0)
        self.a_giant_entry = grid_entry(tab_planets, 6, 1, "a (AU):", 2.2)
        self.e_giant_entry = grid_entry(tab_planets, 7, 0, "e:", 0.05)
        self.i_giant_entry = grid_entry(tab_planets, 7, 1,
                                        "incl (deg):", 2.0)
        self.f_giant_entry = grid_entry(tab_planets, 8, 0,
                                        "start f (deg):", 180.0)

        ttk.Separator(tab_planets, orient="horizontal").grid(
            row=9, column=0, columnspan=4, sticky="ew", pady=5)

        self.wdp_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab_planets, text="WD planet (Mars-class)",
                        variable=self.wdp_var).grid(row=10, column=0,
                                                    columnspan=4, sticky="w")
        self.m_wdp_entry = grid_entry(tab_planets, 11, 0,
                                      "mass (M_Mars):", 2.0)
        self.a_wdp_entry = grid_entry(tab_planets, 11, 1, "a (AU):", 0.31)
        self.e_wdp_entry = grid_entry(tab_planets, 12, 0, "e:", 0.02)
        self.i_wdp_entry = grid_entry(tab_planets, 12, 1, "incl (deg):", 0.5)
        self.f_wdp_entry = grid_entry(tab_planets, 13, 0,
                                      "start f (deg):", 90.0)

        # ---- Moons + tilt tab ----
        ttk.Label(tab_moons, text="Blue planet spin axis",
                  foreground="#58a6ff",
                  font=("Arial", 9, "bold")).grid(row=0, column=0,
                                                  columnspan=4, sticky="w")
        self.obliq_entry = grid_entry(tab_moons, 1, 0,
                                      "obliquity (deg):", 23.4)
        self.spin_node_entry = grid_entry(tab_moons, 1, 1,
                                          "azimuth (deg):", 0.0)

        ttk.Separator(tab_moons, orient="horizontal").grid(
            row=2, column=0, columnspan=4, sticky="ew", pady=5)

        ttk.Label(tab_moons, text="Moons (rails, prograde)",
                  foreground="#58a6ff",
                  font=("Arial", 9, "bold")).grid(row=3, column=0,
                                                  columnspan=4, sticky="w")

        hdr = ["on", "mass(M_m)", "a (AU)", "inc", "phase"]
        for c, h in enumerate(hdr):
            ttk.Label(tab_moons, text=h).grid(row=4, column=c, sticky="w",
                                              padx=1)

        self.moon_vars = []
        self.moon_entries = []
        moon_defaults = [
            (True, 1.0, 0.00257, 5.1, 0.0),
            (False, 0.1, 0.00090, 0.5, 90.0),
        ]
        for k, (on, m, a, inc, ph) in enumerate(moon_defaults):
            var = tk.BooleanVar(value=on)
            ttk.Checkbutton(tab_moons, variable=var).grid(row=5 + k,
                                                          column=0,
                                                          sticky="w")
            row_entries = []
            for c, val in enumerate((m, a, inc, ph)):
                e = ttk.Entry(tab_moons, width=8)
                e.insert(0, str(val))
                e.grid(row=5 + k, column=c + 1, sticky="w", padx=1, pady=1)
                row_entries.append(e)
            self.moon_vars.append(var)
            self.moon_entries.append(row_entries)

        ttk.Label(tab_moons, text="Moon draw scale (x):").grid(
            row=8, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.moon_vis_entry = ttk.Entry(tab_moons, width=8)
        self.moon_vis_entry.insert(0, "500")
        self.moon_vis_entry.grid(row=8, column=2, sticky="w", pady=(6, 0))

        # ---- Apply + configuration files ----
        btn_row = ttk.Frame(self.left_frame)
        btn_row.pack(fill=tk.X, pady=(4, 2))
        ttk.Button(btn_row, text="Apply Changes",
                   command=self.update_parameters).pack(
            side=tk.LEFT, expand=True, fill=tk.X, padx=1)

        cfg_row = ttk.Frame(self.left_frame)
        cfg_row.pack(fill=tk.X, pady=(2, 2))
        ttk.Label(cfg_row, text="Config:").pack(side=tk.LEFT, padx=(0, 3))
        self.config_box = ttk.Combobox(cfg_row, state="readonly", width=26)
        self.config_box.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.config_box.bind("<<ComboboxSelected>>",
                             lambda e: self.load_selected_config())

        cfg_row2 = ttk.Frame(self.left_frame)
        cfg_row2.pack(fill=tk.X, pady=(0, 4))
        for txt, cmd in (("Load", self.load_selected_config),
                         ("Save", lambda: self.save_config(False)),
                         ("Save As", lambda: self.save_config(True)),
                         ("Delete", self.delete_selected_config)):
            ttk.Button(cfg_row2, text=txt, command=cmd).pack(
                side=tk.LEFT, expand=True, fill=tk.X, padx=1)

        env_nb = ttk.Notebook(self.left_frame)
        env_nb.pack(fill=tk.X, pady=(0, 4))
        tab_blue_env = ttk.Frame(env_nb)
        tab_wdp_env = ttk.Frame(env_nb)
        env_nb.add(tab_blue_env, text="Blue Environment")
        env_nb.add(tab_wdp_env, text="WD Planet")

        def make_env_text(parent):
            w = tk.Text(parent, height=21, bg="#161b22", fg="#c9d1d9",
                        font=("Consolas", 8), bd=0)
            w.pack(fill=tk.BOTH, expand=True)
            for tag, col in (("quiet", "#3fb950"), ("elevated", "#d29922"),
                             ("active", "#f97316"), ("severe", "#f85149"),
                             ("head", "#8b949e")):
                w.tag_configure(tag, foreground=col)
            return w

        self.env_text = make_env_text(tab_blue_env)
        self.env_text_wdp = make_env_text(tab_wdp_env)

        ttk.Label(self.left_frame, text="Calculated Metrics",
                  font=("Arial", 10, "bold"),
                  foreground="#58a6ff").pack(anchor="w")

        self.output_text = tk.Text(self.left_frame, height=18, bg="#161b22",
                                   fg="#c9d1d9", font=("Consolas", 8), bd=0)
        self.output_text.pack(fill=tk.BOTH, expand=True)
        self.output_text.tag_configure("quiet", foreground="#3fb950")
        self.output_text.tag_configure("elevated", foreground="#d29922")
        self.output_text.tag_configure("severe", foreground="#f85149")
        self.output_text.tag_configure("head", foreground="#8b949e")

    def setup_plot(self):
        self.control_frame = ttk.Frame(self.right_frame)
        self.control_frame.pack(fill=tk.X, padx=4, pady=4)

        self.row1 = ttk.Frame(self.control_frame)
        self.row1.pack(fill=tk.X)
        self.row2 = ttk.Frame(self.control_frame)
        self.row2.pack(fill=tk.X, pady=(3, 0))

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

        ttk.Button(self.row2, text="Fit",
                   command=self.reset_zoom).pack(side=tk.LEFT, padx=2)

        ttk.Label(self.row2, text="Warp:").pack(side=tk.LEFT, padx=(10, 2))

        self.speed_slider = tk.Scale(self.row2, from_=1, to=20,
                                     orient=tk.HORIZONTAL, bg="#161b22",
                                     fg="white", highlightthickness=0,
                                     length=160)
        self.speed_slider.set(1)
        self.speed_slider.pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(self.row2, text="FF:").pack(side=tk.LEFT, padx=(5, 2))

        self.ff_years_entry = ttk.Entry(self.row2, width=7)
        self.ff_years_entry.insert(0, "1.0")
        self.ff_years_entry.pack(side=tk.LEFT)

        self.ff_unit_box = ttk.Combobox(
            self.row2, state="readonly", width=13,
            values=("ecc. cycles", "WD orbits", "years", "planet years"))
        self.ff_unit_box.set("ecc. cycles")
        self.ff_unit_box.pack(side=tk.LEFT, padx=(3, 0))

        # 3D orbit view on top, eccentricity history strip underneath.
        self.fig = plt.figure(figsize=(8, 9), facecolor="#0d1117")
        gs = GridSpec(2, 1, height_ratios=[4.2, 1.0], figure=self.fig,
                      hspace=0.22, left=0.04, right=0.97,
                      top=0.99, bottom=0.09)
        self.ax = self.fig.add_subplot(gs[0], projection="3d")
        self.ax.set_facecolor("#0d1117")
        self.ax_e = self.fig.add_subplot(gs[1])
        self.setup_e_axes()

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.right_frame)
        widget = self.canvas.get_tk_widget()
        widget.pack(fill=tk.BOTH, expand=True)

        # ---- Mouse wheel zoom ----
        # Bound straight to the canvas widget rather than through
        # matplotlib's scroll_event, so behaviour is identical on all three
        # platforms. Windows and macOS deliver <MouseWheel> with a signed
        # delta; X11 delivers Button-4 (up) and Button-5 (down).
        widget.bind("<MouseWheel>", self._on_wheel)
        widget.bind("<Button-4>", self._on_wheel)
        widget.bind("<Button-5>", self._on_wheel)
        # Windows routes MouseWheel to the focused widget, so grab focus
        # whenever the pointer is over the plot.
        widget.bind("<Enter>", lambda e: widget.focus_set())

    def _on_wheel(self, event):
        if getattr(event, "num", None) == 4:
            step = 1
        elif getattr(event, "num", None) == 5:
            step = -1
        else:
            delta = getattr(event, "delta", 0)
            if delta == 0:
                return "break"
            step = 1 if delta > 0 else -1
        self.change_zoom(0.88 ** step)
        return "break"

    def change_zoom(self, factor):
        self.zoom_factor = float(np.clip(self.zoom_factor * factor,
                                         2e-4, 4.0))
        self.update_axes_limits()
        self.update_stats_label()
        self.canvas.draw_idle()

    def reset_zoom(self):
        self.zoom_factor = 1.0
        self.update_axes_limits()
        self.update_stats_label()
        self.canvas.draw_idle()

    def update_axes_limits(self):
        if not hasattr(self, "a_wd"):
            return
        max_range = self.a_wd * (1 + self.e_wd) * self.zoom_factor
        self.ax.set_xlim(-max_range, max_range)
        self.ax.set_ylim(-max_range, max_range)
        self.ax.set_zlim(-max_range, max_range)
        try:
            self.ax.set_box_aspect((1, 1, 1))
        except AttributeError:
            pass

    def view_halfwidth(self):
        return self.a_wd * (1 + self.e_wd) * self.zoom_factor

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
        return np.array([(p2[i] - p1[i]) / (2 * h),
                         (p2[i + 1] - p1[i + 1]) / (2 * h),
                         (p2[i + 2] - p1[i + 2]) / (2 * h)])

    def accelerations(self, pos, stars):
        """Gravity from both stars plus mutual planet-planet forces.
        Written with scalars because the arrays are tiny and numpy's
        per-call overhead dominates in the integration loop."""
        ox, oy, oz, wx, wy, wz = stars
        n = self.n_planets
        acc = np.zeros((n, 3))

        gm_o = G_SIM * self.m_orange
        gm_w = G_SIM * self.m_wd

        for i in range(n):
            x, y, z = pos[i, 0], pos[i, 1], pos[i, 2]

            dx, dy, dz = x - ox, y - oy, z - oz
            r3 = (dx * dx + dy * dy + dz * dz) ** 1.5
            axi = -gm_o * dx / r3
            ayi = -gm_o * dy / r3
            azi = -gm_o * dz / r3

            dx, dy, dz = x - wx, y - wy, z - wz
            r3 = (dx * dx + dy * dy + dz * dz) ** 1.5
            axi -= gm_w * dx / r3
            ayi -= gm_w * dy / r3
            azi -= gm_w * dz / r3

            acc[i, 0] = axi
            acc[i, 1] = ayi
            acc[i, 2] = azi

        for i in range(n):
            for j in range(i + 1, n):
                dx = pos[i, 0] - pos[j, 0]
                dy = pos[i, 1] - pos[j, 1]
                dz = pos[i, 2] - pos[j, 2]
                r3 = (dx * dx + dy * dy + dz * dz) ** 1.5
                gi = G_SIM * self.p_mass[i] / r3
                gj = G_SIM * self.p_mass[j] / r3
                acc[i, 0] -= gj * dx
                acc[i, 1] -= gj * dy
                acc[i, 2] -= gj * dz
                acc[j, 0] += gi * dx
                acc[j, 1] += gi * dy
                acc[j, 2] += gi * dz

        return acc

    def integrate_step(self, t, dt):
        """Leapfrog KDK; kicks use star positions at t and t+dt."""
        stars0 = self.binary_positions(t)
        a0 = self.accelerations(self.p_pos, stars0)
        self.p_vel += 0.5 * a0 * dt
        self.p_pos += self.p_vel * dt
        stars1 = self.binary_positions(t + dt)
        a1 = self.accelerations(self.p_pos, stars1)
        self.p_vel += 0.5 * a1 * dt

    def advance(self, span_years, dt=None):
        """Advance by span_years at fixed dt; warp never changes step size
        during playback. Fast-forward uses a coarser dt (see fast_forward)."""
        step = self.dt if dt is None else dt
        n = max(1, int(round(abs(span_years) / step)))
        h = span_years / n
        for _ in range(n):
            self.integrate_step(self.time_step, h)
            self.time_step += h

    def osculating_elements(self, idx=0):
        """Planet idx's instantaneous Keplerian elements relative to its
        HOST star (orange dwarf for the inner system, white dwarf for a WD
        planet); constant for two bodies, so drift = perturbation.
        Returns (a, e, i_deg, r, h_unit)."""
        stars = self.binary_positions(self.time_step)
        host = self.p_host[idx] if hasattr(self, "p_host") else "orange"
        if host == "wd":
            r_star = np.array(stars[3:6])
            v_star = self.binary_velocity(self.time_step, "wd")
            m_host = self.m_wd
        else:
            r_star = np.array(stars[0:3])
            v_star = self.binary_velocity(self.time_step, "orange")
            m_host = self.m_orange

        r = self.p_pos[idx] - r_star
        v = self.p_vel[idx] - v_star

        mu = G_SIM * (m_host + self.p_mass[idx])
        rn = np.linalg.norm(r)
        energy = 0.5 * np.dot(v, v) - mu / rn
        a_osc = -mu / (2.0 * energy) if energy < 0 else float("inf")

        h = np.cross(r, v)
        hn = np.linalg.norm(h)
        e_vec = np.cross(v, h) / mu - r / rn
        e_osc = np.linalg.norm(e_vec)
        h_hat = h / hn if hn > 0 else np.array([0.0, 0.0, 1.0])
        i_osc = np.degrees(np.arccos(np.clip(h_hat[2], -1.0, 1.0)))

        return a_osc, e_osc, i_osc, rn, h_hat

    def binary_separation(self):
        s = self.binary_positions(self.time_step)
        return np.sqrt((s[3] - s[0]) ** 2 + (s[4] - s[1]) ** 2 +
                       (s[5] - s[2]) ** 2)

    # -------------------------------------------------- Spin axis + moons

    def spin_axis(self):
        """Unit vector of the blue planet's north pole, fixed in the
        inertial frame. Obliquity is measured from +z (the planet's initial
        orbit plane); azimuth rotates the tilt direction about +z."""
        eps = np.radians(self.obliquity_deg)
        om = np.radians(self.spin_node_deg)
        return np.array([np.sin(om) * np.sin(eps),
                         -np.cos(om) * np.sin(eps),
                         np.cos(eps)])

    def equatorial_basis(self):
        """Orthonormal triad (e1, e2, n) with e1 along the equator's node
        and n the spin axis."""
        om = np.radians(self.spin_node_deg)
        e1 = np.array([np.cos(om), np.sin(om), 0.0])
        n = self.spin_axis()
        e2 = np.cross(n, e1)
        return e1, e2, n

    def moon_offset(self, k, t):
        """Moon k's position relative to the blue planet's centre.
        Circular Keplerian rail in a plane inclined by i_m to the planet's
        equator, node along e1."""
        m = self.moons[k]
        e1, e2, n = self.equatorial_basis()
        im = np.radians(m["inc"])
        theta = 2.0 * np.pi * t / m["period"] + np.radians(m["phase"])
        u = np.cos(im) * e2 + np.sin(im) * n
        return m["a"] * (np.cos(theta) * e1 + np.sin(theta) * u)

    # ------------------------------------------------- Planet environment

    def compute_environment(self):
        """All indicators, strictly physical, for the current state."""
        stars = self.binary_positions(self.time_step)
        r_orange = np.array(stars[0:3])
        r_wd = np.array(stars[3:6])
        p = self.p_pos[0]

        d_o = p - r_orange
        d_w = p - r_wd
        r_o = np.linalg.norm(d_o)
        r_w = np.linalg.norm(d_w)
        sep = np.linalg.norm(r_wd - r_orange)

        a_osc, e_osc, i_osc, _, h_hat = self.osculating_elements(0)

        # ---- 1. Tidal forcing (units: lunar tide on Earth) ----
        tide_host = 2.0 * G_SIM * self.m_orange / r_o ** 3 / TIDE_MOON
        tide_wd = 2.0 * G_SIM * self.m_wd / r_w ** 3 / TIDE_MOON

        tide_moons = []
        for k, m in enumerate(self.moons):
            if m["on"]:
                tide_moons.append(2.0 * G_SIM * m["mass"]
                                  / m["a"] ** 3 / TIDE_MOON)
            else:
                tide_moons.append(0.0)

        tide_giant = 0.0
        if self.idx_giant is not None:
            d_g = np.linalg.norm(self.p_pos[self.idx_giant] - p)
            tide_giant = (2.0 * G_SIM * self.p_mass[self.idx_giant]
                          / d_g ** 3 / TIDE_MOON)

        # Spring/neap envelope from the two moons plus the stars
        stellar_tide = tide_host + tide_wd
        t1, t2 = tide_moons[0], tide_moons[1]
        tide_max = stellar_tide + t1 + t2
        tide_min = abs(stellar_tide - (t1 + t2))

        # ---- 2. UV flux (Earth UV units; band 100-400 nm) ----
        uv_host = self.uv_lum_host / r_o ** 2
        uv_wd = self.uv_lum_wd / r_w ** 2
        uv_total = uv_host + uv_wd
        uv_wd_share = uv_wd / uv_total * 100 if uv_total > 0 else 0

        # ---- 3. Magnetic storm indicator ----
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

        v_orb2 = G_SIM * (self.m_orange + self.m_wd) * (2.0 / sep
                                                        - 1.0 / self.a_wd)
        v_rel2 = V_WIND_AU_YR ** 2 + v_orb2
        f_capture = (G_SIM * self.m_wd / (sep * v_rel2)) ** 2
        mdot_acc = MDOT_WIND * f_capture
        l_acc = (G_SIM * self.m_wd * mdot_acc
                 / self.r_wd_au * LUM_UNIT_LSUN)

        # ---- 4. Climate phase ----
        s_now = self.L_orange / r_o ** 2 + self.L_wd / r_w ** 2
        e_c = min(e_osc, 0.99)
        s_avg = (self.L_orange / (a_osc ** 2 * np.sqrt(1.0 - e_c ** 2))
                 if np.isfinite(a_osc) else s_now)
        t_eq = 278.5 * (s_now * 0.7) ** 0.25

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

        # ---- 5. Seasons from the spin axis ----
        n_spin = self.spin_axis()
        lat_host = np.degrees(np.arcsin(np.clip(
            np.dot(-d_o / r_o, n_spin), -1.0, 1.0)))
        lat_wd = np.degrees(np.arcsin(np.clip(
            np.dot(-d_w / r_w, n_spin), -1.0, 1.0)))
        eps_raw = np.degrees(np.arccos(np.clip(
            np.dot(n_spin, h_hat), -1.0, 1.0)))
        # Above 90 deg the planet spins retrograde. Seasonal amplitude is set
        # by the supplement, but the spin sense is not the same thing, so
        # report both rather than folding one into the other.
        retro = eps_raw > 90.0
        eps_eff = 180.0 - eps_raw if retro else eps_raw
        polar_circle = 90.0 - eps_eff

        # ---- 6. Moon stability against the shrinking Hill radius ----
        m_p = self.p_mass[0]
        rh_host = r_o * (m_p / (3.0 * self.m_orange)) ** (1.0 / 3.0)
        rh_wd = r_w * (m_p / (3.0 * self.m_wd)) ** (1.0 / 3.0)
        rh = min(rh_host, rh_wd)
        a_crit_sat = SAT_STABILITY_C * rh * max(
            0.0, 1.0 - 1.0305 * min(e_osc, 0.9))

        moon_info = []
        for k, m in enumerate(self.moons):
            if not m["on"]:
                moon_info.append(None)
                continue
            ratio = m["a"] / a_crit_sat if a_crit_sat > 0 else 99.0
            if ratio < 0.7:
                st, tg = "STABLE", "quiet"
            elif ratio < 1.0:
                st, tg = "MARGINAL", "elevated"
            else:
                st, tg = "STRIPPED", "severe"

            off = self.moon_offset(k, self.time_step)
            cos_a = np.dot(off / np.linalg.norm(off), -d_o / r_o)
            illum = (1.0 - cos_a) / 2.0
            moon_info.append({
                "ratio": ratio, "status": st, "tag": tg,
                "period_d": m["period"] * 365.25,
                "tide": tide_moons[k], "illum": illum * 100.0,
            })

        return {
            "tide_host": tide_host, "tide_wd": tide_wd,
            "tide_giant": tide_giant,
            "tide_max": tide_max, "tide_min": tide_min,
            "uv_total": uv_total, "uv_wd_share": uv_wd_share,
            "standoff": standoff, "mag_status": mag_status,
            "mag_tag": mag_tag, "l_acc": l_acc,
            "s_now": s_now, "s_avg": s_avg, "t_eq": t_eq,
            "cli_status": cli_status, "cli_tag": cli_tag,
            "lat_host": lat_host, "lat_wd": lat_wd,
            "eps_eff": eps_eff, "eps_raw": eps_raw, "retro": retro,
            "polar_circle": polar_circle,
            "rh": rh, "a_crit_sat": a_crit_sat, "moons": moon_info,
            "e_osc": e_osc, "i_osc": i_osc, "a_osc": a_osc,
        }

    def update_env_display(self):
        env = self.compute_environment()
        t = self.env_text
        t.delete("1.0", tk.END)

        t.insert(tk.END, "-- TIDES (lunar units) --\n", "head")
        t.insert(tk.END, f"Host        : {env['tide_host']:.4f}\n")
        t.insert(tk.END, f"White dwarf : {env['tide_wd']:.3e}\n")
        for k, mi in enumerate(env["moons"]):
            if mi:
                t.insert(tk.END, f"Moon {k + 1}      : {mi['tide']:.4f}"
                                 f"  ({mi['illum']:.0f}% lit)\n")
        if self.idx_giant is not None:
            t.insert(tk.END, f"Gas giant   : {env['tide_giant']:.3e}\n")
        t.insert(tk.END, f"Range       : {env['tide_min']:.3f}"
                         f" - {env['tide_max']:.3f}\n")

        t.insert(tk.END, "-- RADIATION --\n", "head")
        t.insert(tk.END, f"UV flux     : {env['uv_total']:.4f} x Earth\n")
        t.insert(tk.END, f"  WD share  : {env['uv_wd_share']:.3f} %\n")
        t.insert(tk.END, f"Magnetopause: {env['standoff']:.1f} R_E\n")
        t.insert(tk.END, "Storm level : ")
        t.insert(tk.END, env["mag_status"] + "\n", env["mag_tag"])
        t.insert(tk.END, f"WD accr. Lx : {env['l_acc']:.2e} L(sun)\n")

        t.insert(tk.END, "-- CLIMATE --\n", "head")
        t.insert(tk.END, f"Instellation: {env['s_now']:.4f} S_E\n")
        t.insert(tk.END, f"  orbit avg : {env['s_avg']:.4f} S_E\n")
        t.insert(tk.END, f"T_eq (A=0.3): {env['t_eq']:.1f} K\n")
        t.insert(tk.END, "Climate     : ")
        t.insert(tk.END, env["cli_status"] + "\n", env["cli_tag"])

        t.insert(tk.END, "-- SEASONS --\n", "head")
        t.insert(tk.END, f"Obliquity   : {self.obliquity_deg:.1f} deg"
                         f"  (eff {env['eps_eff']:.2f}"
                         f"{' RETRO' if env['retro'] else ''})\n")
        t.insert(tk.END, f"Sub-host lat: {env['lat_host']:+.2f} deg\n")
        t.insert(tk.END, f"Sub-WD lat  : {env['lat_wd']:+.2f} deg\n")
        t.insert(tk.END, f"Polar circle: {env['polar_circle']:.1f} deg\n")

        self.last_env = env

    def update_wdp_env_display(self):
        """Environment of the WD planet, mirroring the blue planet's block
        where the physics carries over and replacing it where it does not.
        A Mars-class world close to a hot young white dwarf lives on a
        cooling clock: the habitable band sweeps inward as the WD fades, so
        the climate story is WHEN, not just where."""
        t = self.env_text_wdp
        t.delete("1.0", tk.END)
        if not self.wdp_on:
            t.insert(tk.END, "WD planet disabled.\n\nEnable it on the "
                             "Planets tab and press Apply Changes.")
            return

        stars = self.binary_positions(self.time_step)
        p = self.p_pos[self.idx_wdp]
        r_w = np.linalg.norm(p - np.array(stars[3:6]))
        r_o = np.linalg.norm(p - np.array(stars[0:3]))

        m_e = self.p_mass[self.idx_wdp] / M_EARTH_MSUN
        m_mars = self.p_mass[self.idx_wdp] / M_MARS_MSUN
        r_pl = m_e ** 0.27                 # rocky mass-radius relation
        g_pl = m_e / r_pl ** 2

        tide_wd = 2.0 * G_SIM * self.m_wd / r_w ** 3 / TIDE_MOON
        tide_o = 2.0 * G_SIM * self.m_orange / r_o ** 3 / TIDE_MOON

        uv_wd = self.uv_lum_wd / r_w ** 2
        uv_o = self.uv_lum_host / r_o ** 2
        uv = uv_wd + uv_o
        share = uv_wd / uv * 100 if uv > 0 else 0

        s_wd = self.L_wd / r_w ** 2
        s_o = self.L_orange / r_o ** 2
        s_now = s_wd + s_o
        t_eq = 278.5 * (s_now * 0.7) ** 0.25
        if s_now >= 1.06:
            cli, tag = "RUNAWAY", "severe"
        elif s_now >= 0.90:
            cli, tag = "HOT", "active"
        elif s_now >= 0.42:
            cli, tag = "TEMPERATE", "quiet"
        elif s_now >= 0.32:
            cli, tag = "COLD", "elevated"
        else:
            cli, tag = "SNOWBALL", "severe"

        r_o_min = max(self.a_wd * (1 - self.e_wd)
                      - self.a_wdp * (1 + self.e_wdp), 1e-6)
        pulse = (self.L_orange / r_o_min ** 2) / max(s_wd, 1e-12) * 100.0

        def age_at(S_target):
            L_need = S_target * self.a_wdp ** 2
            return (1e-3 * self.m_wd / L_need) ** (1.0 / 1.4)
        a_temp = age_at(0.90)
        a_cold = age_at(0.42)
        now = self.wd_age_gyr

        a_osc, e_osc, i_osc, _, _ = self.osculating_elements(self.idx_wdp)
        e_forced = (1.25 * (self.a_wdp / self.a_wd) * self.e_wd
                    / (1 - self.e_wd ** 2))

        mu_o = self.m_orange / (self.m_orange + self.m_wd)
        a_crit = self.a_wd * (
            0.464 - 0.380 * mu_o - 0.631 * self.e_wd
            + 0.586 * mu_o * self.e_wd + 0.150 * self.e_wd ** 2
            - 0.198 * mu_o * self.e_wd ** 2)

        t.insert(tk.END, f"-- WD PLANET ({m_mars:.1f} M_Mars) --\n", "head")
        t.insert(tk.END, f"Year        : {self.period_wdp_yr * 365.25:.1f} d"
                         f"   a={self.a_wdp:.3f} AU\n")
        t.insert(tk.END, f"R ~ {r_pl:.2f} R_E   g ~ {g_pl:.2f} g\n")
        t.insert(tk.END, f"Dist to WD  : {r_w:.4f} AU\n")
        t.insert(tk.END, "-- TIDES (lunar units) --\n", "head")
        t.insert(tk.END, f"White dwarf : {tide_wd:.2f}\n")
        t.insert(tk.END, f"Orange star : {tide_o:.4f}\n")
        t.insert(tk.END, "-- RADIATION --\n", "head")
        t.insert(tk.END, f"UV flux     : {uv:.2f} x Earth"
                         f"  (WD {share:.1f}%)\n")
        t.insert(tk.END, "  low g + hot WD: strong escape\n", "head")
        t.insert(tk.END, "-- CLIMATE --\n", "head")
        t.insert(tk.END, f"Instellation: {s_now:.4f} S_E\n")
        t.insert(tk.END, f"  WD {s_wd:.4f} / host {s_o:.4f}\n")
        t.insert(tk.END, f"T_eq (A=0.3): {t_eq:.1f} K\n")
        t.insert(tk.END, "Climate     : ")
        t.insert(tk.END, cli + "\n", tag)
        t.insert(tk.END, f"Host pulse  : +{pulse:.1f}% S at binary peri\n")
        t.insert(tk.END, "-- COOLING CLOCK --\n", "head")
        t.insert(tk.END, f"TEMPERATE from age {a_temp * 1000:.1f} Myr\n")
        t.insert(tk.END, f"frozen (S<0.42) at {a_cold * 1000:.1f} Myr\n")
        left = (a_cold - now) * 1000
        t.insert(tk.END, f"now {now * 1000:.0f} Myr -> ")
        if left > 0:
            t.insert(tk.END, f"{left:.1f} Myr of warmth left\n",
                     "quiet" if left > 5 else "elevated")
        else:
            t.insert(tk.END, "already frozen\n", "severe")
        t.insert(tk.END, "-- DYNAMICS --\n", "head")
        t.insert(tk.END, f"osc a/e     : {a_osc:.4f} / {e_osc:.4f}\n")
        t.insert(tk.END, f"forced e    : ~{e_forced:.3f} (linear)\n")
        t.insert(tk.END, f"S-type limit: {a_crit:.3f} AU  ")
        ok = self.a_wdp < a_crit
        t.insert(tk.END, (f"margin {a_crit / self.a_wdp:.2f}x\n" if ok
                          else "UNSTABLE\n"),
                 "quiet" if ok else "severe")

    # ------------------------------------------------------ Time controls

    def fast_forward(self):
        if self.ff_in_progress:
            return
        try:
            fraction = float(self.ff_years_entry.get())
        except ValueError:
            messagebox.showerror("Input Error", "FF amount must be a number")
            return
        unit = self.ff_unit_box.get()
        scale = {"ecc. cycles": self.period_secular,
                 "WD orbits": self.period_wd_yr,
                 "years": 1.0,
                 "planet years": self.period_p_yr}.get(unit, self.period_wd_yr)
        self.start_ff(abs(fraction) * scale)

    def next_periastron(self):
        """Integrate forward to the binary's next periastron (t = 0 mod P)."""
        if self.ff_in_progress:
            return
        remaining = self.period_wd_yr - np.mod(self.time_step,
                                               self.period_wd_yr)
        self.start_ff(remaining)

    def start_ff(self, span):
        self.ff_remaining = span
        self.ff_steps_since_draw = 0
        self.ff_in_progress = True
        self.ff_was_running = self.is_running
        if self.is_running:
            self.is_running = False
            if self.animation_id:
                self.root.after_cancel(self.animation_id)
        self.fast_forward_step()

    def fast_forward_step(self):
        chunk = min(1500 * self.dt_ff, self.ff_remaining)
        self.advance(chunk, dt=self.dt_ff)
        self.ff_remaining -= chunk
        self.record_history(self.binary_positions(self.time_step))
        self.sample_e()
        if self.ff_steps_since_draw >= 10 or self.ff_remaining <= 1e-9:
            self.ff_steps_since_draw = 0
            self.update_e_plot()
            self.update_stats_label()
            # The measured cycle lives in the metrics panel too, and a long
            # fast-forward can run for minutes, so keep it current instead
            # of leaving a startup-time reading on screen until the end.
            self.update_metrics_display()
            self.canvas.draw_idle()
        else:
            self.ff_steps_since_draw += 1
        if self.ff_remaining > 1e-9:
            self.root.after(1, self.fast_forward_step)
        else:
            self.ff_in_progress = False
            self.update_stats_label()
            self.update_env_display()
            self.update_wdp_env_display()
            self.update_metrics_display()
            self.render_frame()
            if self.ff_was_running:
                self.is_running = True
                self.btn_toggle.config(text="Pause Simulation")
                self.animate_loop()

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
            return np.array(stars[0:3])
        return np.zeros(3)

    # ------------------------------------------------------ Parameters

    def load_preset(self):
        p = self.PRESET
        pairs = [
            (self.m_orange_entry, p["m_orange"]), (self.m_wd_entry, p["m_wd"]),
            (self.age_entry, p["age"]), (self.a_wd_entry, p["a_wd"]),
            (self.e_wd_entry, p["e_wd"]), (self.i_wd_entry, p["i_wd"]),
            (self.m_blue_entry, p["m_blue"]), (self.a_blue_entry, p["a_blue"]),
            (self.e_blue_entry, p["e_blue"]), (self.i_blue_entry, p["i_blue"]),
            (self.f_blue_entry, p["f_blue"]),
            (self.m_giant_entry, p["m_giant"]),
            (self.a_giant_entry, p["a_giant"]),
            (self.e_giant_entry, p["e_giant"]),
            (self.i_giant_entry, p["i_giant"]),
            (self.f_giant_entry, p["f_giant"]),
            (self.obliq_entry, p["obliquity"]),
            (self.spin_node_entry, p["spin_node"]),
        ]
        for entry, val in pairs:
            entry.delete(0, tk.END)
            entry.insert(0, str(val))

        self.giant_var.set(p["giant_on"])
        moon_keys = [("moon1_on", "m_moon1", "a_moon1", "i_moon1", "p_moon1"),
                     ("moon2_on", "m_moon2", "a_moon2", "i_moon2", "p_moon2")]
        for k, keys in enumerate(moon_keys):
            self.moon_vars[k].set(p[keys[0]])
            for c, key in enumerate(keys[1:]):
                self.moon_entries[k][c].delete(0, tk.END)
                self.moon_entries[k][c].insert(0, str(p[key]))

        self.update_parameters()

    def update_parameters(self):
        try:
            self.m_orange = float(self.m_orange_entry.get())
            self.m_wd = float(self.m_wd_entry.get())
            age_gyr = float(self.age_entry.get())
            self.a_wd = float(self.a_wd_entry.get())
            self.e_wd = float(self.e_wd_entry.get())
            self.i_wd_deg = float(self.i_wd_entry.get())

            self.a_p = float(self.a_blue_entry.get())
            e_blue = float(self.e_blue_entry.get())
            i_blue = float(self.i_blue_entry.get())
            f_blue = float(self.f_blue_entry.get())
            m_blue = float(self.m_blue_entry.get()) * M_EARTH_MSUN

            self.giant_on = bool(self.giant_var.get())
            m_giant = float(self.m_giant_entry.get()) * M_JUP_MSUN
            self.a_giant = float(self.a_giant_entry.get())
            self.e_giant = float(self.e_giant_entry.get())
            i_giant = float(self.i_giant_entry.get())
            f_giant = float(self.f_giant_entry.get())

            self.wdp_on = bool(self.wdp_var.get())
            m_wdp = float(self.m_wdp_entry.get()) * M_MARS_MSUN
            self.a_wdp = float(self.a_wdp_entry.get())
            self.e_wdp = float(self.e_wdp_entry.get())
            i_wdp = float(self.i_wdp_entry.get())
            f_wdp = float(self.f_wdp_entry.get())

            self.obliquity_deg = float(self.obliq_entry.get())
            self.spin_node_deg = float(self.spin_node_entry.get())
            self.moon_vis = max(1.0, float(self.moon_vis_entry.get()))

            if self.e_wd < 0 or self.e_wd >= 1:
                raise ValueError("WD eccentricity must be between 0 and 0.99")
            if not 0 <= e_blue < 1:
                raise ValueError("Blue planet e must be between 0 and 0.99")
            if not 0 <= self.e_giant < 1:
                raise ValueError("Gas giant e must be between 0 and 0.99")
            if age_gyr <= 0:
                raise ValueError("Cooling age must be positive")
            if self.a_p <= 0 or self.a_giant <= 0:
                raise ValueError("Semi-major axes must be positive")
            if self.wdp_on:
                if not 0 <= self.e_wdp < 1:
                    raise ValueError("WD planet e must be between 0 and 0.99")
                if self.a_wdp <= 0 or m_wdp <= 0:
                    raise ValueError("WD planet a and mass must be positive")
            if m_blue <= 0:
                raise ValueError("Blue planet mass must be positive")

            self.i_wd_rad = np.radians(self.i_wd_deg)

            # ---- FULL time reset ----
            self.time_step = 0.0
            self.ff_in_progress = False

            # ---- Stellar properties ----
            self.L_orange = self.m_orange ** 4
            self.L_wd = 1e-3 * self.m_wd * age_gyr ** -1.4
            self.T_orange = T_SUN * self.m_orange ** 0.505
            self.r_wd_rsun = 0.0127 * (self.m_wd / 0.6) ** (-1.0 / 3.0)
            self.r_wd_au = self.r_wd_rsun * R_SUN_AU
            self.T_wd = T_SUN * (self.L_wd / self.r_wd_rsun ** 2) ** 0.25

            self.uv_lum_host = (planck_band_fraction(self.T_orange)
                                / F_UV_SUN * self.L_orange)
            self.uv_lum_wd = (planck_band_fraction(self.T_wd)
                              / F_UV_SUN * self.L_wd)

            self.r_peri_wd = self.a_wd * (1 - self.e_wd)
            self.r_apa_wd = self.a_wd * (1 + self.e_wd)

            self.period_p_yr = np.sqrt(self.a_p ** 3 / self.m_orange)
            self.period_wd_yr = np.sqrt(
                self.a_wd ** 3 / (self.m_orange + self.m_wd))
            self.period_g_yr = np.sqrt(self.a_giant ** 3 / self.m_orange)
            self.period_wdp_yr = np.sqrt(self.a_wdp ** 3 / self.m_wd)
            self.wd_age_gyr = age_gyr

            # ---- Secular (apsidal precession) period driven by the WD.
            # This is the eccentricity cycle: the slow rhythm that actually
            # moves tides, instellation and temperature together.
            n_p_rate = 2.0 * np.pi / self.period_p_yr
            self.prec_wd = (0.75 * (self.m_wd / self.m_orange) * n_p_rate
                            * (self.a_p / self.a_wd) ** 3
                            / (1 - self.e_wd ** 2) ** 1.5)
            self.period_secular = (2.0 * np.pi / self.prec_wd
                                   if self.prec_wd > 0 else float("inf"))
            # Octupole strength. Above ~0.01 the eccentric Kozai-Lidov term
            # is live and a non-coplanar orbit can be pumped hard.
            self.eps_oct = ((self.a_p / self.a_wd) * self.e_wd
                            / (1 - self.e_wd ** 2))

            # ---- Timestep from the fastest planet, not a fixed constant ----
            fastest = self.period_p_yr
            if self.giant_on:
                fastest = min(fastest, self.period_g_yr)
            if self.wdp_on:
                # An 81-day WD planet drops the global timestep ~3x; the
                # blue planet just gets better resolved as a side effect.
                fastest = min(fastest, self.period_wdp_yr)
            self.dt = fastest / 2000.0        # playback: ~2000 steps/orbit
            # Fast-forward step. This is NOT free to coarsen: at 200
            # steps/orbit the forced eccentricity peak reads 0.35 instead of
            # the converged 0.173, and at 400 it reads 0.186. 800 agrees with
            # 1600 to under 2%, so that is the floor.
            self.dt_ff = fastest / 800.0

            # ---- Planet set-up (each planet has its own host star) ----
            self.p_mass = [m_blue]
            self.p_host = ["orange"]
            init = [(self.a_p, e_blue, i_blue, f_blue)]
            self.idx_giant = None
            self.idx_wdp = None
            if self.giant_on:
                self.idx_giant = len(self.p_mass)
                self.p_mass.append(m_giant)
                self.p_host.append("orange")
                init.append((self.a_giant, self.e_giant, i_giant, f_giant))
            if self.wdp_on:
                self.idx_wdp = len(self.p_mass)
                self.p_mass.append(m_wdp)
                self.p_host.append("wd")
                init.append((self.a_wdp, self.e_wdp, i_wdp, f_wdp))
            self.p_mass = np.array(self.p_mass)
            self.n_planets = len(self.p_mass)

            stars0 = self.binary_positions(0.0)
            base = {"orange": (np.array(stars0[0:3]),
                               self.binary_velocity(0.0, "orange"),
                               self.m_orange),
                    "wd": (np.array(stars0[3:6]),
                           self.binary_velocity(0.0, "wd"),
                           self.m_wd)}

            self.p_pos = np.zeros((self.n_planets, 3))
            self.p_vel = np.zeros((self.n_planets, 3))
            for k, (a, e, inc, f0) in enumerate(init):
                r0, v0, m_host = base[self.p_host[k]]
                mu = G_SIM * (m_host + self.p_mass[k])
                pos, vel = kepler_state(a, e, inc, f0, mu)
                self.p_pos[k] = r0 + pos
                self.p_vel[k] = v0 + vel

            # ---- Moons on rails ----
            self.moons = []
            for k in range(2):
                ent = self.moon_entries[k]
                mm = float(ent[0].get()) * M_MOON_MSUN
                am = float(ent[1].get())
                im = float(ent[2].get())
                ph = float(ent[3].get())
                on = bool(self.moon_vars[k].get())
                if on and am <= 0:
                    raise ValueError(f"Moon {k + 1} distance must be positive")
                period = (np.sqrt(am ** 3 / (m_blue + mm))
                          if am > 0 else 1.0)
                self.moons.append({"on": on, "mass": mm, "a": am,
                                   "inc": im, "phase": ph, "period": period})

            self.hist = {"blue": [], "giant": [], "orange": [],
                         "wd": [], "wdp": []}
            self.reset_e_history()
            self.force_plot_redraw()
            self.update_e_plot()
            self.update_env_display()
            self.update_wdp_env_display()
            self.update_metrics_display()
            self.update_stats_label()
            self.render_frame()

        except ValueError as e:
            messagebox.showerror("Input Error",
                                 f"Invalid parameters entered:\n{e}")

    # ------------------------------------------------------ Metrics panel

    def update_metrics_display(self):
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
        blue_ok = self.a_p < a_crit
        giant_ok = (not self.giant_on) or (self.a_giant < a_crit)

        kozai_term = 1 - (5 / 3) * np.cos(self.i_wd_rad) ** 2
        e_max_kozai = np.sqrt(kozai_term) if kozai_term > 0 else 0

        t_kozai = (2.0 / (3.0 * np.pi)
                   * self.period_wd_yr ** 2 / self.period_p_yr
                   * (self.m_orange + self.m_wd) / self.m_wd
                   * (1 - self.e_wd ** 2) ** 1.5)

        tidal_param = (2.0 * self.m_wd / self.m_orange
                       * (self.a_p / self.r_peri_wd) ** 3)

        # Secular apsidal precession driven on the inner planet:
        # d(varpi)/dt = (3/4) n (m_pert/M*) (a/a_pert)^3 (1-e_pert^2)^-1.5
        n_p = 2.0 * np.pi / self.period_p_yr
        prec_wd = (0.75 * (self.m_wd / self.m_orange) * n_p
                   * (self.a_p / self.a_wd) ** 3
                   / (1 - self.e_wd ** 2) ** 1.5)
        prec_g = 0.0
        if self.giant_on:
            prec_g = (0.75 * (self.p_mass[self.idx_giant] / self.m_orange)
                      * n_p
                      * (self.a_p / self.a_giant) ** 3
                      / (1 - self.e_giant ** 2) ** 1.5)
        ratio = prec_g / prec_wd if prec_wd > 0 else 0.0

        t = self.output_text
        t.delete("1.0", tk.END)
        t.insert(tk.END,
                 f"Orange L : {self.L_orange:.4f}  T:{self.T_orange:.0f}K\n"
                 f"WD L     : {self.L_wd:.4f}  T:{self.T_wd:.0f}K\n"
                 f"Blue year: {self.period_p_yr * 365.25:.1f} d"
                 f"  ({self.period_p_yr:.4f} yr)\n"
                 f"Binary   : {self.period_wd_yr:.1f} yr\n"
                 f"WD peri  : {self.r_peri_wd:.2f} AU\n"
                 f"WD apo   : {self.r_apa_wd:.2f} AU\n")

        t.insert(tk.END, f"S-type limit (H&W): {a_crit:.3f} AU\n")
        t.insert(tk.END, "  Blue  : ")
        t.insert(tk.END, "STABLE\n" if blue_ok else "UNSTABLE\n",
                 "quiet" if blue_ok else "severe")
        if self.giant_on:
            t.insert(tk.END, "  Giant : ")
            t.insert(tk.END, "STABLE\n" if giant_ok else "UNSTABLE\n",
                     "quiet" if giant_ok else "severe")

        t.insert(tk.END, "-- SECULAR / KOZAI --\n", "head")
        t.insert(tk.END, f"Ecc. cycle  : {self.period_secular:.0f} yr"
                         f" (linear est.)\n")
        m = self.measure_envelope() if self.e_hist else None
        if m and m["period"]:
            t.insert(tk.END, f"  measured  : {m['period']:.0f} yr"
                             f"  [{m['source']}]\n", "quiet")
            t.insert(tk.END, f"  e envelope: {m['e'].min():.4f}"
                             f" - {m['e'].max():.4f}\n")
        else:
            frac = (self.e_hist[-1][0] / self.period_secular
                    if self.e_hist else 0.0)
            t.insert(tk.END, f"  measured  : run longer "
                             f"({frac:.2f} cycles so far)\n", "head")
        t.insert(tk.END, f"Tidal param : {tidal_param:.2e}\n")
        t.insert(tk.END, f"eps_octupole: {self.eps_oct:.4f}\n")

        # Kozai-Lidov is active between the two critical inclinations.
        i_lo, i_hi = 39.23, 140.77
        in_kozai = i_lo < self.i_wd_deg < i_hi
        t.insert(tk.END, "Inclination : ")
        if not in_kozai:
            t.insert(tk.END, f"{self.i_wd_deg:.1f} deg SAFE\n", "quiet")
        elif self.eps_oct > 0.01:
            t.insert(tk.END, f"{self.i_wd_deg:.1f} deg KOZAI+OCTUPOLE\n",
                     "severe")
        else:
            t.insert(tk.END, f"{self.i_wd_deg:.1f} deg KOZAI ACTIVE\n",
                     "elevated")
        if in_kozai:
            t.insert(tk.END, f"  planet e -> {e_max_kozai:.2f} in "
                             f"{t_kozai:.1e} yr\n", "severe")
            if self.giant_on:
                # The giant has no protector of its own: the blue planet is
                # far too light and GR precession is negligible out here.
                t_kg = (2.0 / (3.0 * np.pi)
                        * self.period_wd_yr ** 2 / self.period_g_yr
                        * (self.m_orange + self.m_wd) / self.m_wd
                        * (1 - self.e_wd ** 2) ** 1.5)
                t.insert(tk.END, f"  GIANT UNPROTECTED, e -> "
                                 f"{e_max_kozai:.2f} in {t_kg:.1e} yr\n",
                         "severe")
            if self.wdp_on:
                # For the WD planet the PERTURBER is the orange dwarf.
                t_kw = (2.0 / (3.0 * np.pi)
                        * self.period_wd_yr ** 2 / self.period_wdp_yr
                        * (self.m_orange + self.m_wd) / self.m_orange
                        * (1 - self.e_wd ** 2) ** 1.5)
                t.insert(tk.END, f"  WD PLANET in band too, "
                                 f"e -> {e_max_kozai:.2f} in "
                                 f"{t_kw:.1e} yr\n", "severe")
        elif self.eps_oct > 0.05 and self.i_wd_deg > 5.0:
            t.insert(tk.END, "  octupole risk above ~5 deg\n", "elevated")


        if self.giant_on:
            t.insert(tk.END, "-- SECULAR COMPETITION --\n", "head")
            t.insert(tk.END,
                     f"WD prec.    : {prec_wd:.3e} rad/yr\n"
                     f"Giant prec. : {prec_g:.3e} rad/yr\n"
                     f"Ratio G/WD  : {ratio:.2f}x  ")
            if ratio > 10:
                t.insert(tk.END, "KOZAI SUPPRESSED\n", "quiet")
            elif ratio > 1:
                t.insert(tk.END, "PARTIAL\n", "elevated")
            else:
                t.insert(tk.END, "WD DOMINANT\n", "severe")

            # Mutual Hill separation between the two planets
            m_tot = self.p_mass[0] + self.p_mass[self.idx_giant]
            r_hm = ((m_tot / (3.0 * self.m_orange)) ** (1.0 / 3.0)
                    * 0.5 * (self.a_p + self.a_giant))
            delta = abs(self.a_giant - self.a_p) / r_hm
            t.insert(tk.END, f"Planet sep  : {delta:.1f} R_H,mutual  ")
            if delta > 10:
                t.insert(tk.END, "OK\n", "quiet")
            elif delta > 3.46:
                t.insert(tk.END, "TIGHT\n", "elevated")
            else:
                t.insert(tk.END, "HILL-UNSTABLE\n", "severe")

        env = getattr(self, "last_env", None)
        if env:
            t.insert(tk.END, "-- MOONS --\n", "head")
            t.insert(tk.END, f"Planet r_Hill: {env['rh']:.5f} AU\n"
                             f"Sat. a_crit  : {env['a_crit_sat']:.5f} AU\n")
            any_moon = False
            for k, mi in enumerate(env["moons"]):
                if not mi:
                    continue
                any_moon = True
                t.insert(tk.END,
                         f"M{k + 1} P={mi['period_d']:.2f} d "
                         f"a/a_crit={mi['ratio']:.2f} ")
                t.insert(tk.END, mi["status"] + "\n", mi["tag"])
            if not any_moon:
                t.insert(tk.END, "(none enabled)\n")

    # ------------------------------------------------------ Rendering

    def setup_e_axes(self):
        """Style the eccentricity-history strip. Built once; only the data
        line is refreshed, so long runs stay cheap to draw."""
        ax = self.ax_e
        ax.clear()
        ax.set_facecolor("#161b22")
        for sp in ax.spines.values():
            sp.set_color("#30363d")
        ax.tick_params(colors="#8b949e", labelsize=7)
        ax.set_xlabel("time (yr)", color="#8b949e", fontsize=8, labelpad=1)
        ax.set_ylabel("planet e", color="#8b949e", fontsize=8, labelpad=2)
        ax.grid(True, color="#21262d", linewidth=0.6)
        self.e_line, = ax.plot([], [], color="#58a6ff", linewidth=1.0,
                               alpha=0.75)
        self.e2_line, = ax.plot([], [], color="#ff7b54", linewidth=0.9,
                                alpha=0.55)
        self.e_env, = ax.plot([], [], color="#d29922", linewidth=1.3)
        self.e_peaks, = ax.plot([], [], "v", color="#3fb950", markersize=5,
                                linestyle="none")
        self.e_now, = ax.plot([], [], "o", color="#f0f6fc", markersize=4)
        # Bands: above 0.2 the seasonal swing turns severe.
        self.e_band = ax.axhspan(0.20, 1.0, color="#f85149", alpha=0.10)
        self.e_txt = ax.text(0.015, 0.86, "", transform=ax.transAxes,
                             color="#8b949e", fontsize=7, va="top")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 0.4)

    def reset_e_history(self):
        self.e_hist = []
        self.e2_hist = []
        self._env_cache = None
        # Aim for roughly 1500 samples across three secular cycles.
        self.e_sample_every = max(self.period_p_yr,
                                  self.period_secular * 3.0 / 1500.0)
        self.next_e_sample = 0.0
        self.sample_e(force=True)

    def sample_e(self, force=False):
        """Record the planet's osculating eccentricity on a fixed cadence
        tied to the secular period, so the trace has the same resolution
        whether the run came from playback or fast-forward."""
        if not force and self.time_step < self.next_e_sample:
            return
        self.next_e_sample = self.time_step + self.e_sample_every
        e = self.osculating_elements(0)[1]
        if np.isfinite(e):
            self.e_hist.append((self.time_step, min(e, 1.5)))
        if self.idx_wdp is not None:
            e2 = self.osculating_elements(self.idx_wdp)[1]
            if np.isfinite(e2):
                self.e2_hist.append((self.time_step, min(e2, 1.5)))
        if len(self.e_hist) > 6000:
            del self.e_hist[::2]          # thin oldest-first, keep shape
            if len(self.e2_hist) > 6000:
                del self.e2_hist[::2]
            self.e_sample_every *= 2.0

    def measure_envelope(self):
        """Measure the eccentricity cycle directly from the recorded trace
        instead of trusting the linear estimate.

        e(t) carries a fast ripple at the binary period sitting on top of the
        slow secular envelope, so take a rolling maximum over roughly one
        binary period first, then locate envelope peaks that are separated by
        at least a quarter of the expected cycle. Two peaks give a period
        outright; one peak plus one trough gives it from a half cycle, which
        is what lets a reading appear before a full cycle has run.

        Cached on sample count, because this is called every frame.
        """
        cache = getattr(self, "_env_cache", None)
        if cache is not None and cache["n"] == len(self.e_hist):
            return cache
        arr = np.array(self.e_hist)
        t, e = arr[:, 0], arr[:, 1]
        out = {"n": len(self.e_hist), "t": t, "e": e, "env": e,
               "peaks": np.array([]), "period": None, "npeak": 0,
               "source": "none"}
        if len(e) < 8:
            self._env_cache = out
            return out

        dt_s = max((t[-1] - t[0]) / max(1, len(t) - 1), 1e-9)
        # Smoothing window: about one binary period, but never so wide that
        # it eats the secular signal itself.
        win_yr = min(self.period_wd_yr, self.period_secular / 10.0)
        w = int(np.clip(round(win_yr / dt_s), 1, 50))

        ext_hi = np.pad(e, w, mode="edge")
        view = np.lib.stride_tricks.sliding_window_view(ext_hi, 2 * w + 1)
        env_hi = view.max(axis=1)
        env_lo = view.min(axis=1)
        out["env"] = env_hi

        sep = int(np.clip(round((self.period_secular / 4.0) / dt_s),
                          2, max(2, len(e) // 3)))

        def extrema(sig, want_max):
            idx = []
            i = 0
            while i < len(sig):
                lo, hi = max(0, i - sep), min(len(sig), i + sep + 1)
                seg = sig[lo:hi]
                best = seg.max() if want_max else seg.min()
                if sig[i] == best:
                    # collapse plateaus to their midpoint
                    j = i
                    while j + 1 < len(sig) and sig[j + 1] == sig[i]:
                        j += 1
                    mid = (i + j) // 2
                    # Reject anything within one separation window of either
                    # end. Near the edges the signal has not been seen to
                    # turn over yet, so a rising tail reads as a peak and
                    # drags the mean spacing down (an 8% low bias before
                    # this guard was added).
                    if sep <= mid <= len(sig) - 1 - sep:
                        idx.append(mid)
                    i = j + sep
                else:
                    i += 1
            return idx

        pk = extrema(env_hi, True)
        tr = extrema(env_lo, False)
        out["peaks"] = np.array(pk, dtype=int)
        out["npeak"] = len(pk)

        if len(pk) >= 2:
            out["period"] = float(np.mean(np.diff(t[pk])))
            out["source"] = f"{len(pk)} peaks"
        elif len(tr) >= 2:
            out["period"] = float(np.mean(np.diff(t[tr])))
            out["source"] = f"{len(tr)} troughs"
        elif len(pk) == 1 and len(tr) == 1:
            out["period"] = float(2.0 * abs(t[pk[0]] - t[tr[0]]))
            out["source"] = "half cycle"
        self._env_cache = out
        return out

    def update_e_plot(self):
        if not self.e_hist:
            return
        m = self.measure_envelope()
        t, e = m["t"], m["e"]
        self.e_line.set_data(t, e)
        self.e_env.set_data(t, m["env"])
        if len(m["peaks"]):
            self.e_peaks.set_data(t[m["peaks"]], m["env"][m["peaks"]])
        else:
            self.e_peaks.set_data([], [])
        self.e_now.set_data([t[-1]], [e[-1]])
        if self.e2_hist:
            a2 = np.array(self.e2_hist)
            self.e2_line.set_data(a2[:, 0], a2[:, 1])
        else:
            self.e2_line.set_data([], [])
        tmax = max(t[-1], self.e_sample_every * 10)
        self.ax_e.set_xlim(0, tmax * 1.02)
        self.ax_e.set_ylim(0, max(0.05, e.max() * 1.25))
        if m["period"]:
            cyc = (f"cycle {m['period']:.0f} yr measured ({m['source']}), "
                   f"linear est. {self.period_secular:.0f}")
        else:
            cyc = (f"cycle {self.period_secular:.0f} yr linear est., "
                   f"{t[-1] / self.period_secular:.2f} cycles elapsed")
        self.e_txt.set_text(
            f"e now {e[-1]:.4f}   envelope {e.min():.4f}-{e.max():.4f}   {cyc}")

    def force_plot_redraw(self):
        """Rebuild static plot elements for the current view mode."""
        self.ax.clear()

        self.ax.xaxis.label.set_color('#8b949e')
        self.ax.yaxis.label.set_color('#8b949e')
        self.ax.zaxis.label.set_color('#8b949e')
        self.ax.tick_params(colors='#8b949e')

        # ---- Static binary tracks (one binary period) ----
        times = np.linspace(0, self.period_wd_yr, 2000)
        tr = np.array([self.binary_positions(t) for t in times])
        self.track_orange = tr[:, 0:3]
        self.track_wd = tr[:, 3:6]
        self.track_rel = tr[:, 3:6] - tr[:, 0:3]

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
        self.blue_dot, = self.ax.plot([], [], [], 'o', color='#58a6ff',
                                      markersize=6, label='Blue Planet')

        if self.giant_on:
            self.giant_dot, = self.ax.plot([], [], [], 'o', color='#d29922',
                                           markersize=9, label='Gas Giant')
            self.giant_trail, = self.ax.plot([], [], [], color='#d29922',
                                             linewidth=1.0, alpha=0.6)
        else:
            self.giant_dot = None
            self.giant_trail = None

        if self.wdp_on:
            self.wdp_dot, = self.ax.plot([], [], [], 'o', color='#ff7b54',
                                         markersize=5, label='WD Planet')
            self.wdp_trail, = self.ax.plot([], [], [], color='#ff7b54',
                                           linewidth=0.9, alpha=0.6)
        else:
            self.wdp_dot = None
            self.wdp_trail = None

        # Spin axis of the blue planet, drawn as a short pole through it
        self.spin_line, = self.ax.plot([], [], [], color='#f0f6fc',
                                       linewidth=1.4, alpha=0.9,
                                       label='Spin Axis')
        self.moon_dots = []
        self.moon_rings = []
        for k in range(2):
            if self.moons[k]["on"]:
                d, = self.ax.plot([], [], [], 'o', color='#c9d1d9',
                                  markersize=4,
                                  label=f'Moon {k + 1} (x{self.moon_vis:.0f})')
                rg, = self.ax.plot([], [], [], color='#c9d1d9',
                                   linewidth=0.8, alpha=0.5)
            else:
                d, rg = None, None
            self.moon_dots.append(d)
            self.moon_rings.append(rg)

        self.planet_trail, = self.ax.plot([], [], [], color='#58a6ff',
                                          linewidth=1.2, alpha=0.7)
        self.orange_trail, = self.ax.plot([], [], [], color='#f97316',
                                          linewidth=1.0, alpha=0.6)
        self.wd_trail, = self.ax.plot([], [], [], color='white',
                                      linewidth=1.0, alpha=0.6)

        if not hasattr(self, "hist"):
            self.hist = {"blue": [], "giant": [], "orange": [],
                         "wd": [], "wdp": []}

        self.ax.legend(facecolor="#161b22", edgecolor="none",
                       labelcolor="white", loc="upper left", fontsize=8)
        self.update_axes_limits()
        self.canvas.draw_idle()

    def record_history(self, stars):
        """Synchronized samples for every body (same frame, same index) so
        trails can be re-based into any view frame."""
        self.hist["blue"].append(tuple(self.p_pos[0]))
        self.hist["giant"].append(
            tuple(self.p_pos[self.idx_giant])
            if self.idx_giant is not None else (0.0, 0.0, 0.0))
        self.hist["wdp"].append(
            tuple(self.p_pos[self.idx_wdp])
            if self.idx_wdp is not None else (0.0, 0.0, 0.0))
        self.hist["orange"].append(stars[0:3])
        self.hist["wd"].append(stars[3:6])

        max_history = 10000
        if len(self.hist["blue"]) > max_history:
            for key in self.hist:
                self.hist[key].pop(0)

    def render_frame(self):
        """Draw current state in the active view frame."""
        stars = self.binary_positions(self.time_step)
        off = self.frame_offset(stars)

        self.bary_dot.set_data_3d(*[[v] for v in -off])
        self.orange_dot.set_data_3d(*[[v] for v in np.array(stars[0:3]) - off])
        self.wd_dot.set_data_3d(*[[v] for v in np.array(stars[3:6]) - off])

        p_blue = self.p_pos[0] - off
        self.blue_dot.set_data_3d([p_blue[0]], [p_blue[1]], [p_blue[2]])

        if self.giant_dot is not None:
            p_g = self.p_pos[self.idx_giant] - off
            self.giant_dot.set_data_3d([p_g[0]], [p_g[1]], [p_g[2]])
        if self.wdp_dot is not None:
            p_w2 = self.p_pos[self.idx_wdp] - off
            self.wdp_dot.set_data_3d([p_w2[0]], [p_w2[1]], [p_w2[2]])

        # Spin axis: a pole scaled to the current view so it stays visible
        axis_len = 0.05 * self.view_halfwidth()
        n_spin = self.spin_axis()
        a1 = p_blue - n_spin * axis_len
        a2 = p_blue + n_spin * axis_len
        self.spin_line.set_data_3d([a1[0], a2[0]], [a1[1], a2[1]],
                                   [a1[2], a2[2]])

        # Moons, drawn at an exaggerated separation (labelled in the legend)
        for k in range(2):
            if self.moon_dots[k] is None:
                continue
            mo = self.moon_offset(k, self.time_step) * self.moon_vis
            mp = p_blue + mo
            self.moon_dots[k].set_data_3d([mp[0]], [mp[1]], [mp[2]])

            th = np.linspace(0, 2 * np.pi, 80)
            e1, e2, n = self.equatorial_basis()
            im = np.radians(self.moons[k]["inc"])
            u = np.cos(im) * e2 + np.sin(im) * n
            ring = (self.moons[k]["a"] * self.moon_vis
                    * (np.outer(np.cos(th), e1) + np.outer(np.sin(th), u)))
            ring = ring + p_blue
            self.moon_rings[k].set_data_3d(ring[:, 0], ring[:, 1], ring[:, 2])

        if self.hist["blue"]:
            b = np.array(self.hist["blue"])
            o = np.array(self.hist["orange"])
            w = np.array(self.hist["wd"])
            g = np.array(self.hist["giant"])
            w2 = np.array(self.hist["wdp"])

            if self.view_mode == "orange":
                b = b - o
                w = w - o
                g = g - o
                w2 = w2 - o
                o = o - o

            self.planet_trail.set_data_3d(b[:, 0], b[:, 1], b[:, 2])
            self.orange_trail.set_data_3d(o[:, 0], o[:, 1], o[:, 2])
            self.wd_trail.set_data_3d(w[:, 0], w[:, 1], w[:, 2])
            if self.giant_trail is not None:
                self.giant_trail.set_data_3d(g[:, 0], g[:, 1], g[:, 2])
            if self.wdp_trail is not None:
                self.wdp_trail.set_data_3d(w2[:, 0], w2[:, 1], w2[:, 2])

        self.canvas.draw_idle()

    def update_stats_label(self):
        a_b, e_b, i_b, r_b, _ = self.osculating_elements(0)
        sep = self.binary_separation()
        txt = (f"Simulation Years : {self.time_step:.2f}\n"
               f"Blue Orbits      : "
               f"{self.time_step / self.period_p_yr:.2f}\n"
               f"WD Orbits        : "
               f"{self.time_step / self.period_wd_yr:.4f}\n"
               f"Binary Sep       : {sep:.2f} AU\n"
               f"Blue  a/e/i      : {a_b:.5f} / {e_b:.5f} / {i_b:.3f}\n")
        if self.idx_giant is not None:
            a_g, e_g, i_g, _, _ = self.osculating_elements(self.idx_giant)
            txt += (f"Giant a/e/i      : "
                    f"{a_g:.5f} / {e_g:.5f} / {i_g:.3f}\n")
        if self.idx_wdp is not None:
            a_w, e_w, i_w, _, _ = self.osculating_elements(self.idx_wdp)
            txt += (f"WDP   a/e/i      : "
                    f"{a_w:.5f} / {e_w:.5f} / {i_w:.3f}\n")
        txt += (f"Config           : {self.current_config_name}\n"
                f"View half-width  : {self.view_halfwidth():.2f} AU\n"
                f"Warp {self.speed_slider.get()}"
                f"   dt {self.dt:.2e} yr   View: {self.view_mode}")
        self.year_label.config(text=txt)

    # ------------------------------------------------------ Animation

    def animate_loop(self):
        if not self.is_running:
            return

        # Frame span tied to the planet's own year, so the view stays
        # watchable whether the binary is 50 or 1000 years wide.
        span = self.speed_slider.get() * self.period_p_yr / 50.0
        self.advance(span)

        stars = self.binary_positions(self.time_step)
        self.record_history(stars)
        self.sample_e()

        self.update_stats_label()
        self.update_env_display()
        self.update_wdp_env_display()
        self.update_e_plot()
        # The metrics panel carries the measured cycle, so refresh it
        # occasionally rather than only on Apply and end-of-fast-forward.
        self.frame_count = getattr(self, "frame_count", 0) + 1
        if self.frame_count % 25 == 0:
            self.update_metrics_display()
        self.render_frame()
        self.animation_id = self.root.after(100, self.animate_loop)


if __name__ == "__main__":
    root = tk.Tk()
    app = AnimatedOrbitalSimApp(root)
    root.mainloop()
