---
name: visual-consistency-review
description: Write prompts/specs for and review generated images, sprites, animation frames or video against explicit constraints - camera geometry and facing, visible vs hidden surfaces, per-character attribute binding, physical contact, and frame-to-frame continuity; also catches keywords leaking into the picture and props carried over from earlier generations. Use whenever the requested output is imagery or animation with such constraints, including inside a code task (vd "sprite", "walk cycle", "ảnh tham chiếu", "nhân vật", "khung hình"). Not for backend or text-only work.
---

# Visual consistency review

Translate the request into observable constraints, inspect the actual output, and propose the smallest next correction. This is a review workflow, not a guarantee of geometric correctness; rules alone cannot fix a generator's capability limits.

## 1. Clean spec for each generation (C15, C16)

Start every generation from a fresh spec; carry over only properties the user still wants.

```
Carry over: …            Drop from previous: …
Must be VISIBLE: …
Context only (do not draw): …
Must NOT appear: …
```

## 2. Scene graph and visibility (F32, F33)

```
Camera: position, direction, angle, lens. Left/right defined relative to: camera | subject
Subject → object: who holds what, which hand, height
Facing: orientation of each subject and object relative to the camera and each other
Visible: …      Hidden: …   (do not ask for details that sit on a hidden surface, nor move them elsewhere)
```

## 3. Attribute table per subject (F34)

| Subject | Face/hair | Clothing | Accessories | Held item / hand | Reference used for (identity / pose / style) |
|---|---|---|---|---|---|

State which reference image supplies **identity** and which supplies only **pose** or style. Attributes of subject A must not appear on subject B.

## 4. Physics and motion (F35, F36)

- Contact points: fingers do not pass through objects, nothing floats unless intended, joints bend the right way. Respect intentional stylisation.
- Sequences: lock character sheet, palette, scale, camera and object attributes across frames, except for changes required by the intended motion.
- Cyclic motion: track phases and contact transitions against the intended movement. Check the last-to-first loop at target playback speed; still frames alone do not prove motion continuity.

## 5. Inspect and report (A06 for images)

- Open the actual image/frames at sufficient resolution; crop when a small feature is decisive. If only a prompt is available, call it a **spec review**, not visual QA.
- Check, in order: forbidden items absent → facing/visibility → per-subject attributes and counts → contact/anatomy → sequence continuity.
- Report each constraint as pass / fail / uncertain with the frame or region as evidence. Do not judge by "looks good", file size, a structure validator, or a single similarity score.
- Negative prompts help but do not guarantee compliance. When a criterion keeps failing, switch control mechanism (pose/layout reference, localized edit, rig, explicit geometry) instead of re-running the same prompt; stay within the authorised generation budget.
