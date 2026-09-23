"""Reading a delegated control back out of rendered markup.

Cloud Manager's controls used to carry their call in an `onclick`, and a test
that wanted to prove a button actually reaches its handler pulled the string out
and evaluated it. Since v2.170.0 the page carries a policy that forbids inline
script, so the call is declared instead - `data-fn` names the handler and
`data-args-json` (or `data-arg`/`data-arg2`) carries its arguments.

`DELEGATED_JS` is the same decoding the real dispatcher does, small enough to
paste into a node harness. It is deliberately *not* a second implementation of
`WD.actions`: it reads the attributes and hands back the name and the arguments,
and the test does the calling, because what these tests are checking is that the
right handler is reached with the right values.

Usage inside a node snippet::

    const hit = delegated(html, 'pushLocalOverCloud');
    api.pushLocalOverCloud.apply(null, hit.args);
"""

DELEGATED_JS = r"""
function _unattr(v) {
  return String(v == null ? '' : v)
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'")
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&');
}

/* The element carrying `data-fn="<name>"`, with its arguments decoded.
   Returns null when nothing on the page names that handler, which is the
   failure a test asserting "the control is reachable" is looking for. */
function delegated(html, fnName) {
  const tag = (String(html).match(
    new RegExp('<[^>]*data-fn(?:-[a-z]+)?="' + fnName + '"[^>]*>')) || [])[0];
  if (!tag) return null;
  const pick = (name) => {
    const hit = tag.match(new RegExp(name + '="([^"]*)"'));
    return hit ? _unattr(hit[1]) : null;
  };
  let args = [];
  const list = pick('data-args-json');
  if (list !== null) {
    args = JSON.parse(list);
  } else {
    const one = pick('data-arg-json');
    if (one !== null) args.push(JSON.parse(one));
    else if (pick('data-arg') !== null) args.push(pick('data-arg'));
    if (pick('data-arg2') !== null) args.push(pick('data-arg2'));
  }
  return {
    fn: fnName,
    args: args,
    stops: pick('data-stop') === '1',
    disabled: /aria-disabled="true"/.test(tag) || /\sdisabled[\s>]/.test(tag),
    tag: tag,
  };
}
"""
