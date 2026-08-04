# Implementing the AI Sentiment Circumplex Visualization

## Overview

The current implementation is designed around the first image: a **Theme Sentiment Circumplex**.

The target visualization in the second image is structurally different. It is an **AI Sentiment Circumplex** that plots organizations, partners, or respondents based on their overall emotional disposition toward GenAI.

The key change is:

> The current visualization plots **themes**.  
> The target visualization plots **organizations/respondents/partners**.

The recommended implementation therefore separates these two visualizations.

---

# 1. Main Changes Required

To reproduce the target diagram:

1. Use a larger circumplex relative to the page.
2. Remove the large circular theme bubbles.
3. Use small circular organization/company markers.
4. Place each organization based on its overall emotional disposition.
5. Use the organization logo or icon as the marker.
6. Color the marker border by organization type:
   - Blue = For Profit
   - Orange = Not for Profit
7. Add emotional descriptor words around each quadrant.
8. Remove the Theme and Brand Persona legends from this visualization.
9. Use the left side for explanatory text.
10. Use the right side for the actual circumplex.

---

# 2. Important Architectural Change

The current implementation uses:

```python
THEMES
```

as the things being plotted.

The target diagram should instead plot:

```text
Organizations / Respondents / Partners
```

A separate organization-level data model is therefore recommended.

For example:

```python
@dataclass
class OrganizationSentiment:
    name: str
    horizontal: float
    vertical: float
    organization_type: str
    logo_path: Path | None = None
```

You do not necessarily need to use this exact dataclass immediately, but the important concept is that the circumplex should operate on organization-level sentiment data rather than the six themes.

---

# 3. Replace `write_theme_circumplex`

The following version is designed to reproduce the structure of the second reference image.

```python
def write_theme_circumplex(
    profiles: list[RespondentProfile],
    path: Path,
) -> bool:
    """
    Writes an AI sentiment circumplex visualization.

    The visualization differs from the theme circumplex:

    - The circumplex represents organizations/respondents.
    - Each organization's position is based on aggregate positive and negative
      emotional affect.
    - Blue outline = For Profit.
    - Orange outline = Not for Profit.
    - The left side contains explanatory narrative.
    - The right side contains the Watson & Tellegen circumplex.
    """

    try:
        import matplotlib

        matplotlib.use("Agg")

        import matplotlib.pyplot as plt
        from matplotlib.patches import Circle

    except ImportError:
        logger.warning(
            "matplotlib not available; skipping optional circumplex chart."
        )
        return False

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    CIRCUMPLEX_RADIUS = 1.0

    FOR_PROFIT_COLOR = "#0878D1"
    NOT_FOR_PROFIT_COLOR = "#F47C20"

    TEXT_COLOR = "#444444"
    LIGHT_TEXT_COLOR = "#777777"

    # ------------------------------------------------------------------
    # Create the figure
    # ------------------------------------------------------------------

    fig = plt.figure(figsize=(13.5, 7.5))

    # Left text panel
    text_ax = fig.add_axes(
        [0.03, 0.08, 0.39, 0.84]
    )

    # Right circumplex panel
    ax = fig.add_axes(
        [0.47, 0.12, 0.50, 0.76]
    )

    text_ax.axis("off")
    ax.set_aspect("equal")
    ax.axis("off")

    # ------------------------------------------------------------------
    # LEFT PANEL
    # ------------------------------------------------------------------

    text_ax.text(
        0.00,
        0.96,
        "Key Insights",
        fontsize=9,
        fontweight="bold",
        color="#7B1FA2",
        va="top",
    )

    text_ax.text(
        0.00,
        0.91,
        "AI Sentiment",
        fontsize=29,
        fontweight="bold",
        color="#000000",
        va="top",
    )

    intro_text = (
        "Using the interview insights with the\n"
        "Watson & Tellegen Circumplex Model,\n"
        "we have organized our partners based\n"
        "on their overall "
    )

    text_ax.text(
        0.04,
        0.72,
        intro_text,
        fontsize=12,
        color=TEXT_COLOR,
        va="top",
        linespacing=1.35,
    )

    text_ax.text(
        0.04,
        0.595,
        "emotional",
        fontsize=12,
        fontweight="bold",
        color="#7B1FA2",
        va="top",
    )

    text_ax.text(
        0.155,
        0.595,
        " disposition\n"
        "towards GenAI.",
        fontsize=12,
        color=TEXT_COLOR,
        va="top",
        linespacing=1.35,
    )

    text_ax.text(
        0.04,
        0.425,
        "Organizations whose sentiments fall\n"
        "into the purple quadrant have ",
        fontsize=12,
        color=TEXT_COLOR,
        va="top",
        linespacing=1.35,
    )

    text_ax.text(
        0.04,
        0.338,
        "already",
        fontsize=12,
        fontweight="bold",
        color="#7B1FA2",
        va="top",
    )

    text_ax.text(
        0.04,
        0.285,
        "realized the value of GenAI and are\n"
        "actively pursuing new opportunities.",
        fontsize=12,
        color=TEXT_COLOR,
        va="top",
        linespacing=1.35,
    )

    text_ax.text(
        0.04,
        0.115,
        "For those that do not fall into the\n"
        "purple quadrant, we need to help them ",
        fontsize=12,
        color=TEXT_COLOR,
        va="top",
        linespacing=1.35,
    )

    text_ax.text(
        0.04,
        0.025,
        "understand",
        fontsize=12,
        fontweight="bold",
        color="#7B1FA2",
        va="top",
    )

    text_ax.text(
        0.18,
        0.025,
        " the value of GenAI before\n"
        "we can work with them to capture it.",
        fontsize=12,
        color=TEXT_COLOR,
        va="top",
        linespacing=1.35,
    )

    # ------------------------------------------------------------------
    # CIRCUMPLEX
    # ------------------------------------------------------------------

    R = CIRCUMPLEX_RADIUS

    # Main circle
    ax.add_patch(
        Circle(
            (0, 0),
            R,
            facecolor="white",
            edgecolor="#333333",
            linewidth=1.2,
            zorder=1,
        )
    )

    # Purple opportunity quadrant
    #
    # This is the upper-right quadrant in the reference image.
    from matplotlib.patches import Wedge

    ax.add_patch(
        Wedge(
            center=(0, 0),
            r=R,
            theta1=0,
            theta2=90,
            facecolor="#B779D1",
            alpha=0.75,
            edgecolor="none",
            zorder=0,
        )
    )

    # Axis lines
    ax.plot(
        [-R, R],
        [0, 0],
        color="#444444",
        linewidth=0.8,
        zorder=2,
    )

    ax.plot(
        [0, 0],
        [-R, R],
        color="#444444",
        linewidth=0.8,
        zorder=2,
    )

    # ------------------------------------------------------------------
    # AXIS LABELS
    # ------------------------------------------------------------------

    ax.text(
        0,
        R * 1.07,
        "HIGH POSITIVE AFFECT",
        ha="center",
        va="bottom",
        fontsize=8,
        fontweight="bold",
    )

    ax.text(
        0,
        -R * 1.07,
        "LOW POSITIVE AFFECT",
        ha="center",
        va="top",
        fontsize=8,
        fontweight="bold",
    )

    ax.text(
        -R * 1.06,
        0,
        "LOW NEGATIVE\nAFFECT",
        ha="right",
        va="center",
        fontsize=8,
        fontweight="bold",
    )

    ax.text(
        R * 1.06,
        0,
        "HIGH NEGATIVE\nAFFECT",
        ha="left",
        va="center",
        fontsize=8,
        fontweight="bold",
    )

    # ------------------------------------------------------------------
    # DIAGONAL EMOTIONAL AXES
    # ------------------------------------------------------------------

    diagonal_labels = [
        (45, "STRONG ENGAGEMENT"),
        (135, "PLEASANTNESS"),
        (225, "DISENGAGEMENT"),
        (315, "UNPLEASANTNESS"),
    ]

    for angle_deg, label in diagonal_labels:

        angle_rad = math.radians(angle_deg)

        label_radius = R * 1.13

        x = label_radius * math.cos(angle_rad)
        y = label_radius * math.sin(angle_rad)

        rotation = angle_deg - 90

        if rotation > 90:
            rotation -= 180

        if rotation < -90:
            rotation += 180

        ax.text(
            x,
            y,
            label,
            ha="center",
            va="center",
            fontsize=7.5,
            fontweight="bold",
            color="#777777",
            rotation=rotation,
            rotation_mode="anchor",
        )

    # ------------------------------------------------------------------
    # EMOTIONAL DESCRIPTORS
    # ------------------------------------------------------------------

    descriptor_groups = [
        (
            135,
            [
                "content",
                "happy",
                "kindly",
                "pleased",
                "satisfied",
                "warmhearted",
            ],
        ),
        (
            45,
            [
                "active",
                "elated",
                "enthusiastic",
                "excited",
                "peppy",
                "strong",
            ],
        ),
        (
            -45,
            [
                "blue",
                "grouchy",
                "lonely",
                "sad",
                "sorry",
                "unhappy",
            ],
        ),
        (
            -135,
            [
                "drowsy",
                "dull",
                "sleepy",
                "sluggish",
            ],
        ),
        (
            180,
            [
                "at rest",
                "calm",
                "placid",
                "relaxed",
            ],
        ),
        (
            0,
            [
                "distressed",
                "fearful",
                "hostile",
                "jittery",
                "nervous",
                "scornful",
            ],
        ),
        (
            -160,
            [
                "quiescent",
                "quiet",
                "still",
            ],
        ),
        (
            30,
            [
                "aroused",
                "astonished",
                "surprised",
            ],
        ),
    ]

    for angle_deg, words in descriptor_groups:

        angle_rad = math.radians(angle_deg)

        descriptor_radius = R * 0.70

        x = descriptor_radius * math.cos(angle_rad)
        y = descriptor_radius * math.sin(angle_rad)

        ax.text(
            x,
            y,
            "\n".join(words),
            ha="center",
            va="center",
            fontsize=6.5,
            color="#888888",
            linespacing=1.2,
            zorder=3,
        )

    # ------------------------------------------------------------------
    # ORGANIZATION / RESPONDENT MARKERS
    # ------------------------------------------------------------------

    organizations = _build_organization_sentiment_points(profiles)

    for organization in organizations:

        x = organization["x"]
        y = organization["y"]

        organization_type = organization.get(
            "type",
            "for_profit",
        )

        if organization_type == "not_for_profit":
            outline_color = NOT_FOR_PROFIT_COLOR
        else:
            outline_color = FOR_PROFIT_COLOR

        # Marker background
        ax.add_patch(
            Circle(
                (x, y),
                0.115,
                facecolor="white",
                edgecolor=outline_color,
                linewidth=3.0,
                zorder=10,
            )
        )

        # Logo/icon if available
        logo = organization.get("logo")

        if logo is not None:

            try:

                from matplotlib.offsetbox import AnnotationBbox, OffsetImage

                image = OffsetImage(
                    logo,
                    zoom=0.11,
                )

                annotation = AnnotationBbox(
                    image,
                    (x, y),
                    frameon=False,
                    zorder=11,
                )

                ax.add_artist(annotation)

            except Exception:

                ax.text(
                    x,
                    y,
                    organization["name"][:3].upper(),
                    ha="center",
                    va="center",
                    fontsize=7,
                    fontweight="bold",
                    zorder=11,
                )

        else:

            ax.text(
                x,
                y,
                organization["name"][:3].upper(),
                ha="center",
                va="center",
                fontsize=7,
                fontweight="bold",
                zorder=11,
            )

    # ------------------------------------------------------------------
    # LEGEND
    # ------------------------------------------------------------------

    ax.add_patch(
        Circle(
            (-0.95, -1.08),
            0.025,
            facecolor="white",
            edgecolor=FOR_PROFIT_COLOR,
            linewidth=2,
        )
    )

    ax.text(
        -0.90,
        -1.08,
        "For Profit",
        va="center",
        fontsize=7,
    )

    ax.add_patch(
        Circle(
            (-0.95, -1.17),
            0.025,
            facecolor="white",
            edgecolor=NOT_FOR_PROFIT_COLOR,
            linewidth=2,
        )
    )

    ax.text(
        -0.90,
        -1.17,
        "Not for Profit",
        va="center",
        fontsize=7,
    )

    # ------------------------------------------------------------------
    # TITLE
    # ------------------------------------------------------------------

    fig.text(
        0.72,
        0.965,
        "AI Sentiment",
        ha="center",
        va="top",
        fontsize=16,
        fontweight="bold",
    )

    fig.text(
        0.72,
        0.935,
        "Watson & Tellegen's Circumplex model",
        ha="center",
        va="top",
        fontsize=7,
        fontstyle="italic",
        color="#999999",
    )

    # ------------------------------------------------------------------
    # SAVE
    # ------------------------------------------------------------------

    fig.savefig(
        path,
        dpi=180,
        bbox_inches="tight",
        pad_inches=0.2,
    )

    plt.close(fig)

    return True
```

---

# 4. Add the Organization Aggregation Helper

Your current code does not appear to have an organization-level aggregation function.

Add this helper:

```python
def _build_organization_sentiment_points(
    profiles: list[RespondentProfile],
) -> list[dict]:
    """
    Converts respondent profiles into organization-level sentiment points.

    The resulting coordinates are normalized to approximately [-1, 1].

    x-axis:
        negative affect

    y-axis:
        positive affect
    """

    organizations = {}

    for profile in profiles:

        organization_name = getattr(
            profile,
            "organization_name",
            None,
        )

        if not organization_name:
            continue

        organization_type = getattr(
            profile,
            "organization_type",
            "for_profit",
        )

        positive_scores = []
        negative_scores = []

        for record in profile.evidence_records:

            if record.direction == "positive":
                positive_scores.append(1.0)

            elif record.direction == "negative":
                negative_scores.append(1.0)

        if not positive_scores and not negative_scores:
            continue

        if organization_name not in organizations:

            organizations[organization_name] = {
                "positive": [],
                "negative": [],
                "type": organization_type,
            }

        organizations[organization_name]["positive"].extend(
            positive_scores
        )

        organizations[organization_name]["negative"].extend(
            negative_scores
        )

    results = []

    for organization_name, values in organizations.items():

        positive_count = len(values["positive"])
        negative_count = len(values["negative"])

        total = positive_count + negative_count

        if total == 0:
            continue

        positive_rate = positive_count / total
        negative_rate = negative_count / total

        # Map from [0, 1] to [-1, 1]
        y = (positive_rate * 2.0) - 1.0
        x = (negative_rate * 2.0) - 1.0

        # Keep points inside the circular boundary.
        distance = math.sqrt(x * x + y * y)

        if distance > 0.88:

            scale = 0.88 / distance

            x *= scale
            y *= scale

        results.append(
            {
                "name": organization_name,
                "x": x,
                "y": y,
                "type": values["type"],
            }
        )

    return results
```

---

# 5. Important: Axis Logic

The current implementation does:

```python
horizontal = negative_rate
vertical = positive_rate
```

That is conceptually valid for a two-dimensional affect model.

However, the important thing is that the two dimensions remain independent.

The target diagram should conceptually use:

```python
x = negative_affect
y = positive_affect
```

Do not collapse the data into a single sentiment score such as:

```python
sentiment = positive - negative
```

That would reduce the two-dimensional emotional space into a single line.

Instead:

```python
positive_affect = independent_measure
negative_affect = independent_measure
```

This allows positions such as:

```text
positive = high
negative = high
```

which represents a highly active or contested emotional state.

It also allows:

```text
positive = low
negative = low
```

which represents a relatively disengaged or emotionally neutral state.

---

# 6. Recommended Naming Change

The current function is named:

```python
write_theme_circumplex()
```

But the target visualization is not actually a theme circumplex.

I recommend renaming the new visualization to:

```python
write_ai_sentiment_circumplex()
```

Then preserve the existing visualization separately:

```python
write_theme_circumplex()
```

This gives you two distinct charts:

---

## Theme Sentiment Circumplex

```text
write_theme_circumplex()
```

Shows:

- Awareness
- Understanding
- Trust
- Relevance
- Ease of Engagement
- Advocacy

This is essentially the first visualization.

---

## AI Sentiment Circumplex

```text
write_ai_sentiment_circumplex()
```

Shows:

- Organization A
- Organization B
- Organization C
- Organization D
- etc.

This is the second visualization.

---

# 7. Most Important Conceptual Change

Your current implementation is well-suited to the first image.

However, the second image requires changing the plotted unit from:

```text
Themes
```

to:

```text
Organizations / Respondents / Partners
```

The overall architecture should therefore look like:

```text
Respondent Profiles
        │
        ├── Theme Evidence
        │       │
        │       └── Theme Sentiment Circumplex
        │
        └── Organization-Level Sentiment
                │
                └── AI Sentiment Circumplex
```

This separation will make the code easier to reason about and prevent the theme-level chart and organization-level chart from becoming coupled.

---

# 8. Additional Implementation Notes

## Organization names

The aggregation helper expects something like:

```python
profile.organization_name
```

If your actual `RespondentProfile` model uses another field, replace:

```python
organization_name = getattr(
    profile,
    "organization_name",
    None,
)
```

with the actual field.

For example:

```python
organization_name = profile.company_name
```

or:

```python
organization_name = profile.partner_name
```

---

## Organization type

The aggregation helper expects:

```python
profile.organization_type
```

with values such as:

```python
"for_profit"
```

or:

```python
"not_for_profit"
```

If your project uses different values, normalize them before plotting.

For example:

```python
if organization_type in {"nonprofit", "non_profit", "not_for_profit"}:
    organization_type = "not_for_profit"
else:
    organization_type = "for_profit"
```

---

## Logos

The target diagram uses recognizable logos inside each circular marker.

The implementation supports:

```python
organization["logo"]
```

If no logo is available, the fallback is:

```python
organization["name"][:3].upper()
```

For example:

```text
ABC
XYZ
SFU
```

A stronger implementation would load logos from local files:

```python
organization = {
    "name": "Example Organization",
    "x": 0.35,
    "y": 0.65,
    "type": "for_profit",
    "logo": plt.imread("assets/logos/example.png"),
}
```

---

# Final Recommendation

Do not try to force the existing theme chart to become the second chart.

Instead:

1. Keep the existing theme chart as a separate visualization.
2. Create a new `write_ai_sentiment_circumplex()` function.
3. Aggregate profiles by organization.
4. Calculate independent positive and negative affect scores.
5. Plot organizations as small logo markers.
6. Color the marker outline by organization type.
7. Add the explanatory narrative panel on the left.
8. Highlight the high-positive/high-negative quadrant as the GenAI opportunity area.

The key conceptual difference is:

```text
Current chart:
Theme → Position

Target chart:
Organization / Partner → Position
```

That is the main change needed to reproduce the second reference image accurately.
