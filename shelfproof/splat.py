import numpy as np

PLY_DTYPE = [
    ("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
    ("nx", "<f4"), ("ny", "<f4"), ("nz", "<f4"),
    ("f_dc_0", "<f4"), ("f_dc_1", "<f4"), ("f_dc_2", "<f4"),
    ("opacity", "<f4"),
    ("scale_0", "<f4"), ("scale_1", "<f4"), ("scale_2", "<f4"),
    ("rot_0", "<f4"), ("rot_1", "<f4"), ("rot_2", "<f4"), ("rot_3", "<f4"),
]


def image_to_splat_ply(rgb: np.ndarray, disparity: np.ndarray) -> bytes:
    H, W, _ = rgb.shape
    d = (disparity - disparity.min()) / (disparity.max() - disparity.min() + 1e-8)
    z = 1.0 + 0.4 * (1.0 - d)

    f = W
    cx, cy = W / 2, H / 2
    u, v = np.meshgrid(np.arange(W), np.arange(H))
    x = (u - cx) / f * z
    y = -(v - cy) / f * z
    pts = np.stack([x, y, -z], axis=-1).reshape(-1, 3).astype(np.float64)
    pts -= pts.mean(axis=0)
    global_scale = 1.0 / np.abs(pts[:, 0]).max()
    pts *= global_scale

    footprint = z.reshape(-1) / f * global_scale * 1.2
    opacity = np.log(0.95 / 0.05)
    f_dc = (rgb.reshape(-1, 3).astype(np.float64) / 255.0 - 0.5) / 0.28209479

    verts = np.zeros(len(pts), dtype=PLY_DTYPE)
    verts["x"], verts["y"], verts["z"] = pts.T
    verts["f_dc_0"], verts["f_dc_1"], verts["f_dc_2"] = f_dc.T
    verts["opacity"] = opacity
    verts["scale_0"] = verts["scale_1"] = verts["scale_2"] = np.log(footprint)
    verts["rot_0"] = 1.0

    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {len(verts)}\n"
        + "".join(f"property float {name}\n" for name, _ in PLY_DTYPE)
        + "end_header\n"
    )
    return header.encode() + verts.tobytes()
