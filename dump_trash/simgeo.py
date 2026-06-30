import tkinter as tk
from tkinter import ttk, messagebox
import math
from dataclasses import dataclass

@dataclass
class GeolocationResult:
    gsd: float
    dx_px: float
    dy_px: float
    dx_east: float
    dy_north: float
    lat_target: float
    lon_target: float

class Geolocator:
    """
    Modul Geolocation terpisah dari UI untuk kemudahan testing dan reusability.
    Menggunakan model WGS84 Ellipsoid untuk akurasi tinggi.
    """
    A_EARTH = 6378137.0  # WGS84 Semi-major axis
    E_SQ = 0.00669437999014  # WGS84 Eccentricity squared

    @classmethod
    def calculate(cls, 
                  view_angle: float, 
                  heading: float, 
                  altitude: float, 
                  w_frame: int, 
                  h_frame: int, 
                  lat0: float, 
                  lon0: float, 
                  u: float, 
                  v: float) -> GeolocationResult:
        """
        Menghitung koordinat GPS objek target berdasarkan posisinya di dalam frame kamera UAV.
        """
        if w_frame <= 0 or h_frame <= 0 or view_angle <= 0 or view_angle >= 180:
            raise ValueError("Parameter kamera tidak valid.")

        # 1. Hitung GSD (m/pixel)
        gsd = (2 * altitude * math.tan(math.radians(view_angle / 2.0))) / w_frame

        # 2. Offset piksel dari pusat frame (Tengah adalah (0,0))
        dx_px = u - (w_frame / 2.0)
        dy_px = v - (h_frame / 2.0)

        # 3. Offset jarak dalam frame-space (meter)
        dx_0 = dx_px * gsd
        dy_0 = dy_px * gsd

        # 4. Rotasi ke sistem koordinat ENU (East-North-Up) berdasarkan Heading UAV
        # Catatan: dy_north dibalik (negatif) untuk dy_0 karena sumbu-v piksel bertambah ke bawah
        theta = math.radians(heading)
        dx_east = (dx_0 * math.cos(theta)) + (dy_0 * math.sin(theta))
        dy_north = (dx_0 * math.sin(theta)) - (dy_0 * math.cos(theta))

        # 5 & 6. Konversi offset meter menjadi derajat latitude/longitude menggunakan WGS84
        lat_rad = math.radians(lat0)
        sin_lat = math.sin(lat_rad)
        cos_lat = math.cos(lat_rad)
        
        # Mencegah division by zero di kutub geografis
        if abs(cos_lat) < 1e-9:
            cos_lat = 1e-9 if cos_lat >= 0 else -1e-9

        # Radius kelengkungan Meridian (R_M) dan Prime Vertical (R_N)
        r_m = cls.A_EARTH * (1 - cls.E_SQ) / math.pow(1 - cls.E_SQ * sin_lat**2, 1.5)
        r_n = cls.A_EARTH / math.sqrt(1 - cls.E_SQ * sin_lat**2)

        lat_target = lat0 + math.degrees(dy_north / r_m)
        lon_target = lon0 + math.degrees(dx_east / (r_n * cos_lat))

        return GeolocationResult(
            gsd=gsd,
            dx_px=dx_px,
            dy_px=dy_px,
            dx_east=dx_east,
            dy_north=dy_north,
            lat_target=lat_target,
            lon_target=lon_target
        )


class UAVGeolocationApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Simulasi Geolokasi BIMA UAV (Pro Version)")
        self.root.geometry("1200x700")
        self.root.configure(padx=15, pady=15)
        
        # Inisialisasi properti untuk mencegah error saat event resize sebelum widget dimuat
        self.cam_canvas_w = 320
        self.cam_canvas_h = 240
        self.map_canvas_w = 400
        self.map_canvas_h = 400

        self.setup_styles()
        self.init_variables()
        self.create_widgets()
        
        # Binding window resize untuk update canvas secara proporsional
        self.root.bind("<Configure>", self.on_resize)
        
        # Perhitungan inisial
        self.root.after(100, self.calculate_and_draw)

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TLabel", font=("Segoe UI", 10))
        style.configure("Header.TLabel", font=("Segoe UI", 12, "bold"))
        style.configure("Result.TLabel", font=("Segoe UI", 11, "bold"), foreground="#0052cc")
        style.configure("Warning.TLabel", font=("Segoe UI", 10, "bold"), foreground="red")
        
    def init_variables(self):
        # Menggunakan nilai default presisi tinggi
        self.vars = {
            "fov": tk.DoubleVar(value=84.0),
            "heading": tk.DoubleVar(value=0.0),
            "altitude": tk.DoubleVar(value=50.0),
            "w_frame": tk.IntVar(value=640),
            "h_frame": tk.IntVar(value=480),
            "lat0": tk.DoubleVar(value=-7.7671400723479795),
            "lon0": tk.DoubleVar(value=110.23367955806965),
            "u": tk.DoubleVar(value=200.0),
            "v": tk.DoubleVar(value=185.0),
        }
        
        # Menambahkan observer, setiap variabel berubah akan otomatis memicu perhitungan ulang
        for var in self.vars.values():
            var.trace_add("write", self.on_input_change)

    def on_input_change(self, *args):
        self.calculate_and_draw()

    def on_resize(self, event):
        # Update kanvas jika jendela diresize, menggunakan after id agar tidak spamming update
        if hasattr(self, '_resize_timer'):
            self.root.after_cancel(self._resize_timer)
        self._resize_timer = self.root.after(100, self.calculate_and_draw)

    def create_widgets(self):
        # Layout Utama: 3 Kolom
        self.main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.main_paned.pack(fill=tk.BOTH, expand=True)

        self.left_frame = ttk.Frame(self.main_paned, padding=10)
        self.center_frame = ttk.Frame(self.main_paned, padding=10)
        self.right_frame = ttk.Frame(self.main_paned, padding=10)

        self.main_paned.add(self.left_frame, weight=1)
        self.main_paned.add(self.center_frame, weight=2)
        self.main_paned.add(self.right_frame, weight=2)

        self.build_input_panel(self.left_frame)
        self.build_center_panel(self.center_frame)
        self.build_right_panel(self.right_frame)

    def build_input_panel(self, parent):
        ttk.Label(parent, text="Parameter Input", style="Header.TLabel").pack(anchor="w", pady=(0, 10))
        
        def create_input_group(title, fields):
            group = ttk.LabelFrame(parent, text=title, padding=10)
            group.pack(fill=tk.X, pady=5)
            for r, (label_text, var_name, is_slider, slider_range) in enumerate(fields):
                ttk.Label(group, text=label_text).grid(row=r*2, column=0, sticky="w", pady=(5,0))
                
                input_frame = ttk.Frame(group)
                input_frame.grid(row=r*2+1, column=0, sticky="ew")
                input_frame.columnconfigure(0, weight=1)

                entry = ttk.Entry(input_frame, textvariable=self.vars[var_name], width=15)
                
                if is_slider:
                    scale = ttk.Scale(input_frame, from_=slider_range[0], to=slider_range[1], variable=self.vars[var_name], orient=tk.HORIZONTAL)
                    scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
                    entry.pack(side=tk.RIGHT)
                else:
                    entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        create_input_group("Kamera & Resolusi", [
            ("FOV Horizontal (°)", "fov", True, (30, 150)),
            ("Resolusi Lebar (W)", "w_frame", False, None),
            ("Resolusi Tinggi (H)", "h_frame", False, None),
        ])
        
        create_input_group("Status Drone", [
            ("Heading (°, 0=Utara)", "heading", True, (0, 360)),
            ("Ketinggian AGL (m)", "altitude", True, (1, 300)),
            ("Latitude UAV", "lat0", False, None),
            ("Longitude UAV", "lon0", False, None),
        ])

        create_input_group("Posisi Target (Piksel)", [
            ("Piksel u (Horizontal)", "u", True, (0, 1920)),
            ("Piksel v (Vertikal)", "v", True, (0, 1080)),
        ])

        btn_reset = ttk.Button(parent, text="Reset ke Default PDF", command=self.reset_defaults)
        btn_reset.pack(fill=tk.X, pady=20)

    def reset_defaults(self):
        self.vars["fov"].set(84.0)
        self.vars["heading"].set(0.0)
        self.vars["altitude"].set(50.0)
        self.vars["w_frame"].set(640)
        self.vars["h_frame"].set(480)
        self.vars["lat0"].set(-7.7671400723479795)
        self.vars["lon0"].set(110.23367955806965)
        self.vars["u"].set(200.0)
        self.vars["v"].set(185.0)

    def build_center_panel(self, parent):
        ttk.Label(parent, text="Hasil & Bidang Citra", style="Header.TLabel").pack(anchor="w", pady=(0, 10))
        
        # Panel Output Text
        self.result_frame = ttk.LabelFrame(parent, text="Kalkulasi Real-time", padding=10)
        self.result_frame.pack(fill=tk.X, pady=(0, 10))

        self.lbl_gsd = ttk.Label(self.result_frame, text="GSD: -")
        self.lbl_gsd.pack(anchor="w", pady=2)
        
        self.lbl_offset_px = ttk.Label(self.result_frame, text="Offset Piksel: -")
        self.lbl_offset_px.pack(anchor="w", pady=2)

        self.lbl_offset_m = ttk.Label(self.result_frame, text="Offset Meter (ENU): -")
        self.lbl_offset_m.pack(anchor="w", pady=2)

        ttk.Separator(self.result_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        self.lbl_target_lat = ttk.Label(self.result_frame, text="Lat Target: -", style="Result.TLabel")
        self.lbl_target_lat.pack(anchor="w", pady=2)
        self.lbl_target_lon = ttk.Label(self.result_frame, text="Lon Target: -", style="Result.TLabel")
        self.lbl_target_lon.pack(anchor="w", pady=2)
        
        self.lbl_warning = ttk.Label(self.result_frame, text="", style="Warning.TLabel")
        self.lbl_warning.pack(anchor="w", pady=(5,0))

        # Panel Visualisasi Frame Kamera
        self.cam_frame = ttk.LabelFrame(parent, text="Visualisasi Frame Kamera (u, v)", padding=10)
        self.cam_frame.pack(fill=tk.BOTH, expand=True)

        self.cam_canvas = tk.Canvas(self.cam_frame, bg="#eef2f3", highlightthickness=1, highlightbackground="#ccc")
        self.cam_canvas.pack(pady=10, fill=tk.BOTH, expand=True)
        
        # Mouse click pada kamera untuk pindah koordinat
        self.cam_canvas.bind("<Button-1>", self.on_camera_click)
        self.cam_canvas.bind("<B1-Motion>", self.on_camera_click)

    def build_right_panel(self, parent):
        ttk.Label(parent, text="Peta Lapangan / Ground (ENU)", style="Header.TLabel").pack(anchor="w", pady=(0, 10))
        
        self.map_frame = ttk.LabelFrame(parent, text="Proyeksi ke Tanah (Top-Down View)", padding=10)
        self.map_frame.pack(fill=tk.BOTH, expand=True)

        self.map_canvas = tk.Canvas(self.map_frame, bg="#ffffff", highlightthickness=1, highlightbackground="#ccc")
        self.map_canvas.pack(pady=10, fill=tk.BOTH, expand=True)

    def on_camera_click(self, event):
        """Memungkinkan user mengklik canvas kamera untuk memindahkan target."""
        cw = self.cam_canvas.winfo_width()
        ch = self.cam_canvas.winfo_height()
        w = self.vars["w_frame"].get()
        h = self.vars["h_frame"].get()
        
        if cw > 1 and ch > 1 and w > 0 and h > 0:
            u = (event.x / cw) * w
            v = (event.y / ch) * h
            
            # Batasi di dalam frame
            u = max(0, min(u, w))
            v = max(0, min(v, h))
            
            self.vars["u"].set(round(u, 1))
            self.vars["v"].set(round(v, 1))

    def calculate_and_draw(self):
        try:
            # Ambil nilai dari input UI
            fov = self.vars["fov"].get()
            heading = self.vars["heading"].get()
            altitude = self.vars["altitude"].get()
            w = self.vars["w_frame"].get()
            h = self.vars["h_frame"].get()
            lat0 = self.vars["lat0"].get()
            lon0 = self.vars["lon0"].get()
            u = self.vars["u"].get()
            v = self.vars["v"].get()

            # Cegah error division by zero atau nilai tidak rasional
            if w <= 0 or h <= 0 or fov <= 0 or fov >= 180 or altitude <= 0:
                return

            # Panggil logika inti
            res = Geolocator.calculate(fov, heading, altitude, w, h, lat0, lon0, u, v)

            # Update Label Output
            self.lbl_gsd.config(text=f"GSD: {res.gsd:.6f} m/px")
            self.lbl_offset_px.config(text=f"Offset Piksel (Δu, Δv): ({res.dx_px:.1f}, {res.dy_px:.1f}) px")
            self.lbl_offset_m.config(text=f"Offset Meter ENU (E, N): ({res.dx_east:.3f} m, {res.dy_north:.3f} m)")
            self.lbl_target_lat.config(text=f"Lat Target: {res.lat_target:.15f}°")
            self.lbl_target_lon.config(text=f"Lon Target: {res.lon_target:.15f}°")

            # Cek status target di luar frame
            if u < 0 or u > w or v < 0 or v > h:
                self.lbl_warning.config(text="⚠ Peringatan: Posisi piksel berada di luar resolusi frame!")
            else:
                self.lbl_warning.config(text="")

            # Redraw Canvas
            self.draw_camera(w, h, u, v)
            self.draw_map(res.dx_east, res.dy_north, heading, altitude, fov, w, h)

        except tk.TclError:
            pass # Abaikan error sementara saat input kosong/sedang diketik

    def draw_camera(self, w_frame, h_frame, u, v):
        self.cam_canvas.delete("all")
        cw = self.cam_canvas.winfo_width()
        ch = self.cam_canvas.winfo_height()
        
        # Fallback jika canvas belum terender
        if cw <= 1: cw, ch = self.cam_canvas_w, self.cam_canvas_h
        else: self.cam_canvas_w, self.cam_canvas_h = cw, ch

        cx, cy = cw / 2, ch / 2

        # 1. Garis tengah crosshair (abu-abu)
        self.cam_canvas.create_line(0, cy, cw, cy, fill="#b0bec5", dash=(4,2))
        self.cam_canvas.create_line(cx, 0, cx, ch, fill="#b0bec5", dash=(4,2))
        self.cam_canvas.create_text(cx + 15, cy + 10, text="Pusat Kamera", fill="#78909c", font=("Segoe UI", 8))

        # 2. Skalakan koordinat objek ke ukuran canvas (UI)
        scale_x = cw / w_frame
        scale_y = ch / h_frame
        tx, ty = u * scale_x, v * scale_y
        
        # 3. Warna berdasarkan status
        is_outside = (u < 0 or u > w_frame or v < 0 or v > h_frame)
        color = "#e67e22" if is_outside else "#e74c3c"
        text = "Objek (Luar)" if is_outside else "Objek"

        # 4. Gambar Objek
        r = 6
        self.cam_canvas.create_oval(tx - r, ty - r, tx + r, ty + r, fill=color, outline="#c0392b", width=2)
        self.cam_canvas.create_text(tx + 15, ty - 12, text=text, fill=color, font=("Segoe UI", 9, "bold"))
        
        # 5. Panduan klik
        self.cam_canvas.create_text(10, 10, text="*Klik area ini untuk memindahkan objek", fill="#999", anchor="nw", font=("Segoe UI", 8, "italic"))

    def draw_map(self, dx_east, dy_north, heading, alt, fov, w, h):
        self.map_canvas.delete("all")
        cw = self.map_canvas.winfo_width()
        ch = self.map_canvas.winfo_height()
        
        if cw <= 1: cw, ch = self.map_canvas_w, self.map_canvas_h
        else: self.map_canvas_w, self.map_canvas_h = cw, ch
            
        cx, cy = cw / 2, ch / 2

        # 1. Garis referensi Utara (N) & Timur (E)
        self.map_canvas.create_line(cx, 0, cx, ch, fill="#e0e0e0")
        self.map_canvas.create_line(0, cy, cw, cy, fill="#e0e0e0")
        
        self.map_canvas.create_text(cx, 15, text="N (Utara Geografis)", fill="#9e9e9e", font=("Segoe UI", 9))
        self.map_canvas.create_text(cw - 45, cy - 10, text="E (Timur)", fill="#9e9e9e", font=("Segoe UI", 9))

        # 2. Dynamic Scaling (Pixel per meter)
        # Menghitung seberapa jauh drone bisa melihat dalam meter
        gsd = (2 * alt * math.tan(math.radians(fov / 2.0))) / w
        footprint_w = w * gsd
        footprint_h = h * gsd
        
        # Jarak maksimum render adalah diagonal footprint ditambah padding
        max_dist = max(footprint_w, footprint_h) * 1.5 
        if max_dist == 0: max_dist = 50
        
        ppm = min(cw, ch) / (max_dist * 2) # pixels per meter

        # 3. Orientasi Kamera UAV (Heading Arrow)
        arrow_len = 35
        hrad = math.radians(heading)
        hx = cx + arrow_len * math.sin(hrad)
        # Sumbu Y Tkinter terbalik (0 di atas), sehingga komponen Utara (cos) dikurangi
        hy = cy - arrow_len * math.cos(hrad) 
        
        self.map_canvas.create_line(cx, cy, hx, hy, arrow=tk.LAST, fill="#2980b9", width=3)

        # 4. Gambar Drone (Pusat Koordinat)
        r_drone = 8
        self.map_canvas.create_oval(cx - r_drone, cy - r_drone, cx + r_drone, cy + r_drone, fill="#3498db", outline="#2980b9", width=2)
        self.map_canvas.create_text(cx + 20, cy + 20, text="UAV", fill="#2980b9", font=("Segoe UI", 9, "bold"))
        
        # 5. Gambar Target
        # Sumbu East positif ke Kanan (+X)
        # Sumbu North positif ke Atas (-Y dalam Tkinter)
        tx = cx + (dx_east * ppm)
        ty = cy - (dy_north * ppm)
        
        # Garis hubung Drone-Target
        self.map_canvas.create_line(cx, cy, tx, ty, fill="#ffcccc", dash=(4,2))
        
        r_target = 6
        self.map_canvas.create_oval(tx - r_target, ty - r_target, tx + r_target, ty + r_target, fill="#e74c3c", outline="#c0392b", width=2)
        self.map_canvas.create_text(tx + 20, ty - 15, text="Target", fill="#e74c3c", font=("Segoe UI", 9, "bold"))
        
        # 6. Indikator Skala (Kiri Bawah)
        scale_px = 50 # Panjang garis referensi dalam pixel
        scale_meters = scale_px / ppm
        
        margin_x = 15
        margin_y = ch - 25
        self.map_canvas.create_line(margin_x, margin_y, margin_x + scale_px, margin_y, fill="#333", width=2)
        self.map_canvas.create_line(margin_x, margin_y - 5, margin_x, margin_y + 5, fill="#333", width=2)
        self.map_canvas.create_line(margin_x + scale_px, margin_y - 5, margin_x + scale_px, margin_y + 5, fill="#333", width=2)
        self.map_canvas.create_text(margin_x + (scale_px/2), margin_y - 12, text=f"{scale_meters:.1f} m", font=("Segoe UI", 8, "bold"), fill="#333")

if __name__ == "__main__":
    root = tk.Tk()
    app = UAVGeolocationApp(root)
    root.mainloop()