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
- **Weighted perimeter**: three steel sides at roughly 35 dB plus one glass door
  at roughly 20 dB averages about 31 dB.

It arrived there by correction, not first guess: v1.31.0 shipped 100 dB/m
(~6 dB) and signal visibly bled through the pods; v1.31.1 raised it to 300 dB/m
(~18 dB) on advice of 15–18 dB for 6 GHz; v1.32.4 raised it to 500 dB/m once
the construction was confirmed as sheet steel rather than acoustic composite.

### Framery Glass — not shipped, value unresolved

Deliberately absent. A door type is genuinely wanted — the pod's four faces are
not the same material, and Ekahau cannot vary attenuation across the faces of
one type — but the number is contested by about 15 dB, and that difference
decides whether repositioning an AP to shoot through the door is a real fix or
a marginal one. Shipping either candidate would see it inherited as fact.

| Candidate | Source | Concern |
|---|---|---|
| **20–25 dB** | v1.32.4, citing WiFi Hotshots and Metro Wireless | Those measurements are of **coated / low-E** glass. Framery's door is **uncoated** acoustic laminate. |
| **3–8 dB** | Derived 2026-09-08 from measured clear glass, 3.6–4.2 dB at 6.75 GHz ([arXiv 2405.01362](https://arxiv.org/pdf/2405.01362)) | Consistent with uncoated-laminate physics, but the surrounding derivation assumed RF diffracting over the pod, which is wrong here. |

The physics favours the lower figure. RF attenuation in glass is dominated by
**conductive coatings**, not by lamination or thickness: a PVB acoustic
interlayer does very little to RF, whereas a low-E coating is a thin metal film
and behaves like one. Uncoated laminated glass is typically low single digits;
coated glass measures 20–40 dB. Applying coated-glass numbers to an uncoated
acoustic laminate would overstate it by roughly an order of magnitude.

**How to settle it:** one survey reading through the door and one through a
steel panel, on a real pod, resolves it in minutes and beats any amount of
further reading. Until then no type ships.

### The limitation Ekahau cannot model, and what to do about it

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
