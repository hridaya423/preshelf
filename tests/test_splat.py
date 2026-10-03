import numpy as np
import pytest

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


def test_flat_depth_preserves_colours_and_finite_gaussians():
    rgb = np.full((4, 6, 3), [255, 128, 0], dtype=np.uint8)
    ply = image_to_splat_ply(rgb, np.ones((4, 6)))
    verts = np.frombuffer(ply.partition(b"end_header\n")[2], dtype=PLY_DTYPE)
    assert all(np.isfinite(verts[name]).all() for name, _ in PLY_DTYPE)
    colours = np.stack([verts[f"f_dc_{i}"] for i in range(3)], axis=-1)
    np.testing.assert_allclose((colours * 0.28209479 + 0.5) * 255, rgb.reshape(-1, 3), atol=1e-4)
    assert (verts["rot_0"] == 1).all()


@pytest.mark.parametrize("shape", [(1, 1), (2, 1)])
def test_rejects_images_too_narrow_to_reconstruct(shape):
    with pytest.raises(ValueError, match="at least 2"):
        image_to_splat_ply(np.zeros((*shape, 3), dtype=np.uint8), np.ones(shape))


def test_rejects_nonfinite_depth():
    with pytest.raises(ValueError, match="finite"):
        image_to_splat_ply(np.zeros((4, 6, 3), dtype=np.uint8), np.full((4, 6), np.nan))
