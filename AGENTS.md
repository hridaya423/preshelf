# PreShelf

Input is a single shelf photo, not video; the video plan in `docs/plans/2026-10-03-shelfproof-phase1.md` is historical. Hobby/hackathon project: noncommercial model licences are acceptable.

- Tests: `uv run pytest -q`.
- Browser app: `uv run modal serve shelfproof/app.py` (hot-reloads on save; the dev URL `https://hridayahoney--shelfproof-web-dev.modal.run` only works while it runs, and returns `modal-http: invalid function call` for a few seconds during reloads).
- CLI: `uv run modal run shelfproof/app.py --image samples/shelf.png` writes `out/<job>.glb`, `.scene.json`, `.ply`.
- Default 3D: MoGe-2 ViT-L normal (`Ruicheng/moge-2-vitl-normal`, pinned revision + MoGe commit in `app.py`) on L4 → `shelfproof/mesh.py` builds an unlit mesh textured with the full-resolution `source.png`. ~20 s/job, ~1 s inference. Depth jumps are cut (edge_threshold 0.04), not bridged. Legacy Depth-Anything-Small splat (`scene.ply`) is kept only for comparison.
- Verified mesh job: `9fdc83856ba9` (`/?job=9fdc83856ba9`).
- Readable package text is capped by the uploaded photo's resolution; never "sharpen" text generatively.
- Jobs live on the `shelfproof-jobs` Modal Volume: `reload()` before reading another container's writes, `commit()` after writing. `mesh.glb` is written last and is the done marker for new jobs.
- Secrets: `RUNWARE_API_KEY`, `REACTOR_API_KEY` in `.env` (gitignored), passed to Modal via `Secret.from_dotenv`. Never print or return them.
- Phase 2 (packaging lab): SAM 2.1 segmentation → Runware packshot (default GPT-Image-2.5 Sunburst `openai:gpt-image@2.5-sunburst`, transparent PNG; alt Nano Banana Pro `google:4@2`) → Sunburst mask-edit of a shelf context crop, pasted back only inside the dilated product mask (fallback: deterministic composite). `shelf_K.png` is source-sized, so the viewer swaps it in as the mesh texture ("View on 3D shelf"). Verified set: job `9fdc83856ba9`, product `8e2750fd`, set `4d30ee12` (~$0.19 for 2 variants). Code: `packaging.py` (pure), `packaging_api.py` (routes + contract docstring), `static/packaging.js`.
- Phase 3 (placement test, DeepGaze IIE): `placement*.py`, `static/placement.js` — built in a separate session.
- Browser checks: agent-browser with a unique `--session`, absolute paths for uploads; save screenshots under `samples/` (`out/` is gitignored and unreadable to tools).
