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

### Framery Pod — 5 dB, from measurement, biased for safety

| | |
|---|---|
| Attenuation | 83.33 dB/m across 2.4, 5 and 6 GHz |
| Thickness | 0.06 m (0.20 ft) → **5 dB effective** |
| Reflection | 0.405 |
| Height | **Auto — full height, deliberately** |
| Colour | `#9C27B0`, keyboard shortcut `[8]` |
| Tracing | set Ekahau's predefined wall length to 3.28 ft (1 m) to follow a pod outline |

#### Why 5 dB when the measurements say 2–5

5 dB is the **conservative end of the measured range**, chosen deliberately. It
is not the midpoint and it is not a measurement in its own right — it is the
worst case the instrument saw, taken as the design figure.

The bias is the right way round. Overstating a pod's attenuation slightly means
a design might add an access point that was not strictly needed. Understating it
means someone ends up in a dead pod, which is the failure that generates
tickets. When the two errors are that asymmetric, err high.

#### This is an effective enclosure value, not a material loss

**Do not "correct" this back to 30 dB.** That has already happened once, and the
reasoning for it lived only in a backup repository.

Powder-coated sheet steel really is 30 dB or more as a *material*. The Framery
pod as a *system* leaks far more than that implies — through the door seal, the
ventilation, the cable pass-through, and the glass aperture. What Ekahau needs
in a wall type is the loss a signal actually suffers crossing the enclosure, and
that has now been measured rather than inferred.

The 30 dB figure that stood until 2026-09-08 was reasoned from Framery's ISO
23351-1 Class A acoustic rating of 30 dB D<sub>S,A</sub> plus Ekahau's Elevator
Shaft analogue. Acoustic isolation and RF attenuation are not the same
mechanism, and the inference was wrong by an order of magnitude.

#### The measurements

Two pods, NetAlly, **2026-09-08**. Door shut for both readings, same building,
same guest SSID, 5 GHz.

| | Pod 1 | Pod 2 |
|---|---|---|
| Door orientation | facing the AP | facing away, pod cornered against a wall |
| Distance to AP | ~20 ft (AP at 10 ft AFF) | ~27 ft (12 ft out, 24 ft to the side) |
| Signal average | **−56 dBm** | **−61 dBm** |
| Noise | −90 dBm | −90 dBm |
| SNR | 34 dB | 29 dB |

Five decibels apart, of which roughly three is the extra distance. So **door
orientation costs about 2 dB**, and total effective enclosure loss sits in the
**2–5 dB** range. The noise floor is identical in both, so nothing environmental
is confusing the comparison.

#### Why one type and not two

A previous version shipped `Framery Walls` at 30 dB and `Framery Glass` at 3 dB,
on the reasoning that the faces are different materials and Ekahau cannot vary
attenuation within one type.

The measurements retire that. A pod with its glass **facing away** from the AP,
cornered against a wall, still only lost about 2 dB more than one facing it —
nothing like the ten-to-one difference a 30/3 split predicts. The enclosure
leaks a couple of decibels whichever face you present, because reflected energy
illuminates the glass aperture even with no line of sight to it. One type, one
number, and no need to decide which face is which while tracing.

#### Where this value is valid, and where it is not

Validated in **open-plan layouts, with an AP within roughly 25 ft, and a
reflective path to the glass door.**

**Not validated** where the glass faces a solid wall or a dead alcove. Every pod
in the building measured was sited with APs facing the glass side, so there is
no true no-path example in the data. A pod whose door faces into a corner with
no reflective route back to an AP could plausibly be worse, and nothing here
proves otherwise. Measure that case before trusting the model on it.

#### The limitation Ekahau cannot model, and what to do about it

**This is the most consequential thing on this page**, and a low wall value makes
it more important rather than less.

**The design rule: never rely on an access point mounted directly above a pod.
Place for lateral line-of-sight to the door.**

That is a rule the designer applies, not a caveat about the model, because the
model will not raise it. Two things compound here — Ekahau cannot represent the
steel roof at all, and the wall value is now low — so a predictive heatmap will
show strong coverage over and inside a pod that has an AP directly overhead
delivering nothing into it. Nothing on the map will look wrong. There is no
warning to notice and no colour to interpret; the plan simply has to be drawn
so the situation never arises.

Framery pods have powder-coated steel on the **roof and base**. Ekahau's wall
model is 2D — vertical planes, no ceiling material — so **an AP mounted directly
above a pod will always predict coverage it cannot deliver**, whatever the wall
value says, because the simulation does not know there is a steel roof in the
way.

This is why the type is **full height** and is exempted from the partial-height
audit in `tools/wall_audit.py`. Height-limiting it would let a ray from a ceiling
AP drop in over the top at no loss at all, which is the opposite of what a steel
roof does. Over-attenuating the square metre or two of floor the pod stands on is
much the cheaper error, and it is deliberately the opposite call from shelving:
a long open-topped run with a large footprint should be height-limited; a small
sealed enclosure should not.

The fix for a pod that will not cover is a wired drop, or repositioning an AP for
a path in through the door — not tuning power or channels.

#### Superseded values, recorded so they are not rebuilt

| Version | Value | Why it changed |
|---|---|---|
| v1.31.0 | 100 dB/m (~6 dB) | signal visibly bled through the pods |
| v1.31.1 | 300 dB/m (~18 dB) | advice of 15–18 dB for 6 GHz |
| v1.32.4 | 500 dB/m (~30 dB) | construction confirmed as sheet steel; inferred from the acoustic rating |
| v2.46.0 | split 30 dB / 4 dB | faces are different materials; glass figure derived, not measured |
| v2.47.0 | split 30 dB / 3 dB | door measured at 2–3 dB |
| v2.48.0 | one type, 3 dB | whole enclosure measured, both door orientations |
| **v2.49.0** | **one type, 5 dB** | **conservative end of the measured 2–5 dB range, for design safety** |

A note on the ~20 dB glass figure that appeared in v1.32.4's reasoning: it cited
sources measuring **coated and low-E** glass, and Framery's door is **uncoated**
sound-control laminate. RF loss in glass is dominated by conductive coatings,
not by lamination or thickness. Do not re-derive from those sources.

---

## Partial-height furniture

Wall types with no `upperEdge` are Auto height — floor to ceiling. That is right
for a wall and wrong for furniture, and it is how 52 segments of warehouse
racking in one real project came to be modelled as 27 dB of solid barrier from
the slab to the roof.

**A height ships only when the type's own name states one.** Everything else
ships on Auto and `tools/wall_audit.py` reports it per project, by name, with a
segment count and a severity.

| Type | Height | Why |
|---|---|---|
| Walls, Steel 12ft | 3.6576 m | **12 ft**, stated in its own name |
| Warehouse Rack Wall - 12ft | 3.6576 m | **12 ft**, stated in its own name |
| Warehouse Rack Wall - 16ft | 4.8768 m | **16 ft**, stated in its own name |
| Warehouse Rack Wall | Auto | name states no height; racking varies too much to guess |
| Cubicle | Auto | height depends on the building — see below |
| Shelf, Retail | Auto | ” |
| Shelf, Warehouse | Auto | ” |
| Bookshelf | Auto | ” |
| Framery Pod | Auto, deliberately | a sealed box with a metal roof and floor; limiting its height would let a ceiling AP drop in over the top at no loss, which is the opposite of what a steel roof does |

### Why the guessed heights were withdrawn

v2.44.0 gave Bookshelf, Cubicle, Shelf Retail and Shelf Warehouse an
`upperEdge`. The reasoning — furniture stops short of the ceiling — is correct.
The action was wrong, for two separate reasons, and both are worth keeping
written down because the argument for making the change is more obvious than
the argument against it.

**We do not know the number.** A cubicle is 1.2 m in one office and 1.7 m in
the next; warehouse racking varies more than that again. A shipped guess changes
every project that opens the template, silently, in a direction nobody chose,
and the person who finds out is the one whose AP count moved. The audit report
is the better instrument: it names the project, the type and the segment count,
and the user decides.

**The numbers came from the wrong primitive.** Ekahau does model partial-height
furniture with an upper edge — on *attenuation areas*, which are polygons
carrying both a lower and an upper edge, not on wall types. Before v2.44.0,
`templates/ekahau_defaults.json` carried no `upperEdge` on any wall type at all.
So the 1.5 m and 2.5 m adopted "so our template and Ekahau's agree" were lifted
from Ekahau's *area* types onto walls, and the agreement the old test asserted
was with a file we had edited ourselves in the same commit.

Restored in v2.65.0. `templates/ekahau_defaults.json` mirrors what Ekahau ships
and is not ours to improve; `tests/test_wall_heights.py` now enforces the rule
in the other direction — a height only where the name states one.

### The honest fix, when it comes

An attenuation area with an `upperEdge` is the correct model for a pod, a
cubicle or a run of racking: Ekahau's engine computes the over-the-top path
itself, with no ceiling-height assumption baked into any number, and it is
right in a 2.7 m office and a 12 m high-bay alike. Nothing in this suite reads
or writes `attenuationAreaTypes.json` or `areas.json` today, so that is new
capability rather than a template edit. Until then, a calibrated wall type plus
the audit is the workable compromise, and the compromise should stay visible.
