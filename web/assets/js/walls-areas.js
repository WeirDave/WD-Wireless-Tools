/* Attenuation area types for Quick Walls.

   A wall type is one line on a floor plan; an attenuation area is a polygon
   with a loss per foot and a lower and upper edge, which is what a tree canopy
   or a planting bed actually is. The presets live in
   /assets/attenuation-area-presets.json in the units they are measured in
   (dB per foot, feet) so the numbers can be checked against the notes they came
   from; Ekahau keeps metres, and the conversion happens here, once, at write.

   **This file never invents the shape of an area type.** Nothing in the suite
   had read attenuationAreaTypes.json before this, and a guessed field name
   writes a project Ekahau may refuse to open. So a new type is cloned from one
   the project already has and only the values we own are overwritten: name,
   colour, the two edges and the attenuation on each band. A project with no
   area type to copy from is refused, with the reason, rather than written to.

   Pure functions, no DOM: tests load this file in Node. */
(function (root) {
  'use strict';

  const FT_M = 0.3048;
  const BANDS = ['TWO', 'FIVE', 'SIX'];

  const feetToMetres = ft => Math.round(ft * FT_M * 10000) / 10000;
  // dB per foot -> dB per metre. 1 dB/ft is 3.2808 dB/m, not 0.3048.
  const dbPerFtToPerM = v => Math.round((v / FT_M) * 10000) / 10000;

  const sameName = (a, b) =>
    String(a || '').trim().toLowerCase() === String(b || '').trim().toLowerCase();

  /* Which member of the .esx holds the types, matched without regard to case,
     and which top-level key of it is the list. The key is read off the file
     rather than assumed, for the reason above. */
  function findMember(names) {
    return (names || []).find(n => /^attenuationAreaTypes\.json$/i.test(n)) || null;
  }

  function listKey(doc) {
    if (!doc || typeof doc !== 'object' || Array.isArray(doc)) return null;
    const keys = Object.keys(doc).filter(k => Array.isArray(doc[k]));
    return keys.length === 1 ? keys[0] : null;
  }

  /* Can this type be used as the shape of a new one? It must carry a
     per-band attenuation list, or there is nowhere to put the numbers. */
  function usableShape(t) {
    return !!t && typeof t === 'object' && Array.isArray(t.propagationProperties)
      && t.propagationProperties.some(p => p && p.band
        && Object.prototype.hasOwnProperty.call(p, 'attenuationFactor'));
  }

  function applyValues(target, preset) {
    target.name = preset.name;
    target.color = preset.color;
    target.lowerEdge = feetToMetres(preset.lowerEdgeFt);
    target.upperEdge = feetToMetres(preset.upperEdgeFt);
    if ('key' in target) target.key = preset.name;
    const props = target.propagationProperties;
    BANDS.forEach(band => {
      const value = dbPerFtToPerM(preset.attenuationDbPerFt[band]);
      let p = props.find(x => x && x.band === band);
      if (!p) {
        p = JSON.parse(JSON.stringify(props.find(x => x && x.band)));
        p.band = band;
        props.push(p);
      }
      p.attenuationFactor = value;
    });
    return target;
  }

  const sameValues = (a, b) => JSON.stringify(a) === JSON.stringify(b);

  /* What adding the presets to this list would do, and the new list.
     Nothing is mutated. A type already there under the same name is updated in
     place and keeps its id, so areas already drawn with it still resolve;
     one that already matches is counted, not rewritten. */
  function addPresets(types, presets, newId) {
    const list = Array.isArray(types) ? types : [];
    const shape = list.find(usableShape);
    if (!shape) {
      return { error: list.length
        ? 'None of this project’s attenuation area types has a per-band '
          + 'attenuation list to copy, so there is nothing safe to build the new '
          + 'types from.'
        : 'This project has no attenuation area type to copy the layout from. '
          + 'Add one in Ekahau (any name), then open the project again.' };
    }
    const out = list.slice();
    const added = [], updated = [];
    let unchanged = 0;
    (presets || []).forEach(preset => {
      const at = out.findIndex(t => sameName(t && t.name, preset.name));
      if (at >= 0) {
        const next = applyValues(JSON.parse(JSON.stringify(out[at])), preset);
        if (sameValues(next, out[at])) { unchanged++; return; }
        out[at] = next;
        updated.push(preset.name);
        return;
      }
      const fresh = applyValues(JSON.parse(JSON.stringify(shape)), preset);
      fresh.id = newId();
      out.push(fresh);
      added.push(preset.name);
    });
    return { types: out, added, updated, unchanged };
  }

  function describe(preset) {
    const a = preset.attenuationDbPerFt;
    return preset.lowerEdgeFt + '–' + preset.upperEdgeFt + ' ft · '
      + a.TWO + ' / ' + a.FIVE + ' / ' + a.SIX + ' dB/ft';
  }

  const api = { FT_M, BANDS, feetToMetres, dbPerFtToPerM, findMember, listKey,
                usableShape, addPresets, describe };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.WDAreas = api;
})(typeof window !== 'undefined' ? window : globalThis);
