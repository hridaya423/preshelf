from pathlib import Path

MIN_POSED_RATIO = 0.6


def registration_error(n_images: int, n_posed: int) -> str | None:
    if n_images == 0:
        return "No frames could be extracted from the video."
    if n_posed / n_images < MIN_POSED_RATIO:
        return (
            f"Camera alignment placed only {n_posed} of {n_images} frames. "
            "Re-film moving slowly sideways along the shelf, keeping it in view the whole time."
        )
    return None


def find_config(out_dir: Path) -> Path:
    configs = sorted(out_dir.glob("**/config.yml"))
    if len(configs) != 1:
        raise FileNotFoundError(f"Expected one config.yml under {out_dir}, found {len(configs)}")
    return configs[0]
