"""Optional output: a "Prioritizing Opportunities" quadrant/bubble chart,
styled after the client's "Prioritizing Potential Resources" framework (same
slide furniture, same quadrant layout, same purple palette), with the eight
coded opportunity themes as the bubbles.

The two axes come from different places, and the distinction is the point:

    Relative Value       MEASURED. How many educators independently raised the
                         theme -- the only demand signal a set of interview
                         transcripts actually carries.

    Relative Difficulty  AUTHORED. How hard a change is for JABC depends on
                         their roadmap, budget and partnerships, none of which
                         appear in a transcript. It is declared per opportunity
                         in config/opportunities.yaml, against the anchors in
                         `difficulty_scale`, rather than derived from a number
                         that would only look objective.

Bubble size is the number of people who raised the theme. In the current
coding each person is counted once per theme, so size and horizontal position
carry the same number and size reinforces the value reading rather than adding
a third variable -- that stops being true if a theme is ever coded per answer.
"""

from __future__ import annotations

import logging
import math
import textwrap
from pathlib import Path

from .models import RespondentProfile

logger = logging.getLogger(__name__)

THEME_DISPLAY = {
    "awareness": "Awareness",
    "understanding": "Understanding",
    "trust": "Trust",
    "relevance": "Relevance",
    "ease_of_engagement": "Ease of\nEngagement",
    "advocacy": "Advocacy",
}

TITLE = "Prioritizing Opportunities"
SUBTITLE = (
    "We have used the below framework to prioritize opportunities, basis how many educators "
    "raised the theme (value) and how hard the change is for JABC to make (difficulty). "
    "Bubble size is the number of people who raised it."
)
EYEBROW = "Opportunity Themes"

# Palette sampled directly (pixel-level) from the reference
# "Prioritizing Potential Resources" chart, not eyeballed:
#   bubble fill                                   #6F2F9F
#   Prioritise quadrant fill                      #EFD9FF
#   Prioritise quadrant border + label            #9509E5
#   Consider / Investigate labels                 #BC8CDD
#   Avoid label + thin quadrant border/divider    #E3D6F0
#   eyebrow caption                               #7A2E9F
#   subtitle grey                                 #666666
BUBBLE_PURPLE = "#6F2F9F"
PRIORITISE_FILL = "#EFD9FF"
PRIORITISE_ACCENT = "#9509E5"
QUAD_LABEL_PURPLE = "#BC8CDD"
FAINT_LAVENDER = "#E3D6F0"
EYEBROW_PURPLE = "#7A2E9F"
SUBTITLE_GREY = "#666666"
AXIS_LABEL_BLACK = "#1A1A1A"

# The reference is a 16:9 slide, so the quadrant box is a wide rectangle,
# not a square. Value is mapped across BOX_W and difficulty up BOX_H; the
# axes still use aspect="equal" so bubbles stay perfectly round.
BOX_MIN = 0.0
BOX_W, BOX_H = 168.0, 100.0
MID_X, MID_Y = BOX_W / 2.0, BOX_H / 2.0
MIN_RADIUS, MAX_RADIUS = 6.5, 11.5

# The source deck plotted ~20 hand-placed resources, so its bubbles fill the
# frame. Seven opportunities spanning 6-11 mentions land in a tight cluster
# instead, which reads as a rendering bug rather than a finding.
# STRETCH_TO_FILL applies a single affine min-max rescale per axis so they span
# the frame the way the reference does. It preserves rank order and relative
# spacing, but it is a presentation choice: because it moves the cluster, an
# item can land in a different quadrant than its raw numbers would put it in.
# Set it to False to plot raw values and have quadrant membership mean exactly
# what `_opportunity_metrics` returns.
STRETCH_TO_FILL = True
STRETCH_INSET = 0.14  # keep stretched points within the middle 72% of each axis

# How much of a collision push is allowed to act vertically (see _declutter).
# 0.0 would pin every bubble to its difficulty row exactly but can deadlock a
# crowded row; 1.0 restores the old isotropic behaviour.
Y_PUSH_DAMP = 0.18

# Preferred display faces, in fallback order -- the reference deck is set in a
# geometric sans. Missing families are skipped silently by matplotlib.
FONT_STACK = ["Poppins", "Montserrat", "Century Gothic", "DejaVu Sans"]


def _opportunity_metrics(opp) -> tuple[float, float, int]:
    """(value, difficulty, people), the first two on a 0-100 scale.

    `value` is the coded mention count and `difficulty` the authored estimate,
    both taken straight from config/opportunities.yaml. Nothing is recomputed
    from the transcripts here: the mention counts came from a human reading
    them, which is a better instrument than keyword matching, and difficulty is
    not a property of the transcripts at all.
    """
    return float(opp.mentions), max(0.0, min(100.0, opp.difficulty * 100.0)), opp.people


def _to_box(value: float, difficulty_0_100: float, max_value: float) -> tuple[float, float]:
    """Difficulty is already 0-100; value is a raw mention count, so it is
    normalised against the most-mentioned opportunity."""
    v = (value / max_value * 100.0) if max_value > 0 else 0.0
    return v / 100.0 * BOX_W, difficulty_0_100 / 100.0 * BOX_H


def _stretch_axis(values: dict, span: float) -> dict:
    """Affine min-max rescale of one axis into [span*INSET, span*(1-INSET)].
    Rank order and relative spacing are preserved; a degenerate (all-equal)
    axis is centred rather than divided by zero."""
    lo_t, hi_t = span * STRETCH_INSET, span * (1.0 - STRETCH_INSET)
    lo, hi = min(values.values()), max(values.values())
    if hi - lo < 1e-9:
        return {k: span / 2.0 for k in values}
    return {k: lo_t + (v - lo) / (hi - lo) * (hi_t - lo_t) for k, v in values.items()}


def _bubble_radius(count: int, max_count: int) -> float:
    if max_count <= 0:
        return MIN_RADIUS
    frac = math.sqrt(count / max_count) if count > 0 else 0.0
    return MIN_RADIUS + frac * (MAX_RADIUS - MIN_RADIUS)


def _push_clear_of_zone(x: float, y: float, r: float, zone: tuple, gap: float = 1.0) -> tuple:
    """If circle (x, y, r) intersects axis-aligned rect `zone`, return a new
    (x, y) shifted just outside it (nudged toward whichever rect edge is
    closest), otherwise return (x, y) unchanged."""
    x0, y0, x1, y1 = zone
    closest_x = min(max(x, x0), x1)
    closest_y = min(max(y, y0), y1)
    dx, dy = x - closest_x, y - closest_y
    dist = math.hypot(dx, dy)
    if dist >= r + gap:
        return x, y
    if dist > 1e-6:
        ux, uy = dx / dist, dy / dist
        return closest_x + ux * (r + gap), closest_y + uy * (r + gap)
    # Centre is inside the rect: escape along whichever axis needs less travel.
    left, right = x - x0, x1 - x
    down, up = y - y0, y1 - y
    nearest = min(left, right, down, up)
    if nearest == left:
        return x0 - (r + gap), y
    if nearest == right:
        return x1 + (r + gap), y
    if nearest == down:
        return x, y0 - (r + gap)
    return x, y1 + (r + gap)


def _declutter(positions: dict, radii: dict, zones: list, min_gap: float = 1.5,
               iterations: int = 60) -> dict:
    """Pairwise repulsion pass so bubbles sized by very different engagement
    counts don't render on top of each other -- unlike circumplex.py's
    fixed-radius dots, radii vary per theme here, so the required
    separation between any two bubbles is their own radii, not a constant.

    Separation is deliberately horizontal-biased (Y_PUSH_DAMP). Only four
    distinct mention counts exist, so themes pile into four vertical stacks;
    an isotropic push resolves those stacks by sliding bubbles up and down,
    which moves them off their authored difficulty and makes the chart read
    as if frequency were the vertical axis. Damping the vertical component
    keeps height meaning difficulty and fans tied counts out sideways
    instead.

    Each bubble's centre is clamped back inside the box (inset by its own
    radius) after every repulsion step, so a bubble pushed outward by a
    crowded corner can never render with its edge outside the quadrant box.
    It's also pushed clear of `zones` -- the measured bounding boxes of the
    four corner labels -- so it can't render underneath the "Avoid" /
    "Consider" / "Investigate" / "Prioritise" text."""
    themes = list(positions.keys())
    coords = {t: list(positions[t]) for t in themes}

    def clamp(t: str) -> None:
        r = radii[t]
        coords[t][0] = min(max(coords[t][0], BOX_MIN + r), BOX_W - r)
        coords[t][1] = min(max(coords[t][1], BOX_MIN + r), BOX_H - r)
        for zone in zones:
            coords[t][0], coords[t][1] = _push_clear_of_zone(coords[t][0], coords[t][1], r, zone)
        coords[t][0] = min(max(coords[t][0], BOX_MIN + r), BOX_W - r)
        coords[t][1] = min(max(coords[t][1], BOX_MIN + r), BOX_H - r)

    for t in themes:
        clamp(t)

    for _ in range(iterations):
        moved = False
        for i in range(len(themes)):
            for j in range(i + 1, len(themes)):
                t1, t2 = themes[i], themes[j]
                min_dist = radii[t1] + radii[t2] + min_gap
                dx = coords[t2][0] - coords[t1][0]
                dy = coords[t2][1] - coords[t1][1]
                dist = math.hypot(dx, dy)
                if dist < min_dist:
                    moved = True
                    ux, uy = (dx / dist, dy / dist) if dist > 1e-6 else (1.0, 0.0)
                    # Bias the separation sideways: damp the vertical
                    # component and put the lost travel back into the
                    # horizontal one, so a stack of tied counts spreads out
                    # rather than climbing off its difficulty row.
                    uy *= Y_PUSH_DAMP
                    norm = math.hypot(ux, uy)
                    if norm < 1e-6:
                        ux, uy = 1.0, 0.0
                    else:
                        ux, uy = ux / norm, uy / norm
                    push = (min_dist - dist) / 2
                    coords[t1][0] -= ux * push
                    coords[t1][1] -= uy * push
                    coords[t2][0] += ux * push
                    coords[t2][1] += uy * push
                    clamp(t1)
                    clamp(t2)
        if not moved:
            break
    return {t: (coords[t][0], coords[t][1]) for t in themes}


def _data_bbox(ax, artist, pad: float = 1.5) -> tuple:
    """Rendered footprint of a text artist, in data coordinates, padded."""
    fig = ax.figure
    bb = artist.get_window_extent(renderer=fig.canvas.get_renderer())
    bb = bb.transformed(ax.transData.inverted())
    return bb.x0 - pad, bb.y0 - pad, bb.x1 + pad, bb.y1 + pad


def _axis_triplet(ax, x: float, y: float, bold_text: str, low_text: str, high_text: str,
                  rotation: int, fontsize: float = 11.0) -> None:
    """Render "Low - <bold label> - High" as three pieces so only the axis
    name is bold, matching the source deck. The bold centre piece is drawn
    first and measured (its rendered length varies with font/DPI), then the
    flanking words are butted up against the measured ends rather than
    offset by a guessed constant.

    Centring is on the *whole* composite, not on the bold word. The flanks are
    not the same length ("- High" runs wider than "Low-"), so anchoring the
    bold piece at `x` leaves the string a visible fraction of a percent off the
    box centre -- small enough to read as a rendering slip rather than a
    choice. All three pieces are therefore shifted by the measured difference
    once they exist."""
    fig = ax.figure
    vertical = rotation % 180 == 90
    centre = ax.text(x, y, bold_text, ha="center", va="center", rotation=rotation,
                     fontsize=fontsize, fontweight="bold", color=AXIS_LABEL_BLACK)
    fig.canvas.draw()
    x0, y0, x1, y1 = _data_bbox(ax, centre, pad=0.0)
    gap = 1.6
    pieces = [centre]
    if vertical:
        # rotation 90 reads bottom-to-top (low end at the bottom); 270 reads
        # top-to-bottom (low end at the top).
        low_at_bottom = rotation % 360 == 90
        lo_xy = (x, y0 - gap) if low_at_bottom else (x, y1 + gap)
        hi_xy = (x, y1 + gap) if low_at_bottom else (x, y0 - gap)
        lo_va = "top" if low_at_bottom else "bottom"
        hi_va = "bottom" if low_at_bottom else "top"
        pieces.append(ax.text(*lo_xy, low_text, ha="center", va=lo_va, rotation=rotation,
                              fontsize=fontsize, color=AXIS_LABEL_BLACK))
        pieces.append(ax.text(*hi_xy, high_text, ha="center", va=hi_va, rotation=rotation,
                              fontsize=fontsize, color=AXIS_LABEL_BLACK))
    else:
        pieces.append(ax.text(x0 - gap, y, low_text, ha="right", va="center",
                              fontsize=fontsize, color=AXIS_LABEL_BLACK))
        pieces.append(ax.text(x1 + gap, y, high_text, ha="left", va="center",
                              fontsize=fontsize, color=AXIS_LABEL_BLACK))

    # Re-centre the assembled string on (x, y) along the axis it runs down.
    fig.canvas.draw()
    boxes = [_data_bbox(ax, p, pad=0.0) for p in pieces]
    if vertical:
        span_lo, span_hi = min(b[1] for b in boxes), max(b[3] for b in boxes)
        shift = (y - (span_lo + span_hi) / 2.0, 1)
    else:
        span_lo, span_hi = min(b[0] for b in boxes), max(b[2] for b in boxes)
        shift = (x - (span_lo + span_hi) / 2.0, 0)
    delta, axis_index = shift
    for piece in pieces:
        pos = list(piece.get_position())
        pos[axis_index] += delta
        piece.set_position(tuple(pos))


def write_theme_priority_matrix(profiles: list[RespondentProfile], path: Path,
                                config=None,
                                title: str = TITLE, subtitle: str = SUBTITLE,
                                eyebrow: str = EYEBROW) -> bool:
    """Writes the opportunity prioritization quadrant PNG. Returns True if
    written (False if matplotlib isn't installed, or no opportunities are
    configured, mirroring the other optional chart writers)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Circle, Rectangle
    except ImportError:
        return False

    from .opportunities import load_opportunities

    opportunities = load_opportunities(config) if config is not None else []
    if not opportunities:
        logger.warning("No opportunities configured; skipping priority matrix.")
        return False

    items = [o.code for o in opportunities]
    by_code = {o.code: o for o in opportunities}
    metrics = {o.code: _opportunity_metrics(o) for o in opportunities}
    max_value = max(m[0] for m in metrics.values())
    max_count = max((m[2] for m in metrics.values()), default=0)
    radii = {c: _bubble_radius(m[2], max_count) for c, m in metrics.items()}
    raw_positions = {c: _to_box(m[0], m[1], max_value) for c, m in metrics.items()}
    if STRETCH_TO_FILL:
        xs = _stretch_axis({t: p[0] for t, p in raw_positions.items()}, BOX_W)
        ys = _stretch_axis({t: p[1] for t, p in raw_positions.items()}, BOX_H)
        raw_positions = {t: (xs[t], ys[t]) for t in raw_positions}

    # The header (eyebrow / title / subtitle) and the quadrant plot are laid
    # out in two different coordinate systems (figure-fraction vs. data), so
    # the axes get a fixed rectangle in figure-fraction space up front. That
    # way the header above it, and the caption/legend below it, are placed
    # relative to a rect that never moves -- nothing to accidentally overlap
    # by guessing at fig.text fractions that happen to land inside the axes.
    PAD_X = 26.0       # room left/right for the "Relative Difficulty" axis labels
    PAD_TOP = 11.0     # room above the box for the mirrored x-axis caption
    PAD_BOTTOM = 58.0  # room below the box for the x-axis caption + 8-item key

    # With aspect="equal", matplotlib fits the data into the *smaller* of the
    # axes rect's two physical dimensions and centers it in the other, leaving
    # dead space if the rect's aspect ratio doesn't already match the data's.
    # So the axes rect is sized in the same ratio as the data span up front.
    x_span = BOX_W + 2 * PAD_X
    y_span = BOX_H + PAD_TOP + PAD_BOTTOM
    axes_width_in = 11.2
    axes_height_in = axes_width_in * (y_span / x_span)
    side_margin_in = 0.55
    top_margin_in = 1.95 if title else 0.85  # eyebrow + title + subtitle stack
    bottom_margin_in = 0.35
    fig_w = axes_width_in + 2 * side_margin_in
    fig_h = axes_height_in + top_margin_in + bottom_margin_in

    with matplotlib.rc_context({"font.family": "sans-serif", "font.sans-serif": FONT_STACK}):
        fig = plt.figure(figsize=(fig_w, fig_h))
        fig.patch.set_facecolor("white")
        ax = fig.add_axes((side_margin_in / fig_w, bottom_margin_in / fig_h,
                           axes_width_in / fig_w, axes_height_in / fig_h))
        ax.set_xlim(BOX_MIN - PAD_X, BOX_W + PAD_X)
        ax.set_ylim(BOX_MIN - PAD_BOTTOM, BOX_H + PAD_TOP)
        ax.set_aspect("equal")
        ax.axis("off")

        # --- Header: small purple eyebrow, heavy title, grey subtitle. ---
        left = side_margin_in / fig_w
        if eyebrow:
            fig.text(left, 1.0 - 0.30 / fig_h, " ".join(eyebrow.upper()), fontsize=7.5,
                     fontweight="bold", color=EYEBROW_PURPLE, ha="left", va="top")
        if title:
            fig.text(left, 1.0 - 0.52 / fig_h, title, fontsize=27, fontweight="bold",
                     color="#000000", ha="left", va="top")
        if subtitle:
            fig.text(left, 1.0 - 1.28 / fig_h, "\n".join(textwrap.wrap(subtitle, width=118)),
                     fontsize=10.5, color=SUBTITLE_GREY, ha="left", va="top", linespacing=1.45)

        # --- Quadrant box: thin lavender frame everywhere, except the
        # Prioritise quadrant (high value, low difficulty -> bottom-right),
        # which gets its own bold border + tinted fill on top, exactly
        # matching the source chart's emphasis treatment. ---
        ax.add_patch(Rectangle((BOX_MIN, BOX_MIN), BOX_W, BOX_H, facecolor="none",
                               edgecolor=FAINT_LAVENDER, linewidth=1.4, zorder=1))
        ax.plot([MID_X, MID_X], [BOX_MIN, BOX_H], color=FAINT_LAVENDER, linewidth=1.4, zorder=1)
        ax.plot([BOX_MIN, BOX_W], [MID_Y, MID_Y], color=FAINT_LAVENDER, linewidth=1.4, zorder=1)
        ax.add_patch(Rectangle((MID_X, BOX_MIN), BOX_W - MID_X, MID_Y - BOX_MIN,
                               facecolor=PRIORITISE_FILL, edgecolor=PRIORITISE_ACCENT,
                               linewidth=2.2, zorder=2))

        quad_font = {"fontsize": 14, "fontweight": "bold"}
        pad = 3.0
        corner_labels = [
            ax.text(BOX_MIN + pad, BOX_H - pad, "Avoid", ha="left", va="top",
                    color=FAINT_LAVENDER, zorder=3, **quad_font),
            ax.text(BOX_W - pad, BOX_H - pad, "Consider", ha="right", va="top",
                    color=QUAD_LABEL_PURPLE, zorder=3, **quad_font),
            ax.text(BOX_MIN + pad, BOX_MIN + pad, "Investigate", ha="left", va="bottom",
                    color=QUAD_LABEL_PURPLE, zorder=3, **quad_font),
            ax.text(BOX_W - pad, BOX_MIN + pad, "Prioritise", ha="right", va="bottom",
                    color=PRIORITISE_ACCENT, zorder=3, **quad_font),
        ]

        # Keep-out rectangles are the labels' *measured* footprints rather
        # than hard-coded guesses, so they stay correct if the font, figure
        # size or label text ever changes.
        fig.canvas.draw()
        zones = [_data_bbox(ax, lbl) for lbl in corner_labels]
        positions = _declutter(raw_positions, radii, zones)

        # x-axis caption, mirrored above and below the box as in the source.
        _axis_triplet(ax, MID_X, BOX_H + PAD_TOP * 0.45, "Relative Value", "Low–", "– High", 0)
        _axis_triplet(ax, MID_X, BOX_MIN - PAD_BOTTOM * 0.30, "Relative Value",
                      "Low–", "– High", 0)
        ax.text(MID_X, BOX_MIN - PAD_BOTTOM * 0.30 - 4.2,
                "number of educators who raised the theme", ha="center", va="top",
                fontsize=8.5, color=SUBTITLE_GREY)

        # y-axis: BOX_MIN (bottom) is low difficulty, BOX_H (top) is high
        # difficulty (see _theme_priority_metrics) -- both sides must agree on
        # which end reads "High" vs. "Low". Left reads bottom-up, right reads
        # top-down, so "High" sits at the top on both.
        _axis_triplet(ax, BOX_MIN - PAD_X * 0.55, MID_Y, "Relative Difficulty", "Low –", "– High", 90)
        _axis_triplet(ax, BOX_W + PAD_X * 0.55, MID_Y, "Relative Difficulty", "Low –", "– High", 270)

        # The bubbles carry short codes, not titles. Seven opportunity titles
        # run to nine words each; wrapped into a circle they are unreadable at
        # any bubble size the frame allows, and enlarging the bubbles to fit
        # would make size -- which encodes the people count -- meaningless.
        for code in items:
            x, y = positions[code]
            r = radii[code]
            opp = by_code[code]
            ax.add_patch(Circle((x, y), r, facecolor=BUBBLE_PURPLE, edgecolor="none", zorder=4))
            ax.text(x, y + r * 0.16, code, ha="center", va="center", color="white",
                    fontweight="bold", fontsize=max(9.0, min(13.0, r * 1.15)), zorder=5)
            ax.text(x, y - r * 0.42, f"{opp.mentions}", ha="center", va="center",
                    color="white", fontsize=max(6.5, min(9.0, r * 0.70)), zorder=5)

        # Key: two columns of four beneath the box, plus the size note.
        # `key_top` must clear the mirrored x-axis caption at
        # BOX_MIN - PAD_BOTTOM * 0.32, and `col_w` must exceed the widest
        # rendered title -- the two columns collided at BOX_W / 2.
        key_top = BOX_MIN - PAD_BOTTOM * 0.42
        col_w = 88.0
        for i, code in enumerate(items):
            col, row = divmod(i, 4)
            opp = by_code[code]
            kx = col * col_w
            ky = key_top - 4.0 - row * 5.0
            ax.text(kx, ky, code, ha="left", va="center", fontsize=8.5,
                    fontweight="bold", color=BUBBLE_PURPLE)
            ax.text(kx + 6.5, ky, f"{opp.title}  ({opp.mentions})", ha="left", va="center",
                    fontsize=7.5, color="#333333")

        legend_y = key_top - 4.0 - 4 * 5.0 - 5.0
        ax.add_patch(Circle((2.2, legend_y), 2.2, facecolor=BUBBLE_PURPLE,
                            edgecolor="none", zorder=4))
        ax.text(6.5, legend_y, "Size  =  number of people who raised it", ha="left",
                va="center", fontsize=8.5, fontweight="bold", color="#333333")
        ax.text(col_w, legend_y,
                "Value = coded mentions (measured).\nDifficulty = authored estimate "
                "(config/opportunities.yaml).",
                ha="left", va="center", fontsize=7.5, fontstyle="italic",
                color="#8A8A8A", linespacing=1.4)

        fig.savefig(path, dpi=200, facecolor="white")
        plt.close(fig)
    return True