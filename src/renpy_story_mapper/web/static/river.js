/**
 * Story River flow painter.
 *
 * The reader's water is geometry, not borders. Rectangles and clipped polygons cannot
 * draw a river that leaves a trunk, sweeps outward, and returns to a confluence, so the
 * flow is measured from the laid-out DOM and painted as one SVG layer per story event.
 *
 * CSS still owns every card, colour, and type decision. This module owns only the
 * trunk, the tributaries, the confluences, and the tails between them.
 */

const SVG_NS = "http://www.w3.org/2000/svg";

/** Enough samples that an offset polyline is indistinguishable from the true offset curve. */
const RIBBON_SAMPLES = 44;

/** Flow sizes in rem, resolved against the root font size at paint time. */
const TRUNK_REM = 3.5;
const ROUTE_TRUNK_REM = 1.5;
const TAIL_REM = 4;
const ARROW_REM = 1.4;

/** A fork mouth widens with the arm count so a four-way split never squeezes its tributaries. */
const MOUTH_PER_EXTRA_ARM = 0.35;
const MOUTH_MAX = 2.3;

/** Tributaries tuck under the card they feed instead of stopping at its edge. */
const TUCK_REM = 1.1;

const MIN_ARROW_RUN_REM = 3.2;

function rootUnit() {
  return parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
}

function point(x, y) {
  return { x, y };
}

function bezier(p0, p1, p2, p3, t) {
  const u = 1 - t;
  return point(
    u * u * u * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t * t * t * p3.x,
    u * u * u * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t * t * t * p3.y,
  );
}

function bezierTangent(p0, p1, p2, p3, t) {
  const u = 1 - t;
  return point(
    3 * u * u * (p1.x - p0.x) + 6 * u * t * (p2.x - p1.x) + 3 * t * t * (p3.x - p2.x),
    3 * u * u * (p1.y - p0.y) + 6 * u * t * (p2.y - p1.y) + 3 * t * t * (p3.y - p2.y),
  );
}

function round(value) {
  return Math.round(value * 100) / 100;
}

function smoothstep(t) {
  return t * t * (3 - 2 * t);
}

/**
 * A filled band that follows a cubic centreline and changes width along it.
 * Both ends leave and arrive vertically, which is what makes a fork read as water
 * pulling away from the trunk rather than a line snapping to an angle. `sideways`
 * turns one end so a rail can feed a card that sits beside it, not below it.
 */
function ribbon(from, to, startWidth, endWidth, { entersSideways = false, leavesSideways = false } = {}) {
  const reach = to.x - from.x;
  // A collapsed or inverted run still needs handles that point the way the water goes,
  // or the band folds back over itself.
  const drop = to.y - from.y;
  const span = Math.max(Math.abs(drop), 1) * (drop < 0 ? -1 : 1);
  // The handles never cross: a tributary that leaves and arrives vertically stays a
  // sweep, while overlapping handles collapse it into a flat horizontal bulge.
  const lead = leavesSideways ? Math.max(span * 0.62, Math.abs(reach) * 0.5) : span * 0.62;
  const trail = span * 0.4;
  const p0 = from;
  const p1 = leavesSideways
    ? point(from.x + reach * 0.55, from.y)
    : point(from.x, from.y + lead);
  const p2 = entersSideways
    ? point(to.x - reach * 0.55, to.y)
    : point(to.x, to.y - trail);
  const p3 = to;
  const left = [];
  const right = [];
  let middle = null;
  for (let step = 0; step <= RIBBON_SAMPLES; step += 1) {
    const t = step / RIBBON_SAMPLES;
    const centre = bezier(p0, p1, p2, p3, t);
    const slope = bezierTangent(p0, p1, p2, p3, t);
    const length = Math.hypot(slope.x, slope.y) || 1;
    const half = (startWidth + (endWidth - startWidth) * smoothstep(t)) / 2;
    left.push([centre.x - (slope.y / length) * half, centre.y + (slope.x / length) * half]);
    right.push([centre.x + (slope.y / length) * half, centre.y - (slope.x / length) * half]);
    // Mark the arrow where the sweep is still turning; dead centre is its flattest point.
    if (step === Math.round(RIBBON_SAMPLES * 0.4)) {
      middle = { x: centre.x, y: centre.y, angle: (Math.atan2(slope.y, slope.x) * 180) / Math.PI - 90 };
    }
  }
  const outline = [...left, ...right.reverse()]
    .map(([x, y], index) => `${index ? "L" : "M"}${round(x)},${round(y)}`)
    .join("");
  return { d: `${outline}Z`, middle };
}

/**
 * A trunk segment. `mouth` flares the tail of the run so the split reads as a river
 * mouth opening; a negative run flares the head instead, which is how a confluence
 * pours back into the shared story.
 */
function trunk(axis, top, bottom, width, { mouth = 0, flareUp = false } = {}) {
  const half = width / 2;
  const wide = Math.max(width, mouth) / 2;
  if (!mouth || mouth <= width) {
    return `M${round(axis - half)},${round(top)}L${round(axis + half)},${round(top)}L${round(axis + half)},${round(bottom)}L${round(axis - half)},${round(bottom)}Z`;
  }
  const span = Math.min(Math.abs(bottom - top), (wide - half) * 2.4);
  if (flareUp) {
    const knee = top + span;
    return [
      `M${round(axis - wide)},${round(top)}`,
      `C${round(axis - wide)},${round(top + span * 0.55)} ${round(axis - half)},${round(knee - span * 0.45)} ${round(axis - half)},${round(knee)}`,
      `L${round(axis - half)},${round(bottom)}`,
      `L${round(axis + half)},${round(bottom)}`,
      `L${round(axis + half)},${round(knee)}`,
      `C${round(axis + half)},${round(knee - span * 0.45)} ${round(axis + wide)},${round(top + span * 0.55)} ${round(axis + wide)},${round(top)}`,
      "Z",
    ].join("");
  }
  const knee = bottom - span;
  return [
    `M${round(axis - half)},${round(top)}`,
    `L${round(axis - half)},${round(knee)}`,
    `C${round(axis - half)},${round(knee + span * 0.45)} ${round(axis - wide)},${round(bottom - span * 0.55)} ${round(axis - wide)},${round(bottom)}`,
    `L${round(axis + wide)},${round(bottom)}`,
    `C${round(axis + wide)},${round(bottom - span * 0.55)} ${round(axis + half)},${round(knee + span * 0.45)} ${round(axis + half)},${round(knee)}`,
    `L${round(axis + half)},${round(top)}`,
    "Z",
  ].join("");
}

/** A stream that proves nothing beyond itself narrows to a point instead of merging. */
function tail(axis, top, bottom, width) {
  return ribbon(point(axis, top), point(axis, bottom), width, Math.min(2, width)).d;
}

/**
 * A drop long enough to clear another route's opened story is carried down a lane at the
 * edge of the stage. Running it straight from card to confluence would drag a wide band
 * across everything in between.
 */
const CARRY_REM = 16;
const CARRY_BEND_REM = 5;

class RiverCanvas {
  constructor(host, unit) {
    this.host = host;
    this.unit = unit;
    this.origin = host.getBoundingClientRect();
    this.svg = document.createElementNS(SVG_NS, "svg");
    this.svg.setAttribute("class", "story-river-canvas");
    this.svg.setAttribute("aria-hidden", "true");
    this.svg.setAttribute("focusable", "false");
    this.svg.setAttribute("preserveAspectRatio", "none");
    this.svg.setAttribute("viewBox", `0 0 ${round(this.origin.width)} ${round(this.origin.height)}`);
    this.svg.setAttribute("width", round(this.origin.width));
    this.svg.setAttribute("height", round(this.origin.height));
  }

  rect(element) {
    const box = element.getBoundingClientRect();
    return {
      left: box.left - this.origin.left,
      right: box.right - this.origin.left,
      top: box.top - this.origin.top,
      bottom: box.bottom - this.origin.top,
      width: box.width,
      height: box.height,
      centre: box.left - this.origin.left + box.width / 2,
    };
  }

  /** Lane clear of every centred block, on the side the stream already leans toward. */
  lane(x) {
    const margin = this.unit * 3.4;
    return x < this.origin.width / 2 ? margin : this.origin.width - margin;
  }

  /**
   * Draw one stream from `from` to `to`, carrying it down an edge lane when the drop is
   * long enough that a direct sweep would cross other routes' content.
   */
  stream(from, to, startWidth, endWidth, options = {}) {
    const drop = to.y - from.y;
    if (drop <= CARRY_REM * this.unit) {
      const direct = ribbon(from, to, startWidth, endWidth);
      this.band(direct.d, options);
      this.arrow(direct.middle, { run: Math.abs(drop) + Math.abs(to.x - from.x) });
      return;
    }
    const bend = CARRY_BEND_REM * this.unit;
    const laneX = this.lane(from.x);
    const carried = Math.min(startWidth, endWidth) * 0.6;
    const out = ribbon(from, point(laneX, from.y + bend), startWidth, carried);
    this.band(out.d, options);
    this.arrow(out.middle, { run: bend + Math.abs(laneX - from.x) });
    this.band(trunk(laneX, from.y + bend, to.y - bend, carried), options);
    this.arrowOnRun(laneX, from.y + bend, to.y - bend);
    const back = ribbon(point(laneX, to.y - bend), to, carried, endWidth);
    this.band(back.d, options);
    this.arrow(back.middle, { run: bend + Math.abs(to.x - laneX) });
  }

  band(d, { slot = null, kind = "trunk", fade = 0 } = {}) {
    if (!d) return null;
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("class", `river-band river-band--${kind}`);
    path.setAttribute("d", d);
    if (slot) path.style.setProperty("--river-flow", `var(--story-route-${slot})`);
    if (fade) path.style.setProperty("--river-fade", String(fade));
    this.svg.append(path);
    return path;
  }

  arrow(at, { run = Infinity } = {}) {
    if (!at || run < MIN_ARROW_RUN_REM * this.unit) return;
    const size = ARROW_REM * this.unit;
    const head = size * 0.44;
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("class", "river-arrow");
    path.setAttribute(
      "d",
      `M0,${round(-size)}L0,0M${round(-head)},${round(-head)}L0,0L${round(head)},${round(-head)}`,
    );
    path.setAttribute("transform", `translate(${round(at.x)},${round(at.y)}) rotate(${round(at.angle || 0)})`);
    this.svg.append(path);
  }

  /** A straight run gets its arrow at the midpoint, pointing downstream. */
  arrowOnRun(axis, top, bottom) {
    this.arrow({ x: axis, y: (top + bottom) / 2 + ARROW_REM * this.unit * 0.4, angle: 0 }, { run: bottom - top });
  }
}

function armSlot(element) {
  return element?.dataset?.storyRouteSlot || null;
}

/**
 * Where a stream leaves an arm: below the card *and* below the target and provenance
 * lines it carries, so water never runs under the reader's own words.
 */
function armFoot(canvas, arm, head) {
  let foot = canvas.rect(head).bottom;
  for (const child of arm.children) {
    if (child.classList.contains("story-continuation")) break;
    const box = canvas.rect(child);
    if (box.height) foot = Math.max(foot, box.bottom);
  }
  return foot;
}

function ownedDescendant(choice, arm) {
  const id = arm.dataset.storySelectionId;
  if (!id) return null;
  return choice.querySelector(
    `:scope > .story-descendants > .story-descendant-route[data-owner-selection-id="${CSS.escape(id)}"]`,
  );
}

/** Arms fan across a mouth that is wider than the trunk it leaves. */
function mouthWidth(trunkWidth, count) {
  return trunkWidth * Math.min(MOUTH_MAX, 1 + MOUTH_PER_EXTRA_ARM * Math.max(0, count - 1));
}

/** Arms share a column when the layout stacked them, whatever the reason. */
function isStacked(canvas, arms, armEls) {
  if (arms.classList.contains("is-stacked")) return true;
  if (armEls.length < 2) return false;
  const [first, second] = armEls.map((arm) => arm.querySelector(":scope > .story-arm-head"));
  if (!first || !second) return false;
  return Math.abs(canvas.rect(first).centre - canvas.rect(second).centre) < 4;
}

function paintFan(canvas, choice, armEls, axis, enterY, width, slot) {
  const unit = canvas.unit;
  const tuck = TUCK_REM * unit;
  const heads = armEls.map((arm) => ({
    arm,
    head: arm.querySelector(":scope > .story-arm-head"),
  })).filter((entry) => entry.head);
  if (!heads.length) return { y: enterY, rail: null };
  const boxes = heads.map(({ arm, head }) => ({ arm, head, box: canvas.rect(head) }));
  const mouth = mouthWidth(width, boxes.length);
  const highest = Math.min(...boxes.map(({ box }) => box.top));
  const splitY = Math.max(enterY + unit * 0.5, highest - unit * 6.75);

  canvas.band(trunk(axis, enterY, splitY, width, { mouth }), { slot });
  canvas.arrowOnRun(axis, enterY, splitY - unit * 2);

  const lane = mouth / boxes.length;
  boxes.forEach(({ arm, box }, index) => {
    const startX = axis - mouth / 2 + lane * (index + 0.5);
    const bandWidth = Math.min(lane * 0.94, box.width * 0.46);
    const stream = ribbon(
      point(startX, splitY),
      point(box.centre, box.top + tuck),
      lane,
      bandWidth,
    );
    canvas.band(stream.d, { slot: armSlot(arm), kind: "tributary" });
    canvas.arrow(stream.middle, { run: Math.abs(box.top - splitY) + Math.abs(box.centre - startX) });
  });
  return { y: Math.max(...boxes.map(({ box }) => box.bottom)), rail: null };
}

/**
 * A stacked fork becomes one visible rail with short inlets, so five or more arms never
 * squeeze the prose. Narrow viewports stack a smaller fan through CSS alone, so the rail
 * is placed from where the cards actually sit rather than from a fixed padding value.
 */
function paintStack(canvas, arms, armEls, axis, enterY, width, slot) {
  const unit = canvas.unit;
  const armsBox = canvas.rect(arms);
  const boxes = armEls
    .map((arm) => ({ arm, head: arm.querySelector(":scope > .story-arm-head") }))
    .filter((entry) => entry.head)
    .map(({ arm, head }) => ({ arm, box: canvas.rect(head) }));
  if (!boxes.length) return { y: enterY, rail: null };
  const railWidth = Math.min(width, unit * 1.5);
  // Sit a third of the way into the gutter the stack reserved, so each inlet has a
  // visible run between the rail and the card edge it feeds.
  const cards = Math.min(...boxes.map(({ box }) => box.left));
  const railX = Math.max(armsBox.left + railWidth / 2, armsBox.left + (cards - armsBox.left) / 3);
  const head = armsBox.top + unit * 1.2;
  const foot = armsBox.bottom;
  canvas.stream(point(axis, enterY), point(railX, head), width, railWidth, { slot });
  canvas.band(trunk(railX, head, foot, railWidth), { slot });
  canvas.arrowOnRun(railX, head, foot);
  for (const entry of boxes) {
    const inletY = entry.box.top + Math.min(entry.box.height * 0.4, unit * 1.4);
    canvas.band(
      ribbon(
        point(railX, inletY - unit * 2.2),
        point(entry.box.left + unit * 0.2, inletY),
        railWidth,
        railWidth * 0.7,
        { entersSideways: true },
      ).d,
      { slot: armSlot(entry.arm), kind: "tributary" },
    );
  }
  return { y: foot, rail: { x: railX, width: railWidth, foot } };
}

/**
 * Arms that rejoin *at this confluence*. A fork can carry more than one proven target, so an
 * arm only merges into the confluence its own rejoin binding names; painting every
 * non-terminal arm into the first confluence would assert a merge the story never proves.
 */
function mergingArms(choice, armEls, confluence) {
  const target = confluence.dataset.storyConfluenceTargetSelectionId || null;
  return armEls.filter((arm) => {
    if (arm.querySelector(":scope > .story-continuation.is-route-return")) return false;
    if (ownedDescendant(choice, arm)) return false;
    if (["ending", "unresolved"].includes(arm.dataset.outcomeKind || "")) return false;
    return (arm.dataset.storyRejoinTargetSelectionId || null) === target;
  });
}

function paintMerge(canvas, choice, merging, confluence, width) {
  const unit = canvas.unit;
  const tuck = TUCK_REM * unit;
  const target = canvas.rect(confluence);
  const mouth = mouthWidth(width, Math.max(1, merging.length));
  const lane = mouth / Math.max(1, merging.length);
  merging.forEach((arm, index) => {
    const head = arm.querySelector(":scope > .story-arm-head");
    if (!head) return;
    const box = canvas.rect(head);
    const foot = armFoot(canvas, arm, head);
    const endX = target.centre - mouth / 2 + lane * (index + 0.5);
    canvas.stream(
      point(box.centre, foot - tuck),
      point(endX, target.top + unit * 0.55),
      Math.min(lane * 0.94, box.width * 0.46),
      lane,
      { slot: armSlot(arm), kind: "tributary" },
    );
  });
  return merging.length;
}

/**
 * A stacked fork with one target already has a rail running past every arm, so the rail itself
 * carries the rejoin to the confluence. When targets differ, `paintChoice` deliberately uses
 * per-arm streams instead: one shared rail cannot say which stacked arms belong to which target.
 */
function paintRailMerge(canvas, merging, confluence, rail, width, slot) {
  if (!merging.length) return 0;
  const target = canvas.rect(confluence);
  canvas.stream(
    point(rail.x, rail.foot),
    point(target.centre, target.top + canvas.unit * 0.55),
    rail.width,
    width,
    { slot },
  );
  return merging.length;
}

/** Arms that end, stay unresolved, or keep their own identity run out instead of merging. */
function paintOpenTails(canvas, choice, armEls, merged, rail) {
  const unit = canvas.unit;
  for (const arm of armEls) {
    const head = arm.querySelector(":scope > .story-arm-head");
    if (!head) continue;
    const descendant = ownedDescendant(choice, arm);
    const own = arm.querySelector(":scope > .story-continuation.is-route-return");
    const full = canvas.rect(head);
    // A stacked arm leaves from its own left edge; a fanned arm leaves from its centre.
    const box = rail ? { ...full, centre: full.left + unit * 0.8 } : full;
    const foot = armFoot(canvas, arm, head) - unit * 0.4;
    const slot = armSlot(arm);
    if (descendant) {
      const summary = descendant.querySelector(":scope > .story-descendant-owner") || descendant;
      const target = canvas.rect(summary);
      canvas.stream(
        point(box.centre, foot),
        point(target.centre, target.top + unit * 0.3),
        Math.min(unit * ROUTE_TRUNK_REM, box.width * 0.3),
        unit * ROUTE_TRUNK_REM,
        { slot, kind: "route" },
      );
      continue;
    }
    if (own) {
      const target = canvas.rect(own);
      canvas.stream(
        point(box.centre, Math.min(foot, target.top - unit * 2.4)),
        point(target.centre, target.top + unit * 0.3),
        unit * ROUTE_TRUNK_REM,
        unit * ROUTE_TRUNK_REM * 0.8,
        { slot, kind: "route" },
      );
      continue;
    }
    if (merged.has(arm)) continue;
    const spent = arm.dataset.outcomeKind === "ending" ? 0.7 : 0.45;
    canvas.band(
      tail(box.centre, foot, foot + TAIL_REM * unit, unit * ROUTE_TRUNK_REM),
      { slot, kind: "tail", fade: spent },
    );
  }
}

/**
 * Paint one branch point and report the y where the stream leaves it. The axis comes from
 * the branch point itself, so the same code serves the shared river and a nested route.
 * `slot` is null on the shared chronology and a palette slot inside an owned route.
 */
function paintChoice(canvas, choice, enterY, width, slot) {
  const unit = canvas.unit;
  const axis = canvas.rect(choice).centre;
  let y = enterY;
  const control = choice.querySelector(":scope > .story-choice-control");
  if (control) {
    const box = canvas.rect(control);
    if (box.top > y) {
      canvas.band(trunk(axis, y, box.top, width), { slot });
      canvas.arrowOnRun(axis, y, box.top);
    }
    y = box.bottom;
  }
  const arms = choice.querySelector(":scope > .story-arms");
  if (!arms) return y;
  const armEls = [...arms.querySelectorAll(":scope > .story-arm")];
  if (!armEls.length) return y;

  const fork = isStacked(canvas, arms, armEls)
    ? paintStack(canvas, arms, armEls, axis, y, width, slot)
    : paintFan(canvas, choice, armEls, axis, y, width, slot);
  y = fork.y;

  // A fork can prove several different merges. Each confluence takes only the arms whose own
  // rejoin binding names it, and anything left over runs out as a tail.
  const merged = new Set();
  const confluences = [...choice.querySelectorAll(":scope > .story-continuation.is-confluence")];
  const confluenceTargetCount = new Set(
    confluences.map((confluence) => confluence.dataset.storyConfluenceTargetSelectionId || null),
  ).size;
  const useSharedRail = Boolean(fork.rail) && confluenceTargetCount <= 1;
  for (const confluence of confluences) {
    const merging = mergingArms(choice, armEls, confluence);
    for (const arm of merging) merged.add(arm);
    const count = useSharedRail
      ? paintRailMerge(canvas, merging, confluence, fork.rail, width, slot)
      : paintMerge(canvas, choice, merging, confluence, width);
    const box = canvas.rect(confluence);
    if (count) canvas.band(trunk(axis, box.bottom, box.bottom + unit * 3.4, width, { mouth: mouthWidth(width, count), flareUp: true }), { slot });
    y = Math.max(y, box.bottom);
  }
  paintOpenTails(canvas, choice, armEls, merged, fork.rail);

  for (const descendant of choice.querySelectorAll(":scope > .story-descendants > .story-descendant-route")) {
    paintDescendant(canvas, descendant);
    y = Math.max(y, canvas.rect(descendant).bottom);
  }
  return y;
}

/** An opened route keeps its own colour and its own narrower stream. */
function paintDescendant(canvas, descendant) {
  if (!descendant.open) return;
  const slot = descendant.dataset.storyRouteSlot || null;
  const width = canvas.unit * ROUTE_TRUNK_REM;
  const sequence = descendant.querySelector(":scope > .story-choice-sequence");
  if (!sequence) return;
  const summary = descendant.querySelector(":scope > .story-descendant-owner");
  const enterY = summary ? canvas.rect(summary).bottom : canvas.rect(sequence).top;
  paintSequence(canvas, sequence, enterY, width, slot);
}

/** A route's own sequence of branch points and owned story events. */
function paintSequence(canvas, sequence, enterY, width, slot) {
  let y = enterY;
  for (const node of sequence.children) {
    if (node.classList.contains("story-choice")) y = paintChoice(canvas, node, y, width, slot);
    else if (node.classList.contains("story-route-flow")) y = paintRouteFlow(canvas, node, y, width, slot);
  }
  return y;
}

/**
 * Owned story events read as a margin rail so the route stays identifiable beside the
 * shared river, and any fork inside one of them is painted like every other fork.
 */
function paintRouteFlow(canvas, flow, enterY, width, slot) {
  const unit = canvas.unit;
  const events = flow.querySelector(":scope > .story-route-events");
  if (!events) return enterY;
  const box = canvas.rect(events);
  const railX = box.left + unit * 1.35;
  const head = box.top + unit * 2;
  canvas.stream(point(canvas.rect(flow).centre, enterY), point(railX, head), width, unit, { slot, kind: "route" });
  canvas.band(trunk(railX, head, box.bottom, unit), { slot, kind: "route" });
  for (const event of events.querySelectorAll(":scope > .story-event")) {
    const card = event.querySelector(":scope > .story-event-head");
    let y = card ? canvas.rect(card).bottom : canvas.rect(event).top;
    for (const choice of event.querySelectorAll(":scope > .story-choices > .story-choice")) {
      y = paintChoice(canvas, choice, y, width, slot);
    }
  }
  return Math.max(enterY, box.bottom);
}

function paintEvent(event, unit) {
  const previous = event.querySelector(":scope > .story-river-canvas");
  if (event.hidden || !event.isConnected) {
    previous?.remove();
    return;
  }
  const canvas = new RiverCanvas(event, unit);
  if (!canvas.origin.height || !canvas.origin.width) {
    previous?.remove();
    return;
  }
  // A narrow stage gets a narrower river rather than a bar that swallows the prose.
  const width = Math.min(TRUNK_REM * unit, canvas.origin.width * 0.05);
  const axis = canvas.origin.width / 2;
  const bottom = canvas.origin.height;
  let y = 0;
  const head = event.querySelector(":scope > .story-event-head");
  if (head) {
    const box = canvas.rect(head);
    if (box.top > 0) {
      canvas.band(trunk(axis, 0, box.top, width));
      canvas.arrowOnRun(axis, 0, box.top);
    }
    y = box.bottom;
  }
  for (const choice of event.querySelectorAll(":scope > .story-choices > .story-choice")) {
    y = paintChoice(canvas, choice, y, width, null);
  }
  if (bottom > y) {
    canvas.band(trunk(axis, y, bottom, width));
    canvas.arrowOnRun(axis, y, bottom);
  }
  if (previous) previous.replaceWith(canvas.svg);
  else event.prepend(canvas.svg);
}

const scheduled = new Set();
let frame = 0;

function flush() {
  frame = 0;
  const unit = rootUnit();
  const events = [...scheduled];
  scheduled.clear();
  for (const event of events) paintEvent(event, unit);
}

function schedule(events) {
  for (const event of events) scheduled.add(event);
  if (frame) return;
  frame = requestAnimationFrame(flush);
}

let observer = null;
let mounted = null;

function mainEvents(root) {
  return [...root.querySelectorAll('.story-event[data-story-stream="main"]')];
}

/** Repaint the river under `root`, or only the events containing `within`. */
export function repaintStoryRiver(within = null) {
  if (!mounted) return;
  if (within) {
    const event = within.closest?.('.story-event[data-story-stream="main"]');
    if (event) {
      schedule([event]);
      return;
    }
  }
  schedule(mainEvents(mounted));
}

/**
 * Start painting the river inside `root` and keep it painted while the reader
 * expands prose, opens owned routes, searches, or resizes the window.
 */
export function mountStoryRiver(root) {
  unmountStoryRiver();
  if (!root) return;
  mounted = root;
  observer = new ResizeObserver((entries) => schedule(entries.map((entry) => entry.target)));
  for (const event of mainEvents(root)) observer.observe(event);
  schedule(mainEvents(root));
}

export function unmountStoryRiver() {
  observer?.disconnect();
  observer = null;
  if (mounted) for (const canvas of mounted.querySelectorAll(".story-river-canvas")) canvas.remove();
  mounted = null;
  scheduled.clear();
}
