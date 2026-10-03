import numpy as np

from shelfproof.splat import PLY_DTYPE, image_to_splat_ply


def make_ply():
    rng = np.random.default_rng(0)
    rgb = rng.integers(0, 256, (4, 6, 3), dtype=np.uint8)
    disparity = rng.random((4, 6)).astype(np.float64)
    return image_to_splat_ply(rgb, disparity)


def test_vertex_count_in_header():
    ply = make_ply()
    header, _, body = ply.partition(b"end_header\n")
    assert b"element vertex 24" in header
    assert len(body) == 24 * 17 * 4


def test_point_cloud_is_centred_and_unit_sized():
    ply = make_ply()
    body = ply.partition(b"end_header\n")[2]
    verts = np.frombuffer(body, dtype=PLY_DTYPE)
    xyz = np.stack([verts["x"], verts["y"], verts["z"]], axis=-1)
    assert np.abs(xyz.mean(axis=0)).max() < 1e-5
    assert np.abs(xyz[:, 0]).max() == np.float32(1.0)
