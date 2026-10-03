# PreShelf research and phase boundaries

Research checked 3 October 2026. This document separates verified capabilities from proposed implementation choices. No reconstruction, model training, or deployment has been performed.

## Decisions from the conversation

- Phase 1 is an internal milestone: upload a video of one shelf bay, reconstruct it, and navigate the actual result in a browser.
- Processing must be real. A prepared scene may help development but cannot substitute for the upload pipeline.
- Cloud GPU processing is available. The user named Modal, Runware, and Reactor and left the provider choice open.
- Do not constrain the plan around team size or a guessed remaining time budget.
- A new shelf capture may not be available. Find public input footage and document its source and permission.
- Phase 2 adds packaging variations; phase 3 adds market mapping; phase 4 adds customer simulation and placement comparisons.
- The eventual hackathon submission goes beyond phase 1. The organizer's brief asks for retail AI using behavioral data; participant-only data and rules have not been supplied. [Organizer page](https://luma.com/hdf7uc43).

## Recommended reconstruction route

Use Modal to run an existing reconstruction pipeline: video -> sampled frames -> COLMAP camera alignment -> Nerfstudio Splatfacto -> Gaussian PLY -> Spark/Three.js viewer. Modal provides compute, not a reconstruction model. Keep one GPU job, one file store, and one browser flow.

Nerfstudio documents video preprocessing, Splatfacto training, and Gaussian export. Its documentation estimates roughly 6 GB GPU memory for the default method and 12 GB for the larger method; these are not guarantees for arbitrary shelf captures. Start with one 24 GB GPU and measure the actual job before changing hardware. [Video input](https://docs.nerf.studio/quickstart/custom_dataset.html), [Splatfacto](https://docs.nerf.studio/nerfology/methods/splat.html), [installation and Docker image](https://docs.nerf.studio/quickstart/installation.html).

The local machine is an M4 Pro with 48 GB memory and a 20-core Apple GPU. The project directory was empty when inspected. Node, Python, FFmpeg, Git, pnpm, and uv are available; COLMAP, gsplat, and Blender were not on PATH. The practical local alternative is COLMAP plus Brush. Brush supports macOS and takes COLMAP/Nerfstudio datasets; it does not remove the camera-alignment step. Use it only if the chosen cloud path proves unsuitable, rather than maintaining both. [Brush](https://github.com/ArthurBrussee/brush), [COLMAP installation](https://colmap.github.io/install.html).

### Corrections to the original notes

| Claim or option | What the evidence supports | Decision |
| --- | --- | --- |
| VGGT makes the splat immediately | VGGT estimates cameras, depth, points, and tracks. Its COLMAP export still needs a splat trainer. Model checkpoints have different license terms. | An alternative pose initializer if COLMAP demonstrably fails; not a second default pipeline. [VGGT](https://github.com/facebookresearch/vggt) |
| LongSplat is an easy turnkey video API | Research implementation with CUDA dependencies and its own representation. Conversion is needed for common viewers. License limits use to noncommercial research/evaluation. | Keep as research reference. [Code](https://github.com/NVlabs/LongSplat), [license](https://github.com/NVlabs/LongSplat/blob/main/LICENSE.md) |
| One photo is equivalent to a moving video | Single-image methods infer unseen structure. They cannot observe hidden product faces or establish shelf clearance. | Exclude single-photo reconstruction from phase 1. Accept it later only with an explicit inferred-geometry label. |
| Apple SHARP solves single-photo input | Predicts splats for nearby novel views; the model license excludes product development. | Do not select as the default product dependency. [SHARP](https://github.com/apple-aiml-research/ml-sharp), [model terms](https://github.com/apple-aiml-research/ml-sharp/blob/main/LICENSE_MODEL) |
| Any image-to-3D endpoint reconstructs a shop | Runware's Meshy guidance recommends an isolated object; Rodin's multiple views are views of one object and infer hidden geometry. | Useful for later product assets, not established as faithful shelf-scene reconstruction. [Meshy](https://runware.ai/docs/models/meshy-6/guides/generating-3d), [Rodin](https://runware.ai/docs/models/hyper3d-rodin-gen-2/guides/image-and-text-to-3d) |
| A splat is an editable inventory | A visual splat does not inherently provide SKU identity, separate product objects, watertight surfaces, or dimensions. | Retain frames and camera data; add product geometry and semantics only when the next phase needs them. |

Polycam has hosted reconstruction and PLY export, but its reconstruction API requires approved Enterprise access and credits; splat API submissions require its frame metadata format. Do not plan around unverified immediate API access. [Upload tool](https://poly.cam/tools/gaussian-splatting), [API](https://poly.cam/docs/api/reconstruction).

## What each phase should deliver

| Phase | Smallest complete outcome | Evidence needed before claiming success |
| --- | --- | --- |
| 1. Capture | A submitted shelf video produces its own navigable splat, with reset and download. | Run the complete path on two distinct inputs, inspect actual results from several nearby views, and show a useful failure for an unusable clip. |
| 2. Packaging | Compare two controlled package variants in the same shelf view. | Preserve factual label content, hold camera/lighting/placement fixed, and inspect the changed package at the intended viewing distance. |
| 3. Market mapping | Map one product category by observed price, attributes, claims, and competitors with source dates. | Every factual field has provenance; missing values remain missing. Category gaps are hypotheses, not measured demand. |
| 4. Behavior | Compare baseline and changed placement under explicit shopping missions and model assumptions. | Separate exposure, attention, consideration, and choice; validate each predicted quantity against matching observations. |

For phase 2, begin with one manually selected product and one simple package shape. A textured box or cylinder over a designated slot is manageable. Removing the original product from a splat, filling the newly exposed background, and making the replacement consistent across views is a separate problem. A first version can compare controlled 2D shelf renders while preserving the 3D viewer for context; do not imply that editing arbitrary splats is already solved.

"Does the product fit?" needs two separate answers. Physical fit requires shelf and package dimensions, scale calibration, and clearance. Assortment fit requires category, price, attribute, and competitor data. Neither follows from a plausible-looking reconstruction. Monocular reconstruction should report arbitrary scene units until a known measurement establishes scale.

## Behavioral resources worth using

### Movement and dwell

[Standard Day-in-the-Life](https://huggingface.co/datasets/standard-cognition/day-in-the-life) is a useful movement dataset. The research description reports 1,791 trajectories, while the current publisher card reports 1,817 tracks and 2,109,812 observations. Use the versioned downloaded release as the count of record. It covers one store-day, positions and movement aligned with a metric layout. CSV files include 24-joint poses; Parquet excludes pose. It does not provide imagery, demographics, purchases, or persistent customer identity.

Start with empirical shelf-transition probabilities and dwell-time distributions, conditional on an explicit mission only where labels support it. Do not begin with a Transformer or GRU. This dataset cannot teach a model how low-income customers choose a new drink package. Its [license](https://huggingface.co/datasets/standard-cognition/day-in-the-life/blob/main/LICENSE) has research/noncommercial conditions and separate commercial provisions; inspect the exact terms for the intended use.

### Attention

[Retail Gaze](https://github.com/PrimeshShamilka/RetailGazeDataset) contains 3,922 images from 12 camera angles with head boxes, gaze points, and product-region masks. Participants followed specified looking patterns. Its target is estimating the gaze of a person visible in the image, not predicting the preferences of a hypothetical shopper. No explicit repository license was found. [Author paper](https://www.cs.odu.edu/~sampath/publications/conferences/2022/DASA-2022-Senarath.pdf).

The [McGill convenience-store search study](https://www.sciencedirect.com/science/article/pii/S1077314224002108) matches the original notes: 108 videos from 36 participants searching for orange juice, KitKat, and canned tuna, with gaze measurements and a survey. It is relevant to goal-conditioned search. The data are described as password protected and available on request; unrestricted download and license were not verified. Do not make it a hackathon dependency.

[UNISAL](https://github.com/rdroste/unisal) provides author code, pretrained weights, and image/video saliency inference with an Apache-2.0 repository license. It is a practical later baseline for a predicted-attention overlay. Check the checkpoint and training-data terms as well. Evaluate it on shelf imagery before making performance claims.

[DeepGaze](https://github.com/matthias-k/DeepGaze) offers pretrained spatial-attention and scanpath models. Its newer MSDB adaptation fits a small set of dataset parameters with the backbone frozen, an example of calibration being smaller than full fine-tuning. Licensing was not clear from the repository, and a [commercial-license question](https://github.com/matthias-k/DeepGaze/issues/15) remains relevant. Treat it as a research comparator until permission is resolved.

A saliency density integrated over a product mask is a relative allocation of modeled visual attention. It is not automatically the probability that a shopper notices that SKU at least once, likes it, considers it, or buys it. Define the displayed statistic and keep the camera, image size, viewing conditions, and aggregation constant between variants.

### Choice and packaging preference

[Chandon et al. (2009)](https://journals.sagepub.com/doi/full/10.1509/jmkg.73.6.1) experimentally varied shelf displays and studied attention and brand evaluation. Facings and placement influenced attention, but attention improvements did not always carry through to evaluation. This supports separate attention and choice models. Do not turn the paper's effects into universal percentage multipliers for every shelf, category, or population.

Use [conditional logit](https://eml.berkeley.edu/books/choice2.html) as the first choice baseline once actual choices exist. Inputs can include price, pack size, attributes, prior brand use, and experimental condition. Include an outside/no-purchase option. Consider mixed logit or partially pooled segment effects only after simpler models show a measurable limitation on held-out data. Estimating these coefficients is model fitting; it does not require language-model fine-tuning.

An [attentional drift-diffusion model](https://pmc.ncbi.nlm.nih.gov/articles/PMC3374478/) is a plausible later research direction when gaze sequences, valuations, response times, and choices are available. The cited work concerns simpler purchasing decisions. It is excessive for a prototype that has none of those measurements yet.

[Dunnhumby's Complete Journey](https://www.dunnhumby.com/source-files/) represents two years of transactions from 2,500 households, with customer attributes for some households. It is useful for learning transaction-analysis and choice workflows. It does not join modern UK package images to measured shelf gaze. The same page separately offers explicitly synthetic data; do not confuse that dataset with observed transactions or assume all its files share the same provenance and terms.

For phase 2 preference evidence, run a randomized human comparison of two shelf renders, holding the rest of the scene fixed. Record choice, a neither option, and optionally confidence or reason. A small convenience sample can debug the experiment and produce exploratory results; it cannot establish representative demographic preference or sales uplift. Determine sample size from the decision and desired precision rather than inventing a universal minimum.

### Demographic simulation

Begin with shopping missions: finding a named brand, finding the cheapest qualifying option, or browsing a category. Treat their weights as user-specified scenarios until measured. Age, income, and lifestyle effects require attributes linked to the same people's observed attention and choices. Separate unrelated movement, gaze, and purchase datasets cannot create that joint evidence by being joined on invented personas.

The [interview-grounded agent study](https://hai.stanford.edu/policy/simulating-human-behavior-with-ai-agents?sf225800334=1) used extensive interviews with 1,052 people and evaluated surveys, games, and experiments. It does not validate demographic prompts as supermarket customers. Use an LLM to extract product attributes, explain model results, and suggest hypotheses, not to manufacture consumer preference percentages.

## Market intelligence data

| Source | Useful fields | Boundary |
| --- | --- | --- |
| Organizer-provided data | Potential product attributes and behavioral framework | Inspect actual schemas, access, and definitions before assuming availability. [Event brief](https://luma.com/hdf7uc43) |
| Open Food Facts | Barcodes, brands, categories, ingredients, nutrition, labels, images | Catalogue coverage and correctness vary. ODbL/database and image attribution obligations apply. [API](https://openfoodfacts.github.io/openfoodfacts-server/api/), [terms](https://openfoodfacts.github.io/openfoodfacts-server/api/tutorials/license-be-on-the-legal-side/) |
| Open Prices | Dated price observations | Verify local category coverage. Normalize currency, quantity, and promotion status before comparison. [API](https://github.com/openfoodfacts/open-prices/blob/main/API.md) |
| Defra Family Food | Category expenditure and quantities by income, age, region, and household composition | Public CSV/ODS; category-level population context, not SKU preference. FYE 2025 tables were available when checked. [Datasets](https://www.gov.uk/government/statistical-data-sets/family-food-datasets) |
| FSA Food and You 2 | Dietary practices, shopping, food security, labeling and attitudes | Survey evidence, not measured shelf attention or transactions. [Collection](https://www.gov.uk/government/collections/food-and-you-2) |

Start with one category and a sourced comparison table. Plot price per unit against one meaningful attribute, with visible filters for claims and product type. Embedding clusters can help browse packaging similarity, but a visually empty cluster is not evidence of unmet demand. Date every price and source; preserve the distinction between observed product facts, reported consumer attitudes, and model assumptions.

## Training and validation decisions

1. Phase 1 optimizes a representation of each scene. It does not train a shopper model or fine-tune a language model.
2. Phase 2 may use an existing package-image generator and a pretrained saliency model. Prefer templates or constrained artwork placement for factual label content.
3. Phase 3 begins with retrieval, normalization, and sourced analysis. Train nothing unless a measured extraction/classification gap warrants it.
4. Phase 4 begins with simple transition/dwell models and a choice baseline. Fine-tune a visual model only after measuring failure on labeled shelf data that the team can legally use.

Split gaze data by participant and scene, not random neighboring frames. Compare attention against simple center/area baselines, using held-out fixation likelihood or suitable saliency metrics. Assess choice with held-out log loss and calibration against a simple category/price baseline. Validate claimed placement or packaging effects with randomized interventions; good observational prediction alone does not identify their causal effects.

Use the same sampled missions and random seeds in baseline and intervention runs to reduce comparison noise. Report variation across repeated runs and sensitivity to assumptions. A simulation interval describes the chosen model's uncertainty; it does not automatically cover uncertainty about real shoppers.

## Public footage for phase 1

The best verified open test input found is [SLAM&Render](https://github.com/samuel-cerezo/SLAM-Render), with RGB frames, depth, camera information, and ground-truth trajectories. Setup 3 contains opaque supermarket goods. These are tabletop arrangements, not a full grocery shelf. The [dataset record](https://zenodo.org/records/15000694) and repository specify CC BY 4.0.

- [Natural-light training capture](https://zenodo.org/api/records/15000694/files/3-natural-tr.zip/content), approximately 1.73 GB.
- [Separate test trajectory](https://zenodo.org/api/records/15000694/files/3-natural-tt.zip/content), approximately 1.31 GB.

Use consecutive RGB frames from one camera and one capture; inspect the archive before choosing its image path. For the video-upload test, encode that sequence as a clip and make the pipeline recover poses itself. Do not quietly feed it ground-truth poses and claim success at reconstruction from an unknown video. Keep the separate trajectory for independent visual evaluation once camera conventions are established.

The project's downloader uses `setup-3-natural-train`; the README example omits `setup-`. Its linked `data/README.md` was unavailable when checked. Direct archive links avoid these documentation problems. Files have not been downloaded or visually inspected in this planning session.

No better, clearly licensed, static grocery-shelf sweep was verified. Random shelf photographs, fixed CCTV, edited store-tour videos, or already-rendered splat videos are not equivalent inputs. Public visibility alone does not establish reuse permission. Use a single uninterrupted segment with translational movement, overlapping views, readable packaging, and few moving people. A final real-shelf acceptance test remains necessary.

## Planning checkpoint

The product decisions needed for a first phase are settled. The implementation plan chooses a local browser interface with a Modal GPU worker, preserves reconstruction artifacts for later phases, and treats footage qualification plus container compatibility as the first technical gates. The user asked for planning, so no dependencies were installed and no paid jobs were started.
