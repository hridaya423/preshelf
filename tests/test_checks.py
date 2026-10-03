from pathlib import Path

import pytest

from shelfproof.checks import find_config, registration_error


def test_no_frames_is_an_error():
    assert "No frames" in registration_error(0, 0)


def test_low_registration_is_an_error():
    msg = registration_error(300, 120)
    assert "120 of 300" in msg


def test_good_registration_passes():
    assert registration_error(300, 290) is None


def test_find_config_returns_single_match(tmp_path: Path):
    cfg = tmp_path / "data" / "splatfacto" / "2026-10-03_120000" / "config.yml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("x")
    assert find_config(tmp_path) == cfg


def test_find_config_requires_exactly_one(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        find_config(tmp_path)
