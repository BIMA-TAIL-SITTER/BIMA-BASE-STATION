import cv2
import numpy as np


# ════════════════════════════════════════════════════════════════
#  PAPER 1 — He et al., Drones 2024
#  Metode: BRISQUE Score + Interval-based Redundancy Removal
# ════════════════════════════════════════════════════════════════

def compute_brisque_score(image: np.ndarray) -> float:
    """
    Simplified BRISQUE (Blind/Referenceless Image Spatial Quality Evaluator).
    Paper asli pakai SVM regression; versi ini pakai statistical proxy
    yang mengikuti logika MSCN coefficient dari paper He 2024 Section 2.3.2.
    
    Lower score = better quality (sesuai paper).
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float64)

    # Step 1: Local Mean Subtraction + Divisive Normalization (Eq. 6-8 paper)
    # Gaussian window kernel
    kernel_size = 7
    sigma = 7 / 6.0
    local_mean = cv2.GaussianBlur(gray, (kernel_size, kernel_size), sigma)
    local_var  = cv2.GaussianBlur(
        (gray - local_mean) ** 2, (kernel_size, kernel_size), sigma
    )
    local_std = np.sqrt(local_var) + 1.0  # C=1 mencegah div-by-zero (Eq. 6)

    # MSCN coefficients (Mean Subtracted Contrast Normalized)
    mscn = (gray - local_mean) / local_std

    # Step 2: Asymmetric Generalized Gaussian Distribution (AGGD) features
    # — variasi kiri dan kanan distribusi MSCN
    mscn_flat   = mscn.flatten()
    left_vals   = mscn_flat[mscn_flat < 0]
    right_vals  = mscn_flat[mscn_flat >= 0]

    left_var  = np.var(left_vals)  if len(left_vals)  > 0 else 0
    right_var = np.var(right_vals) if len(right_vals) > 0 else 0
    asymmetry = abs(left_var - right_var)  # asimetri distribusi

    # Step 3: Produk MSCN dengan tetangga (4 arah: H, V, diagonal)
    # — menangkap distorsi struktural (sesuai paper Section 2.3.2)
    pairs = [
        mscn[:, :-1] * mscn[:, 1:],   # horizontal
        mscn[:-1, :] * mscn[1:, :],   # vertical
        mscn[:-1, :-1] * mscn[1:, 1:],  # diagonal utama
        mscn[:-1, 1:] * mscn[1:, :-1],  # diagonal sekunder
    ]
    pair_stats = [np.var(p) for p in pairs]
    structural_distortion = np.mean(pair_stats)

    # Score gabungan — proxy BRISQUE (lower = better quality)
    score = asymmetry * 10 + structural_distortion * 100
    return float(score)


def redundancy_removal_he2024(
    images: list,
    interval: int = 3
) -> list:
    """
    Implementasi Paper 1 — He et al. (Drones 2024), Section 2.4.
    
    Algoritma:
      1. Hitung BRISQUE score semua frame
      2. Bagi ke interval ukuran `interval`
      3. Dalam setiap interval, pertahankan frame dengan score TERENDAH
      4. Return list index frame yang lolos

    Parameters
    ----------
    images   : list of BGR np.ndarray
    interval : ukuran redundancy interval (i pada paper, default=3)

    Returns
    -------
    selected_indices : list of int — indeks frame yang dipertahankan
    """
    print(f"\n[Paper 1 — He 2024] Menghitung BRISQUE scores ({len(images)} frame)...")
    scores = []
    for idx, img in enumerate(images):
        s = compute_brisque_score(img)
        scores.append(s)
        print(f"  Frame {idx:03d}: BRISQUE = {s:.4f}")

    # Seleksi: tiap interval, pertahankan 1 frame terbaik (score terendah)
    # Paper: "Retain the image with the lowest quality score within (i+1)"
    selected = []
    for start in range(0, len(images), interval + 1):
        end = min(start + interval + 1, len(images))
        group = list(range(start, end))
        best  = min(group, key=lambda i: scores[i])
        selected.append(best)
        print(f"  Interval [{start}-{end-1}]: pilih frame {best} "
              f"(score={scores[best]:.4f})")

    print(f"[He 2024] {len(images)} frame → {len(selected)} frame terpilih "
          f"(reduksi {(1 - len(selected)/len(images))*100:.1f}%)")
    return selected


# ════════════════════════════════════════════════════════════════
#  PAPER 2 — Yuan et al., SCIRP 2024
#  Metode: Two-Stage Keyframe Selection
#          Stage 1: Overlap Rate + Lagrange Interpolation
#          Stage 2: Remapping Error Minimization
# ════════════════════════════════════════════════════════════════

def compute_overlap_rate(img_a: np.ndarray, img_b: np.ndarray) -> float:
    """
    Hitung overlap rate antara dua frame via feature matching + homography.
    Sesuai paper Yuan 2024 Section 2.2.1:
    'calculating the similarity transformation by identifying matching points,
     then determining the overlapping region to calculate overlap rate.'
    
    Returns float in [0, 1].
    """
    detector = cv2.SIFT_create(300)
    gray_a = cv2.cvtColor(img_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(img_b, cv2.COLOR_BGR2GRAY)

    kp_a, des_a = detector.detectAndCompute(gray_a, None)
    kp_b, des_b = detector.detectAndCompute(gray_b, None)

    if des_a is None or des_b is None or len(kp_a) < 4 or len(kp_b) < 4:
        return 0.0

    matcher = cv2.BFMatcher()
    raw = matcher.knnMatch(des_a, des_b, k=2)
    good = [m for pair in raw if len(pair) == 2
            for m, n in [pair] if m.distance < 0.75 * n.distance]

    if len(good) < 4:
        return 0.0

    src = np.float32([kp_a[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kp_b[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)

    if H is None:
        return 0.0

    # Warp sudut image_a ke ruang image_b, hitung intersection area
    h_a, w_a = img_a.shape[:2]
    h_b, w_b = img_b.shape[:2]
    corners_a = np.float32([[0,0],[w_a,0],[w_a,h_a],[0,h_a]]).reshape(-1,1,2)
    warped    = cv2.perspectiveTransform(corners_a, H).reshape(-1, 2)

    # Bounding box intersection
    x_min_w = max(0, warped[:, 0].min())
    x_max_w = min(w_b, warped[:, 0].max())
    y_min_w = max(0, warped[:, 1].min())
    y_max_w = min(h_b, warped[:, 1].max())

    intersect = max(0, x_max_w - x_min_w) * max(0, y_max_w - y_min_w)
    area_b    = w_b * h_b

    return float(intersect / area_b) if area_b > 0 else 0.0


def lagrange_interpolation(x_points: list, y_points: list, x_query: float) -> float:
    """
    Lagrange polynomial interpolation (Eq. 2 dari Yuan 2024).
    
    L(x) = Σ y_i * Π_{j≠i} (x - x_j)/(x_i - x_j)
    """
    n      = len(x_points)
    result = 0.0
    for i in range(n):
        term = y_points[i]
        for j in range(n):
            if j != i:
                denom = x_points[i] - x_points[j]
                if abs(denom) < 1e-10:
                    continue
                term *= (x_query - x_points[j]) / denom
        result += term
    return result


def compute_remapping_error(
    img_ref: np.ndarray,
    img_candidate: np.ndarray
) -> float:
    """
    Hitung rata-rata remapping error (Eq. 4-5 dari Yuan 2024).
    
    mean_error = (1/n) * Σ sqrt((u - x')² + (v - y')²)
    
    di mana (x', y') = hasil reproyeksi keypoint img_ref melalui H ke img_candidate,
    dan (u, v) = posisi aktual matching point di img_candidate.
    
    Returns mean reprojection error dalam pixel.
    """
    detector = cv2.SIFT_create(300)
    gray_ref = cv2.cvtColor(img_ref,       cv2.COLOR_BGR2GRAY)
    gray_can = cv2.cvtColor(img_candidate, cv2.COLOR_BGR2GRAY)

    kp_r, des_r = detector.detectAndCompute(gray_ref, None)
    kp_c, des_c = detector.detectAndCompute(gray_can, None)

    if des_r is None or des_c is None or len(kp_r) < 4 or len(kp_c) < 4:
        return float('inf')

    matcher = cv2.BFMatcher()
    raw  = matcher.knnMatch(des_r, des_c, k=2)
    good = [m for pair in raw if len(pair) == 2
            for m, n in [pair] if m.distance < 0.75 * n.distance]

    if len(good) < 4:
        return float('inf')

    src = np.float32([kp_r[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kp_c[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)

    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    if H is None:
        return float('inf')

    # Reproyeksi: (x, y) dari ref → (x', y') di candidate via H
    reprojected = cv2.perspectiveTransform(src, H)  # (x', y')

    # Error = jarak Euclidean antara (x', y') dan (u, v) — Eq. 5
    errors = np.sqrt(
        (reprojected[:, 0, 0] - dst[:, 0, 0]) ** 2 +
        (reprojected[:, 0, 1] - dst[:, 0, 1]) ** 2
    )
    return float(np.mean(errors))


def keyframe_selection_yuan2024(
    images: list,
    overlap_threshold: float = 0.80,   # T = 80% (optimal dari paper, Section 3.1)
    remap_threshold:   float = 4.0,    # T = 4 pixel (dari paper Section 2.2.2)
    sample_interval:   int   = 75,     # jarak antar sample point (dari paper)
    max_window:        int   = 300     # window maksimum (dari paper Section 2.2.1)
) -> list:
    """
    Implementasi Paper 2 — Yuan et al. (SCIRP 2024), Section 2.2.
    
    Stage 1: Fit overlap rate curve via Lagrange polynomial,
             temukan candidate keyframe (overlap = overlap_threshold).
    Stage 2: Validasi dengan remapping error ≤ remap_threshold.
             Jika tidak lolos, cari mundur sampai ketemu frame yang lolos.
    
    Returns
    -------
    keyframe_indices : list of int
    """
    n = len(images)
    keyframes = [0]       # Frame pertama selalu jadi keyframe (sesuai paper)
    current_kf_idx = 0    # Kc — current keyframe index

    print(f"\n[Paper 2 — Yuan 2024] Memulai two-stage keyframe selection "
          f"({n} frame total)...")

    while current_kf_idx < n - 1:
        Kc_img = images[current_kf_idx]

        # ── STAGE 1: Lagrange Overlap Rate Fitting ──────────────────────────
        # Ambil 4 sample frame dalam window (Eq. 1 paper)
        window_end = min(current_kf_idx + max_window, n - 1)

        # S1 dipilih random dalam [current+1, current+S_interval]
        S1 = min(current_kf_idx + sample_interval, window_end)
        S2 = min(S1 + sample_interval, window_end)       # S2 = S1 + interval
        S3 = min((S1 + S2) // 2, window_end)             # S3 = midpoint S1,S2
        S4 = min(S2 + sample_interval, window_end)

        sample_indices = sorted(set([S1, S2, S3, S4]))
        if len(sample_indices) < 2:
            # Tidak cukup frame tersisa
            break

        # Hitung overlap rate di titik-titik sample
        print(f"\n  [Stage 1] Keyframe saat ini: {current_kf_idx}, "
              f"window: [{current_kf_idx+1}, {window_end}]")
        x_pts, y_pts = [], []
        for s_idx in sample_indices:
            ov = compute_overlap_rate(Kc_img, images[s_idx])
            x_pts.append(float(s_idx))
            y_pts.append(ov)
            print(f"    Sample frame {s_idx}: overlap = {ov:.3f}")

        # Scan kurva Lagrange untuk cari frame terakhir yang overlap ≥ threshold
        # (frame yang tepat di threshold = candidate keyframe)
        candidate_idx = None
        for fi in range(current_kf_idx + 1, window_end + 1):
            fitted_ov = lagrange_interpolation(x_pts, y_pts, float(fi))
            if fitted_ov >= overlap_threshold:
                candidate_idx = fi    # terus update, ambil yang paling jauh
            else:
                break                 # kurva sudah turun di bawah threshold

        if candidate_idx is None:
            # Semua frame sudah terlalu jauh/tidak ada overlap cukup
            print(f"  [Stage 1] Tidak ada candidate dalam window. "
                  f"Maju satu step.")
            candidate_idx = min(current_kf_idx + 1, n - 1)

        print(f"  [Stage 1] Candidate keyframe: {candidate_idx}")

        # ── STAGE 2: Remapping Error Validation ─────────────────────────────
        # Cek apakah candidate lolos threshold remapping error
        err = compute_remapping_error(Kc_img, images[candidate_idx])
        print(f"  [Stage 2] Remapping error candidate {candidate_idx}: "
              f"{err:.2f} px (threshold={remap_threshold})")

        if err <= remap_threshold:
            # Langsung diterima
            keyframes.append(candidate_idx)
            current_kf_idx = candidate_idx
            print(f"  ✅ Keyframe {candidate_idx} diterima (error {err:.2f} ≤ "
                  f"{remap_threshold})")
        else:
            # Cari mundur dari candidate ke current: cari frame pertama
            # yang memenuhi remap_threshold (sesuai paper Section 2.2.2)
            print(f"  ⚠️  Error terlalu besar, cari mundur...")
            found = False
            for back_idx in range(candidate_idx - 1, current_kf_idx, -1):
                err_back = compute_remapping_error(Kc_img, images[back_idx])
                print(f"    Frame {back_idx}: error = {err_back:.2f} px")
                if err_back <= remap_threshold:
                    keyframes.append(back_idx)
                    current_kf_idx = back_idx
                    print(f"  ✅ Keyframe {back_idx} diterima (backward search)")
                    found = True
                    break

            if not found:
                # Tidak ada yang lolos, paksa maju satu step
                next_idx = min(current_kf_idx + 1, n - 1)
                keyframes.append(next_idx)
                current_kf_idx = next_idx
                print(f"  ⚠️  Tidak ada frame lolos, paksa frame {next_idx}")

    print(f"\n[Yuan 2024] {n} frame → {len(keyframes)} keyframe "
          f"(reduksi {(1 - len(keyframes)/n)*100:.1f}%): {keyframes}")
    return keyframes