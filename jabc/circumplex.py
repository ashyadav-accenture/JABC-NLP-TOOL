"""Optional output: the Factor Circumplex.

Plots the ten factors from the approved diagram. The two axes come from
different places, and keeping them apart is the whole point of the chart:

    horizontal   AUTHORED. "Fundamental factor for consideration" vs "Add-ons"
                 is an editorial judgement about how decisive a factor is,
                 fixed when the diagram was drawn. Each item's x is transcribed
                 from config/motivators_barriers.yaml and is never recomputed
                 -- nothing in this pipeline measures that quality, so deriving
                 it from a number would quietly overwrite a human decision with
                 something that does not mean the same thing.

    vertical     MEASURED. Distance from the centre is the coded frequency of
                 mention, normalised against the highest-frequency factor.
                 Motivators sit above the line (positive effect), barriers
                 below (negative effect).

Circle size also tracks frequency, so it reinforces the vertical reading rather
than introducing a third variable. The ring around each circle is a plain family
band -- blue for motivators, orange for barriers. It used to be a donut
breakdown of that factor's mentions by Brand Persona; ten small multiples of a
two-slice pie, several of them overlapping, were not readable at ring size, so
that breakdown moved to the deck as one full-size labelled pie per factor. The
shares themselves are unchanged and still exported by `layout_dataframe`.

Topics are shown as hand-drawn icons rather than text -- ten labels will not
fit legibly inside ten circles -- with a key below the plot. The icons are
built from primitive shapes because matplotlib's Agg backend cannot render
colour emoji (they come out as blank "tofu" boxes).
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

from .config_loader import PERSONAS, persona_groups
from .drivers import analyze_drivers
from .models import RespondentProfile

logger = logging.getLogger(__name__)

# Per-classification-persona colors. Retained because the shares themselves are
# still computed and exported per persona (layout_dataframe keeps a column each,
# so a merged wedge can be traced back to its halves); the chart itself draws
# the merged groups below.
PERSONA_COLORS = {
    "brand_champion": "#3C9A5F",
    "non_active_supporter": "#F0A857",
    "brand_prospect": "#4C8FD4",
    "brand_newbie": "#AFAFAF",
}

# The two reported personas. Green vs blue keeps the pair separable in
# greyscale and for red-green color vision deficiency, and each is the darker,
# saturated version of its former pair leader so the chart reads as a
# consolidation of the old one rather than an unrelated palette.
PERSONA_GROUP_COLORS = {
    "established_supporters": "#3C9A5F",
    "potential_adopters": "#4C8FD4",
}

# The ring on the circumplex is now a plain family band, not a breakdown: blue
# for motivators, orange for barriers. The persona split it used to carry is
# still computed and exported (layout_dataframe, and one pie per factor in the
# deck) -- it was simply unreadable at ring size on ten overlapping circles.
KIND_RING_COLORS = {
    "motivator": "#2F6FB5",
    "barrier": "#E08A2E",
}


def group_color(group_key: str, index: int = 0) -> str:
    """Ring color for a reported group. A group renamed in persona_rules.yaml
    still gets a color rather than crashing the chart mid-render."""
    fallback = list(PERSONA_GROUP_COLORS.values()) + ["#F0A857", "#AFAFAF"]
    return PERSONA_GROUP_COLORS.get(group_key, fallback[index % len(fallback)])


def group_shares(persona_shares: dict, config=None) -> dict[str, float]:
    """Collapses per-persona ring shares onto the reported groups. Shares are
    fractions of the same respondent total, so they add directly."""
    return {
        group_key: sum(persona_shares.get(member, 0.0) for member in members)
        for group_key, members in persona_groups(config).items()
    }

# Motivators and barriers keep distinct fills so the two families stay
# separable independently of which half of the plot they land in.
KIND_STYLE = {
    "motivator": {"fill": "#EAF3FB", "edge": "#2F5C99", "ink": "#20406B"},
    "barrier": {"fill": "#FDF0EC", "edge": "#B5533A", "ink": "#8A3A25"},
}

Y_SPAN = 0.60       # highest-frequency factor sits at this fraction of the radius
RING_W = 0.12
DOT_R_MIN = 0.38
DOT_R_MAX = 0.56


# ---------------------------------------------------------------------------
# Icons
# ---------------------------------------------------------------------------
# Each drawer fills a box of half-width `s` centred on (cx, cy), in the axes'
# data coordinates, using a single ink colour so the glyph reads at any size.

def _icon_book(ax, cx, cy, s, c, z):
    from matplotlib.patches import Polygon
    for sx in (-1, 1):
        ax.add_patch(Polygon([(cx, cy + s * 0.52), (cx + sx * s * 0.72, cy + s * 0.34),
                                (cx + sx * s * 0.72, cy - s * 0.46), (cx, cy - s * 0.30)],
                               closed=True, facecolor="none", edgecolor=c,
                               linewidth=1.3, zorder=z))
    ax.plot([cx, cx], [cy + s * 0.52, cy - s * 0.30], color=c, linewidth=1.3, zorder=z)


def _icon_package(ax, cx, cy, s, c, z):
    from matplotlib.patches import Rectangle
    ax.add_patch(Rectangle((cx - s * 0.62, cy - s * 0.50), s * 1.24, s * 1.0,
                             facecolor="none", edgecolor=c, linewidth=1.3, zorder=z))
    ax.plot([cx - s * 0.62, cx + s * 0.62], [cy + s * 0.14] * 2, color=c, linewidth=1.2, zorder=z)
    ax.plot([cx, cx], [cy + s * 0.50, cy + s * 0.14], color=c, linewidth=1.2, zorder=z)


def _icon_referral(ax, cx, cy, s, c, z):
    from matplotlib.patches import FancyBboxPatch, Polygon
    for dx, dy, w, h in ((-0.30, 0.18, 0.80, 0.46), (0.26, -0.20, 0.70, 0.40)):
        ax.add_patch(FancyBboxPatch((cx + s * dx - s * w / 2, cy + s * dy - s * h / 2),
                                      s * w, s * h,
                                      boxstyle=f"round,pad=0,rounding_size={s * 0.12}",
                                      facecolor="white", edgecolor=c, linewidth=1.2, zorder=z))
    ax.add_patch(Polygon([(cx - s * 0.44, cy - s * 0.05), (cx - s * 0.30, cy - s * 0.26),
                            (cx - s * 0.18, cy - s * 0.05)],
                           closed=True, facecolor=c, edgecolor="none", zorder=z))


def _icon_spark(ax, cx, cy, s, c, z):
    from matplotlib.patches import Polygon
    pts = []
    for i in range(8):
        ang = math.radians(90 + i * 45)
        r = s * (0.66 if i % 2 == 0 else 0.24)
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    ax.add_patch(Polygon(pts, closed=True, facecolor="none", edgecolor=c,
                           linewidth=1.3, zorder=z))


def _icon_expert(ax, cx, cy, s, c, z):
    from matplotlib.patches import Arc, Circle
    ax.add_patch(Circle((cx, cy + s * 0.30), s * 0.28, facecolor="none",
                          edgecolor=c, linewidth=1.3, zorder=z))
    ax.add_patch(Arc((cx, cy - s * 0.42), s * 1.16, s * 1.0,
                       theta1=20, theta2=160, color=c, linewidth=1.3, zorder=z))


def _icon_stale_doc(ax, cx, cy, s, c, z):
    from matplotlib.patches import Polygon
    ax.add_patch(Polygon([(cx - s * 0.48, cy + s * 0.56), (cx + s * 0.22, cy + s * 0.56),
                            (cx + s * 0.50, cy + s * 0.26), (cx + s * 0.50, cy - s * 0.56),
                            (cx - s * 0.48, cy - s * 0.56)],
                           closed=True, facecolor="none", edgecolor=c, linewidth=1.3, zorder=z))
    ax.plot([cx + s * 0.22, cx + s * 0.50], [cy + s * 0.56, cy + s * 0.26],
             color=c, linewidth=1.1, zorder=z)
    for k, dy in enumerate((0.06, -0.16, -0.38)):
        ax.plot([cx - s * 0.28, cx + s * (0.28 - k * 0.10)], [cy + s * dy] * 2,
                 color=c, linewidth=1.1, zorder=z)


def _icon_hourglass(ax, cx, cy, s, c, z):
    from matplotlib.patches import Polygon
    ax.add_patch(Polygon([(cx - s * 0.46, cy + s * 0.56), (cx + s * 0.46, cy + s * 0.56),
                            (cx, cy)], closed=True, facecolor=c, edgecolor=c,
                           linewidth=1.2, zorder=z))
    ax.add_patch(Polygon([(cx - s * 0.46, cy - s * 0.56), (cx + s * 0.46, cy - s * 0.56),
                            (cx, cy)], closed=True, facecolor="none", edgecolor=c,
                           linewidth=1.2, zorder=z))
    for dy in (0.60, -0.60):
        ax.plot([cx - s * 0.54, cx + s * 0.54], [cy + s * dy] * 2,
                 color=c, linewidth=1.4, zorder=z, solid_capstyle="round")


def _icon_calendar(ax, cx, cy, s, c, z):
    from matplotlib.patches import Rectangle
    ax.add_patch(Rectangle((cx - s * 0.56, cy - s * 0.52), s * 1.12, s * 1.0,
                             facecolor="none", edgecolor=c, linewidth=1.3, zorder=z))
    ax.add_patch(Rectangle((cx - s * 0.56, cy + s * 0.24), s * 1.12, s * 0.24,
                             facecolor=c, edgecolor=c, linewidth=1.0, zorder=z))
    for gx in (-0.28, 0.0, 0.28):
        for gy in (-0.04, -0.30):
            ax.plot([cx + s * gx], [cy + s * gy], marker="s", markersize=1.7,
                     color=c, zorder=z)


def _icon_monitor(ax, cx, cy, s, c, z):
    from matplotlib.patches import Rectangle
    ax.add_patch(Rectangle((cx - s * 0.62, cy - s * 0.20), s * 1.24, s * 0.80,
                             facecolor="none", edgecolor=c, linewidth=1.3, zorder=z))
    ax.plot([cx - s * 0.62, cx + s * 0.62], [cy + s * 0.38] * 2, color=c,
             linewidth=1.1, zorder=z)
    ax.plot([cx, cx], [cy - s * 0.20, cy - s * 0.44], color=c, linewidth=1.3, zorder=z)
    ax.plot([cx - s * 0.34, cx + s * 0.34], [cy - s * 0.44] * 2, color=c,
             linewidth=1.4, zorder=z, solid_capstyle="round")


def _icon_warning(ax, cx, cy, s, c, z):
    from matplotlib.patches import Polygon
    ax.add_patch(Polygon([(cx, cy + s * 0.58), (cx + s * 0.62, cy - s * 0.48),
                            (cx - s * 0.62, cy - s * 0.48)],
                           closed=True, facecolor="none", edgecolor=c,
                           linewidth=1.3, zorder=z))
    ax.plot([cx, cx], [cy + s * 0.24, cy - s * 0.14], color=c, linewidth=1.5,
             zorder=z, solid_capstyle="round")
    ax.plot([cx], [cy - s * 0.31], marker="o", markersize=1.9, color=c, zorder=z)


def _icon_puzzle(ax, cx, cy, s, c, z):
    """Curriculum integration: a piece that has to be made to fit. The tab and
    the socket are on opposite edges so the "does this slot in?" reading
    survives at circle size."""
    from matplotlib.patches import Circle, Rectangle
    ax.add_patch(Rectangle((cx - s * 0.52, cy - s * 0.52), s * 1.04, s * 1.04,
                             facecolor="none", edgecolor=c, linewidth=1.3, zorder=z))
    # Tab pushing out of the right edge, socket cut into the top edge.
    ax.add_patch(Circle((cx + s * 0.52, cy), s * 0.20, facecolor="white",
                          edgecolor=c, linewidth=1.3, zorder=z))
    ax.add_patch(Circle((cx, cy + s * 0.52), s * 0.20, facecolor="white",
                          edgecolor=c, linewidth=1.3, zorder=z))


def _icon_megaphone(ax, cx, cy, s, c, z):
    """Low awareness: the announcement that is not reaching anyone. Drawn as an
    outline cone with two emission arcs -- the arcs are what separate it from
    the package and monitor glyphs at a glance."""
    from matplotlib.patches import Arc, Polygon
    ax.add_patch(Polygon([(cx - s * 0.62, cy + s * 0.30), (cx - s * 0.62, cy - s * 0.30),
                            (cx + s * 0.06, cy - s * 0.58), (cx + s * 0.06, cy + s * 0.58)],
                           closed=True, facecolor="none", edgecolor=c,
                           linewidth=1.3, zorder=z))
    for scale in (0.44, 0.78):
        ax.add_patch(Arc((cx + s * 0.10, cy), s * scale, s * scale * 1.5,
                           theta1=-58, theta2=58, color=c, linewidth=1.2, zorder=z))


ICON_DRAWERS = {
    "book": _icon_book,
    "package": _icon_package,
    "referral": _icon_referral,
    "spark": _icon_spark,
    "expert": _icon_expert,
    "stale_doc": _icon_stale_doc,
    "hourglass": _icon_hourglass,
    "calendar": _icon_calendar,
    "monitor": _icon_monitor,
    "warning": _icon_warning,
    "puzzle": _icon_puzzle,
    "megaphone": _icon_megaphone,
}


def _draw_icon(ax, name, cx, cy, size, color, zorder=6):
    drawer = ICON_DRAWERS.get(name)
    if drawer is None:
        logger.warning("Unknown circumplex icon '%s'; drawing nothing.", name)
        return
    drawer(ax, cx, cy, size, color, zorder)


# ---------------------------------------------------------------------------
# Layout resolution
# ---------------------------------------------------------------------------

def resolve_layout(profiles: list[RespondentProfile], config) -> list[dict]:
    """Joins the authored layout to the coded items and the persona shares.

    Returns one record per plotted factor. Raises on an unknown `ref` rather
    than skipping it -- a typo would silently drop a factor off the chart, and
    a missing circle is far harder to notice than an error.
    """
    raw = getattr(config, "motivators_barriers", {}) or {}
    layout = raw.get("circumplex_layout", {}) or {}
    entries = layout.get("items", []) or []
    if not entries:
        return []

    stats = {st.item.key: st for st in analyze_drivers(profiles, config)}

    records = []
    for entry in entries:
        ref = entry.get("ref")
        st = stats.get(ref)
        if st is None:
            raise ValueError(
                f"motivators_barriers.yaml: circumplex_layout references unknown "
                f"item '{ref}'. Known items: {sorted(stats)}"
            )
        records.append({
            "key": ref,
            "code": st.item.code,
            "label": st.item.label,
            "kind": st.item.kind,
            "frequency": st.item.frequency,
            "x": float(entry.get("x", 0.0)),
            "icon": entry.get("icon", ""),
            "persona_shares": st.persona_shares,
            "mention_count": st.mention_count,
            "respondent_count": st.respondent_count,
            "well_evidenced": st.well_evidenced,
        })
    return records


def layout_dataframe(records: list[dict], config=None):
    """Sidecar table: which numbers were authored and which were measured."""
    import pandas as pd

    max_freq = max((r["frequency"] for r in records), default=1) or 1
    rows = []
    for r in records:
        sign = 1 if r["kind"] == "motivator" else -1
        row = {
            "code": r["code"],
            "factor": r["label"],
            "kind": r["kind"],
            "coded_frequency": r["frequency"],
            "x_authored": r["x"],
            "y_from_frequency": round(sign * r["frequency"] / max_freq, 3),
            "detected_mentions": r["mention_count"],
            "detected_respondents": r["respondent_count"],
            "ring_well_evidenced": r["well_evidenced"],
        }
        # The plotted wedges first, then the per-persona shares they were built
        # from, so a merged wedge on the chart can be read back to its halves.
        for group_key, share in group_shares(r["persona_shares"], config).items():
            row[f"share_{group_key}"] = round(share, 3)
        for persona in PERSONAS:
            row[f"share_{persona}"] = round(r["persona_shares"].get(persona, 0.0), 3)
        rows.append(row)
    return pd.DataFrame(rows)


def _dot_radius(frequency: int, min_freq: int, max_freq: int) -> float:
    """Radius scaled by frequency on AREA, not radius: doubling the radius
    reads as roughly four times the size and would overstate the gap."""
    if max_freq <= min_freq:
        return (DOT_R_MIN + DOT_R_MAX) / 2
    t = (frequency - min_freq) / (max_freq - min_freq)
    return math.sqrt(DOT_R_MIN ** 2 + t * (DOT_R_MAX ** 2 - DOT_R_MIN ** 2))


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------

def write_driver_circumplex(profiles: list[RespondentProfile], path: Path, config) -> bool:
    """Writes the Factor Circumplex PNG. Returns True if written (False if
    matplotlib isn't installed, mirroring write_heatmap)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Circle, Wedge
    except ImportError:
        logger.warning("matplotlib not available; skipping optional circumplex chart.")
        return False

    records = resolve_layout(profiles, config)
    if not records:
        logger.warning("No circumplex_layout configured; skipping circumplex chart.")
        return False

    raw = getattr(config, "motivators_barriers", {}) or {}
    layout = raw.get("circumplex_layout", {}) or {}
    axis_labels = layout.get("axis_labels", {})
    quadrants = layout.get("quadrant_labels", {})

    R = 5.0
    n_key_rows = math.ceil(len(records) / 2)
    row_h = 0.52
    key_top = -R * 1.24
    key_bottom = key_top - 0.55 - n_key_rows * row_h - 0.60 - 0.50 - 2 * row_h
    y_lo, y_hi = key_bottom - 0.6, R * 1.18
    x_half = R * 1.42

    width_in = 12.0
    fig, ax = plt.subplots(figsize=(width_in, width_in * (y_hi - y_lo) / (2 * x_half)))
    ax.set_xlim(-x_half, x_half)
    ax.set_ylim(y_lo, y_hi)
    ax.set_aspect("equal")
    ax.axis("off")

    ax.add_patch(Circle((0, 0), R, facecolor="none", edgecolor="#2F5C99",
                          linewidth=1.6, zorder=1))
    ax.plot([-R, R], [0, 0], color="#333333", linewidth=1.1, zorder=1)
    ax.plot([0, 0], [-R, R], color="#333333", linewidth=1.1, zorder=1)

    axis_font = {"fontsize": 9.5, "fontweight": "bold", "color": "#333333"}
    ax.text(0, R * 1.10, axis_labels.get("top", "HIGH POSITIVE EFFECT"),
             ha="center", va="bottom", **axis_font)
    note = axis_labels.get("top_note", "")
    if note:
        ax.text(0, R * 1.045, f"({note})", ha="center", va="bottom",
                 fontsize=8.5, fontstyle="italic", color="#8A8A8A")
    ax.text(0, -R * 1.10, axis_labels.get("bottom", "HIGH NEGATIVE EFFECT"),
             ha="center", va="top", **axis_font)
    ax.text(-R * 1.07, 0, axis_labels.get("left", ""), ha="right", va="center", **axis_font)
    ax.text(R * 1.07, 0, axis_labels.get("right", ""), ha="left", va="center", **axis_font)

    label_r = R * 1.20
    for angle_deg, key in ((135, "upper_left"), (45, "upper_right"),
                            (225, "lower_left"), (315, "lower_right")):
        text = quadrants.get(key, "")
        if not text:
            continue
        rad = math.radians(angle_deg)
        # Tangent-following rotation, normalized into (-90, 90] so opposite
        # corners match and neither renders upside down, which a naive
        # `angle - 90` does for the two lower corners.
        rotation = ((angle_deg - 90 + 90) % 180) - 90
        ax.text(label_r * math.cos(rad), label_r * math.sin(rad), text,
                 ha="center", va="center", fontsize=9, fontweight="bold",
                 color="#8A8A8A", rotation=rotation, rotation_mode="anchor")

    frequencies = [r["frequency"] for r in records]
    min_freq, max_freq = min(frequencies), max(frequencies)

    for rec in records:
        r = _dot_radius(rec["frequency"], min_freq, max_freq)
        # Sign, not measured valence: a motivator's frequency reads upward as
        # positive effect, a barrier's downward as negative effect.
        sign = 1 if rec["kind"] == "motivator" else -1
        rec["_pos"] = (rec["x"] * R,
                        sign * (rec["frequency"] / max_freq) * R * Y_SPAN,
                        r)

    # Three passes rather than one circle at a time. Both position axes are
    # fixed -- x is authored and y is the frequency -- so circles cannot be
    # nudged apart, and two factors that tie on frequency (B3 and B4 both at 8)
    # necessarily share a y. Drawing each circle complete in turn let a later
    # circle's opaque fill cover an earlier one's persona ring, destroying data
    # rather than merely crowding it. Filling everything first, then every ring,
    # keeps all ten rings fully visible however much the discs overlap.
    for rec in records:
        x, y, r = rec["_pos"]
        style = KIND_STYLE[rec["kind"]]
        ax.add_patch(Circle((x, y), r, facecolor=style["fill"], edgecolor=style["edge"],
                              linewidth=1.4, zorder=3))

    for rec in records:
        x, y, r = rec["_pos"]
        _draw_icon(ax, rec["icon"], x, y, r * 0.62, KIND_STYLE[rec["kind"]]["ink"], zorder=6)

    for rec in records:
        x, y, r = rec["_pos"]
        ax.add_patch(Wedge((x, y), r, 0.0, 360.0, width=RING_W,
                             facecolor=KIND_RING_COLORS[rec["kind"]], edgecolor="none",
                             zorder=7))

    for rec in records:
        x, y, r = rec["_pos"]
        ax.text(x, y - r - 0.20, rec["code"], ha="center", va="top", fontsize=8,
                 fontweight="bold", color=KIND_STYLE[rec["kind"]]["ink"], zorder=8)

    # --- Key ---------------------------------------------------------------
    # In data coordinates rather than via bbox_to_anchor's axes-fraction
    # default, since a legend anchored near the axes edge is a known matplotlib
    # tight-bbox sizing quirk that clipped it in an earlier pass.
    # The right column starts clear of the longest left-column entry rather
    # than at the midpoint: factor labels are full sentences ("Ready-to-use
    # resources that reduce teacher preparation"), and a column split by
    # geometry rather than by text width overlaps them.
    col_x = [-R * 1.38, R * 0.16]
    ax.text(col_x[0], key_top, "Factors", ha="left", va="top", fontsize=11,
             fontweight="bold", color="#333333")
    ax.text(col_x[0] + 1.05, key_top + 0.01, "(coded frequency of mention)",
             ha="left", va="top", fontsize=8.5, fontstyle="italic", color="#8A8A8A")

    for i, rec in enumerate(records):
        col, row = divmod(i, n_key_rows)
        x0 = col_x[col]
        row_y = key_top - 0.60 - row * row_h
        style = KIND_STYLE[rec["kind"]]
        ax.add_patch(Circle((x0 + 0.20, row_y), 0.19, facecolor=style["fill"],
                              edgecolor=style["edge"], linewidth=1.1, zorder=4, clip_on=False))
        _draw_icon(ax, rec["icon"], x0 + 0.20, row_y, 0.13, style["ink"], zorder=6)
        ax.text(x0 + 0.52, row_y, f"{rec['code']}  {rec['label']}  ({rec['frequency']})",
                 ha="left", va="center", fontsize=8.2, color="#333333")

    persona_y = key_top - 0.60 - n_key_rows * row_h - 0.60
    ax.text(col_x[0], persona_y, "Ring", ha="left", va="top", fontsize=11,
             fontweight="bold", color="#333333")
    ax.text(col_x[0] + 0.65, persona_y + 0.01, "(which family the factor belongs to)",
             ha="left", va="top", fontsize=8.5, fontstyle="italic", color="#8A8A8A")
    for i, (kind, label) in enumerate((("motivator", "Motivator"), ("barrier", "Barrier"))):
        x0 = col_x[0] + i * 3.4
        row_y = persona_y - 0.50
        ax.add_patch(Circle((x0 + 0.20, row_y), 0.14, facecolor=KIND_RING_COLORS[kind],
                              edgecolor="none", zorder=4, clip_on=False))
        ax.text(x0 + 0.52, row_y, label, ha="left",
                 va="center", fontsize=8.5, color="#333333")

    ax.text(col_x[1], persona_y,
             "Vertical position and circle size = coded frequency of\n"
             "mention; motivators read upward, barriers downward.\n"
             "Horizontal position is set by the approved diagram --\n"
             "an editorial judgement, not a measurement, so it is\n"
             "never recomputed from the data.\n"
             "Who raised each factor is in the deck, one pie per factor.",
             ha="left", va="top", fontsize=8.5, fontstyle="italic",
             color="#8A8A8A", linespacing=1.5)

    fig.suptitle("Factor Circumplex", fontsize=17, fontweight="bold",
                  color="#1a1a1a", y=0.968)

    # pad_inches guards against matplotlib's tight-bbox calculation slightly
    # under-measuring rotated text (the diagonal quadrant labels), which would
    # otherwise get a sliver clipped off their leading edge.
    fig.savefig(path, dpi=150, bbox_inches="tight", pad_inches=0.35)
    plt.close(fig)
    return True
