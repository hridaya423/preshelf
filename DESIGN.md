# PreShelf design direction

## How to use this guide

This is a direction for improving the interface, grounded in the October 3, 2026 concept exploration and the existing app. The images are visual concepts, not pixel specifications or evidence that an interaction works. Preserve their hierarchy and sense of care; adapt their details to real content, capabilities, and screen sizes.

The current implementation remains the source of truth for available functionality. This document describes a proposed visual direction, not an already implemented design system. It does not prescribe a framework, component library, exact font, or measured color tokens.

## Reference screens

| Reference | Status | What to carry forward |
| --- | --- | --- |
| [Shelf with selection tray](samples/ui-concepts/04-selection-tray.png) | User preferred concept 1 | A large working shelf, compact viewing tools, and a selected-product tray below the canvas. |
| [Selection inspector](samples/ui-concepts/approved-selection-inspector.png) | User preferred this for concept 2 | A shelf beside a readable product preview and a clear next action. |
| [Revised comparison](samples/ui-concepts/07-comparison-refined.png) | Latest proposal; not explicitly approved | One large before/after canvas, a visible concept picker, and access to the brief and 3D preview. |

The first two are complementary layout patterns, not a requirement to show two selection screens in sequence. Use a tray when the shelf needs the width; use an inspector when the current decision needs explanation or controls.

Earlier presentation boards, the empty upload landing page, and the superseded guided-form and comparison mockups are exploration history. They are not equal sources of design direction. The user preferred actual software screens with a sample shelf loaded by default.

## The experience

PreShelf should open into something a person can use. Make a clearly identified sample shelf available by default, with uploading a personal photo easy to find. A sample is working content, not a promotional image. Opening the app should not start paid concept generation.

The shelf is the main object of work. Keep it visible while someone selects a product, describes a packaging change, or inspects a result whenever the available space supports that task. Retain the selected product and shelf context as they move between tools.

Polish comes from readable controls, predictable placement, and proportion. Most visual color should come from the shelf and packaging. The surrounding interface should help someone see and act on that content.

## Screen structure

Use a small, stable application header for the product identity, major destinations, upload action, and theme control. Put the current shelf or product name in the workspace below it. Avoid repeating the same navigation as a header tab, a large heading, and another row of buttons.

Organize work into three layers:

- Application navigation answers where you are and which tool you can open.
- The canvas presents the photo, 3D scene, comparison, or heatmap. Viewing tools stay close to it.
- A tray or inspector presents the current selection, settings, results, and next action.

The concepts give roughly three quarters of a desktop workspace to the canvas when an inspector is open. Treat that as a starting proportion. A long brief needs more width than a concept picker; a shelf with many small packages needs more width than a close crop. Let the content decide.

Keep the canvas and its toolbar aligned. Put related controls together: view mode above the canvas, pan/zoom/reset near its lower edge, and task actions beside their inputs or selection. A fixed action area can help with a long panel, provided it never covers content or keyboard focus.

Use whitespace to separate groups before adding containers. A border should identify a control, selection, or meaningful boundary. Avoid nesting cards inside cards or turning every piece of metadata into a badge.

## Visual language

Use near-white and light mineral-gray surfaces in light mode, dark graphite text, and a restrained brick-red or vermilion accent. The accent identifies the main action and important selection states; it should not color every link, toggle, and icon. Give destructive actions an explicit label and treatment distinct from ordinary selection.

Use a compact, readable sans-serif family with a few deliberate weights. Existing system fonts are a reasonable starting point. Most interface text should feel around 14–16px on desktop, with modest workspace headings and quieter supporting text. Avoid oversized hero typography in the working app. Do not reproduce illegible small text from generated screenshots.

Prefer small, consistent corner radii, fine separators, and minimal elevation. Reserve shadows for surfaces that actually float, such as menus. Use one coherent icon family; label unfamiliar or consequential controls. Selected states should combine color with a check, outline, underline, or text state.

Support light and dark themes across every surface. Dark mode should use graphite surfaces with distinct control boundaries and readable secondary text, rather than simply invert the light palette. Keep photos, textures, packshots, and heatmaps faithful in either theme. Establish and measure actual semantic colors during implementation; the image colors are not validated accessibility tokens.

## Apply the direction across workflows

### Shelf and product selection

Let the loaded shelf dominate the home workspace. Keep upload available without displacing the current scene. Identify sample content plainly.

A selection should connect the marked region on the shelf to its product thumbnail and name. Keep outlines thin enough to inspect the packaging. Distinguish a proposed segmentation from a confirmed selection, and retain confirmation, retry, and reselection controls.

The compact tray is useful for a simple next step. The inspector is useful for a larger product preview or contextual actions. Neither should duplicate the same information elsewhere on screen.

### Packaging Lab

Keep the selected product identifiable while the brief is edited. Group audience, price tier, and tone separately from constraints such as Keep and Avoid. Make optional reference photos and generation settings discoverable without forcing every setting into the initial view.

Use actual field labels and preserve entries when generation fails. Keep the chosen model, variant count, and relevant paid-generation information available before submission. Do not hardcode illustrative prices or timings from a mockup.

Provide product and previous concept-set history in a clear, reachable location. Changing panels should not imply that earlier work has disappeared.

### Comparison and 3D preview

The revised concept proposes a wipe over one continuous shelf. Original and generated images must share geometry, crop, and zoom so the comparison shows the packaging change rather than a camera change. Label both sides and provide an operable slider, not a decorative divider.

Retain side-by-side comparison as an alternative. On narrow screens, prefer a usable wipe or explicit original/concept switch over shrinking two shelves beyond recognition.

Keep concept selection obvious and synchronized with the preview. Use short factual labels; avoid invented quality scores or claims that one variant will perform better. Pack-only inspection can be useful, but its exact control placement is a proposal rather than an existing contract.

Opening a concept on the 3D shelf should preserve its identity and offer a visible way back to the original texture. Keep generation and rendering status close to the affected content.

### Placement Test

Reuse the canvas, inspector, control, and selection language. Give slot selection and heatmaps room to be inspected. Keep assumptions, personas, optional user-entered costs, result tables, overlay controls, and 3D access reachable.

Results must remain described as model estimates under stated assumptions, not measured shopper behavior. Do not turn a recommendation into an unexplained score or hide its assumptions to make the screen look simpler. Tables may need a wider layout than the selection inspector.

## Preserve capability while simplifying

Before replacing a surface, map its current actions to their new locations. Secondary menus and expandable sections are suitable for less frequent actions only when their labels make those actions findable.

| Area | Capabilities to retain |
| --- | --- |
| Shelf viewer | Upload, original photo, textured 3D, reset, keyboard orbit/zoom, GLB download, legacy splat comparison and its controls. |
| Product setup | Point/box selection, keyboard selection, mask confirmation and retry, reselection, product name/category, optional side/back photos. |
| Packaging | Full brief, model choice, variant count, generation progress/errors, product and concept-set history, available packshot/shelf downloads. |
| Comparison | Original versus concept, side-by-side and slider comparison, concept on the 3D shelf, return to original packaging. |
| Placement | Slot and persona setup, assumptions and optional costs, results, heatmaps, overlay controls, 3D view, and estimate disclosures. |

This is a migration reminder, not a frozen feature inventory. Check the current source before changing a workflow: [viewer](shelfproof/static/index.html), [Packaging Lab](shelfproof/static/packaging.js), and [Placement Test](shelfproof/static/placement.js).

## Behavior beyond the screenshots

On smaller screens, let the inspector become an accessible section, drawer, or sheet rather than compressing the desktop split. Preserve access to the shelf and selection context. Keep touch targets comfortable and avoid controls that depend on hover.

Every primary path needs loading, empty, error, disabled, and recovery states. Keep valid previews and user input visible during recoverable failures. Report progress that the backend actually knows; do not invent percentage completion. Announce meaningful status changes accessibly.

Keep keyboard selection and camera controls. Provide visible focus, labeled icon buttons, and an accessible comparison slider. Do not make color or animation the only indication of state.

Use motion sparingly to explain a panel opening, a selection change, or completed work. Frequent viewing controls should respond immediately. Respect reduced-motion preferences and avoid animating the shelf merely for decoration.

## Reviewing an implementation

Judge the running interface against the task, not screenshot similarity. Inspect it with a real shelf, multiple products and concept sets, long names, pending work, and a recoverable error. Look at desktop and narrow layouts in both themes, and exercise the keyboard path.

Check whether the shelf is large enough to inspect, the selected product and concept are unmistakable, the next action is easy to find, and secondary capabilities remain reachable. Remove repeated labels, redundant explanations, and containers that do not help someone decide or act.

Generated packaging, logos, prices, text, crop proportions, and sample metadata are illustrative. Use real assets and application state in the product. The concepts also suggest interactions that the current app may not support, such as photo pan/zoom and linked comparison views; implement and verify those deliberately or show controls that reflect the actual behavior. Never ship a mockup control that implies unavailable functionality.
