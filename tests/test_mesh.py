import numpy as np
import pytest

from shelfproof.mesh import build_mesh

K = np.array([[1.0, 0, 0.5], [0, 1.5, 0.5], [0, 0, 1]])


def plane(h=4, w=6, z=2.0):
    v, u = np.mgrid[0:h, 0:w]
    return np.stack([(u - w / 2) * 0.1, (v - h / 2) * 0.1, np.full((h, w), z)], -1).astype(np.float32)


def test_plane_becomes_full_grid_in_opengl_coords():
    mesh = build_mesh(plane(), np.ones((4, 6), bool), K, (1200, 800))
    assert mesh["vertices"].shape == (24, 3)
    assert mesh["faces"].shape == (2 * 3 * 5, 3)
    assert np.allclose(mesh["vertices"][:, 2], -2)
    assert mesh["vertices"][0, 1] > mesh["vertices"][-1, 1]
    assert np.allclose(mesh["uvs"][0], [0.5 / 6, 1 - 0.5 / 4])
    meta = mesh["metadata"]
    assert meta["source_size"] == [1200, 800] and meta["geometry_size"] == [6, 4]
    assert meta["camera"]["target"] == [0, 0, -2.0]


def test_triangles_face_the_camera():
    mesh = build_mesh(plane(), np.ones((4, 6), bool), K, (6, 4))
    a, b, c = (mesh["vertices"][mesh["faces"][:, i]] for i in range(3))
    assert (np.cross(b - a, c - a)[:, 2] > 0).all()


def test_depth_jump_is_not_bridged():
    points = plane()
    points[:, 3:, 2] = 4.0
    mesh = build_mesh(points, np.ones((4, 6), bool), K, (6, 4))
    z = mesh["vertices"][mesh["faces"]][..., 2]
    assert (np.ptp(z, axis=1) < 1e-6).all()


def test_masked_and_invalid_pixels_are_dropped():
    points = plane()
    points[0, 0] = np.nan
    mask = np.ones((4, 6), bool)
    mask[3, 5] = False
    mesh = build_mesh(points, mask, K, (6, 4))
    assert mesh["metadata"]["vertex_count"] == 22
    assert mesh["faces"].max() < 22


def test_rejects_empty_surface():
    with pytest.raises(ValueError, match="No usable surface"):
        build_mesh(plane(), np.zeros((4, 6), bool), K, (6, 4))
