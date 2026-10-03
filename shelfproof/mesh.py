import warnings

import numpy as np


def _depth_edges(depth: np.ndarray, valid: np.ndarray, rtol: float) -> np.ndarray:
    filled = np.where(valid, depth, np.nan)
    padded = np.pad(filled, 1, mode="edge")
    h, w = depth.shape
    windows = np.stack([padded[i:i + h, j:j + w] for i in range(3) for j in range(3)])
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        spread = np.nanmax(windows, axis=0) - np.nanmin(windows, axis=0)
        return valid & (spread / depth > rtol)


def build_mesh(points: np.ndarray, mask: np.ndarray, intrinsics: np.ndarray, source_size, edge_threshold: float = 0.04) -> dict:
    h, w = mask.shape
    if points.shape != (h, w, 3) or np.asarray(intrinsics).shape != (3, 3) or min(h, w) < 2:
        raise ValueError("Points, mask and intrinsics have inconsistent shapes.")
    depth = points[..., 2]
    valid = mask.astype(bool) & np.isfinite(points).all(-1) & (depth > 0)
    keep = valid & ~_depth_edges(depth, valid, edge_threshold)

    index = np.full((h, w), -1, dtype=np.int64)
    index[keep] = np.arange(keep.sum())
    tl, tr, bl, br = index[:-1, :-1], index[:-1, 1:], index[1:, :-1], index[1:, 1:]
    quads = (tl >= 0) & (tr >= 0) & (bl >= 0) & (br >= 0)
    faces = np.concatenate([
        np.stack([tl[quads], bl[quads], tr[quads]], -1),
        np.stack([bl[quads], br[quads], tr[quads]], -1),
    ]).astype(np.int32)
    if not len(faces):
        raise ValueError("No usable surface was estimated for this image.")

    rows, cols = np.nonzero(keep)
    vertices = (points[keep] * [1, -1, -1]).astype(np.float32)
    uvs = np.stack([(cols + 0.5) / w, 1 - (rows + 0.5) / h], -1).astype(np.float32)
    return {
        "vertices": vertices,
        "faces": faces,
        "uvs": uvs,
        "metadata": {
            "source_size": [int(source_size[0]), int(source_size[1])],
            "geometry_size": [w, h],
            "intrinsics": np.asarray(intrinsics, dtype=float).round(6).tolist(),
            "camera": {"position": [0, 0, 0], "target": [0, 0, float(np.median(vertices[:, 2]))], "up": [0, 1, 0]},
            "vertex_count": int(len(vertices)),
            "triangle_count": int(len(faces)),
            "edge_threshold": edge_threshold,
        },
    }
