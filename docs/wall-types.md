# Why the wall types have the values they do

Ekahau's wall-type schema has no description field — a type carries a name, a
colour, an attenuation, a thickness and its edges, and nothing else. So the
reasoning behind a number has nowhere to live inside the app or inside an
`.esx`. It lives here.

This matters more than it sounds. The Framery value was changed three times
across v1.31.0, v1.31.1 and v1.32.4, each time for a good reason, and every one
of those reasons was written down in `docs/releases/` — a folder that did not
survive the clean repository at v2.0.0. The values kept working; the argument
for them was lost, and had to be recovered from a backup. Anything shipped with
a considered number should be written down here as well.

---

## Framery pods

### Framery Walls — 30 dB, settled

| | |
|---|---|
| Attenuation | 500 dB/m across 2.4, 5 and 6 GHz |
| Thickness | 0.06 m (0.20 ft) → **30 dB effective** |
| Reflection | 0.405 (steel panel) |
| Height | **Auto — full height, deliberately** |
| Colour | `#9C27B0` |

Every current Framery pod — One Compact, One, Four, Six — uses identical
exterior construction, verified against Framery's own tech-specs pages on
2026-08-03: **powder-coated matt steel panels**, an acoustic core, and a
sound-control laminated 4+4 mm glass door. Only size and weight differ, which
is why one wall type covers the range.

The 30 dB figure rests on three independent supports:

- Framery's own **ISO 23351-1 Class A, 30 dB D<sub>S,A</sub>** speech reduction.
  Acoustic and RF attenuation are not the same thing, but mass-loaded steel
  construction reaching 30 dB acoustically typically lands in the 25–35 dB range
  for Wi-Fi bands.
- **Ekahau's own Elevator Shaft** type is 150 dB/m × 0.2 m = 30 dB — the closest
  physical analogue in the stock library, a metal-lined enclosure.
A third support originally given — a weighted perimeter of three steel sides at
~35 dB plus a door at ~20 dB averaging ~31 dB — **no longer holds**, because the
door has since been measured at 3 dB rather than 20. It is recorded here only so
nobody re-derives 30 dB from it. The two supports above are unaffected: they are
about steel, and the measurement went through the glass.

That superseded figure is also why the split into two types matters. A single
perimeter average was never the right shape for this object; it smeared a
ten-to-one difference between the faces into one number.

It arrived at 30 dB by correction, not first guess: v1.31.0 shipped 100 dB/m
(~6 dB) and signal visibly bled through the pods; v1.31.1 raised it to 300 dB/m
(~18 dB) on advice of 15–18 dB for 6 GHz; v1.32.4 raised it to 500 dB/m once
the construction was confirmed as sheet steel rather than acoustic composite.

### Framery Glass — 3 dB, measured

| | |
|---|---|
| Attenuation | 50 dB/m across 2.4, 5 and 6 GHz |
| Thickness | 0.06 m (0.20 ft) → **3 dB effective** |
| Reflection | 0.6944 (Ekahau's own value for glazing) |
| Height | **Auto — full height, deliberately** |
| Colour | `#4FC3F7` |

**Measured on site with a NetAlly, September 2026: 2–3 dB through the closed
pod.** Not inferred, not derived — read off the instrument with the door shut.
This is stronger evidence than anything the earlier estimates had, and it is
why the figure is so much lower than the number that preceded it.

The thickness matches Framery Walls rather than the 8 mm pane, so the two draw
as one continuous outline when tracing a pod. They differ in attenuation, which
is the entire point, not in geometry.

#### Why the old ~20 dB figure was wrong

v1.32.4 put the door at 20–25 dB, citing WiFi Hotshots and Metro Wireless.
Those sources measure **coated and low-E glass**. Framery's door is **uncoated**
sound-control laminate, which is a different attenuation mechanism entirely: RF
loss in glass is dominated by **conductive coatings**, not by lamination or
thickness. A PVB acoustic interlayer does very little to RF; a low-E coating is
a thin metal film and behaves like one. Uncoated laminate is low single digits,
coated glass is 20–40 dB. The measurement lands exactly where the physics says
it should.

Do not re-derive the high number. It came from applying coated-glass data to
uncoated glass.

### Draw the pair separately, or the model is wrong in a way that looks fine

**Panels on three faces, glass on the door.** This is not a nicety.

Ekahau cannot vary attenuation across the faces of one wall type — attenuation
belongs to the type and a segment references exactly one — so the split is the
only way to say that a pod has one face that is ten times less lossy than the
others. Drawn correctly, the ray tracer finds the door path on its own, which is
what physically happens and what the NetAlly measured.

Draw all four faces as one uniform 30 dB perimeter and the model predicts a dead
box. That is demonstrably wrong, and it is wrong in the worst way: it looks
entirely plausible on a heat map.

### The limitation Ekahau cannot model, and what to do about it

With the door measured at only 3 dB, this is now unambiguously the dominant
real-world problem with a pod — not the walls.

Framery pods have powder-coated steel on the **roof and base** as well as the
walls. Ekahau's wall model is 2D — vertical planes, no ceiling material — so
**an AP mounted directly above a pod will always appear to cover its interior**,
whatever the wall values say, because the simulation does not know there is a
metal ceiling in the way.

This is why both Framery types are **full height** and are exempted from the
partial-height audit in `tools/wall_audit.py`. Height-limiting them would let a
ray from a ceiling AP drop in over the top at no loss at all — the opposite of
what a steel roof does. Over-attenuating the square metre or two of floor the
pod stands on is much the cheaper error.

It is deliberately the opposite call from shelving: a long, open-topped run with
a large footprint should be height-limited; a small sealed enclosure should not.

**Signal budget.** Through a steel wall or through the glass door, usable
coverage reaches roughly 2 m inside the pod. With an AP directly above,
effectively nothing gets in. The fix is a wired drop or repositioning an AP for
line-of-sight through a side or the door — not tuning power or channels.

**Two things Ekahau's format cannot store**, so they are conventions rather than
data: the *predefined wall length* of 3.28 ft (1 m) used when tracing a pod
outline is an Ekahau UI setting, not a field in the `.esx`; and there is no
description field on a wall type, which is the reason this document exists.

---

## Partial-height furniture

Wall types with no `upperEdge` are Auto height — floor to ceiling. That is right
for a wall and wrong for furniture. See `tests/test_wall_heights.py` for the
values and `tools/wall_audit.py` for the scanner that finds projects where it
was left wrong.

| Type | Height | Source |
|---|---|---|
| Cubicle | 1.5 m | Ekahau's own Cubicle |
| Shelf, Retail | 2.5 m | Ekahau's own Retail Shelf |
| Shelf, Warehouse | 10.0 m | Ekahau's own Warehouse Shelf |
| Bookshelf | 2.0 m | no Ekahau equivalent; a tall office bookshelf |
| Warehouse Rack Wall - 12ft | 3.6576 m | stated in its own name |
| Warehouse Rack Wall - 16ft | 4.8768 m | stated in its own name |
| Warehouse Rack Wall | **none** | name states no height; racking varies too much to guess |
