# JABC NLP-Based Sentiment & Brand Health Matrix System

A local, deterministic, rule-based NLP pipeline that reads JABC educator /
stakeholder interview workbooks (`.xlsx`), scores each respondent across
six Brand Health Themes, classifies each respondent into one of four Brand
Personas, and exports a **Brand Health Matrix** plus a full evidence audit
trail. No external LLM API calls are made — everything runs locally.

## What it does

```
Raw Interview Workbooks (.xlsx)
    -> Sheet classification (completed response sheet vs. reference sheet)
    -> Respondent identity resolution
    -> Question/answer extraction
    -> Structured evidence extraction (phrases, keywords, ratings, sentiment, behavior)
    -> Deterministic theme scoring (Awareness, Understanding, Trust,
       Relevance, Ease of Engagement, Advocacy)
    -> Behavioral / engagement state detection
    -> Brand Persona classification (Champion / Non-Active Supporter /
       Prospect / Newbie), reported as two merged personas
       (Established Supporters / Potential Adopters)
    -> Confidence & uncertainty scoring
    -> Brand Health Matrix + evidence exports
```

Every number in the output can be traced back to the specific interview
answer(s) that produced it via `respondent_theme_evidence.csv`.

## Installation

```bash
cd jabc_brand_health_analyzer
pip install pandas openpyxl pyyaml vaderSentiment matplotlib
```

(`matplotlib` is only needed if you use `--generate_heatmap true`.)

## Usage

```bash
python3 jabc_brand_health_analyzer.py \
    --input_dir /Users/asheeshyadav/Desktop/Accenture/Excel-Docs \
    --output_dir ./outputs \
    --generate_heatmap true
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--input_dir` | *(required)* | Directory of `.xlsx` interview files |
| `--output_dir` | *(required)* | Where outputs are written |
| `--config_dir` | `./config` | YAML configuration directory |
| `--generate_heatmap` | `false` | Also write `brand_health_matrix_heatmap.png` |
| `--include_reference_sheets` | `false` | Score reference-only sheets too (not recommended) |
| `--manual_review_threshold` | from config | Override the persona classification margin threshold |
| `--calibration_csv` | *(none)* | Run the calibration workflow against a human-reviewed CSV |

### Try it on the included synthetic sample data

```bash
python sample_data/generate_sample_data.py   # regenerate if needed
python jabc_brand_health_analyzer.py --input_dir ./sample_data --output_dir ./outputs --generate_heatmap true
```

## Outputs

| File | Contents |
|---|---|
| `brand_health_matrix.csv` / `.xlsx` | **Primary output.** Average theme scores per Brand Persona, with conditional formatting (green ≥4.0, yellow 2.5-3.9, red <2.5) in the `.xlsx` version. Both reported personas always appear, even with zero respondents. |
| `respondent_brand_health_scores.csv` / `.xlsx` | One row per respondent: theme scores, evidence status, behavioral flags, both the reported and the classification persona, confidence, manual-review flag/reason. |
| `respondent_theme_evidence.csv` / `.xlsx` | One row per piece of evidence extracted (phrase/keyword match, explicit rating, etc.) — the audit trail behind every score. |
| `persona_validation.csv` | Diagnostic-only comparison of the predicted persona against the original interview-sheet label (never fed back into scoring). |
| `brand_health_matrix_heatmap.png` | Optional visual heatmap of the matrix. |
| `calibration_report.csv` / `.xlsx` | Only produced with `--calibration_csv`; compares automated scores/personas to a human reviewer's. |

## How scoring works

Each of the six Brand Health Themes is scored 1-5 as a weighted average of
up to five components — **components with no supporting evidence are
dropped from both the numerator and denominator**, so missing evidence
never silently drags a score down (see `jabc/scoring.py`):

- **40%** Contextual Evidence (answers to questions mapped to this theme)
- **25%** Phrase-Rule Evidence (negation- and intensifier-aware phrase matches)
- **15%** Explicit Rating (numeric ratings normalized to 1-5)
- **10%** Sentiment Support (VADER; only from answers genuinely relevant to the theme)
- **10%** Behavioral/Engagement Evidence (only when that behavior was actually discussed)

### Persona classification is gate-first

The four personas are **relationship states, not score bands**, so
`jabc/persona.py` decides them in two stages:

1. **Engagement gate** — `jabc/engagement.py` establishes three structured
   facts from the raw answers: does this educator have JABC history, is that
   history live or lapsed, and (if there is no JABC history) do they actively
   and happily run *other* external programs. Each persona in
   `persona_rules.yaml` declares the flag combination that defines it, and the
   first satisfied gate wins.
2. **Theme-score fit** — how well the respondent sits inside that persona's
   typical ranges. This sets the classification margin, feeds confidence, and
   is the sole basis for the decision only when an interview carries no usable
   engagement evidence at all.

Average theme score alone is never used to assign a persona. The ordering
matters because scores and personas genuinely disagree in real interviews: a
Champion who is vocal about JABC's portal friction still scores low on
`ease_of_engagement`, and a Non-Active Supporter who remembers JABC fondly
still scores high on `trust`.

### Classification is four-way; reporting is two-way

Everything above stays a four-way decision, because the gates test four
distinct relationship states. Every **reported** view — the Brand Health
Matrix, the heatmap, the smiley grid, the factor pies — merges them into
two personas, declared in `persona_rules.yaml` under `persona_groups`:

| Reported persona | Includes | Definition |
| --- | --- | --- |
| **Established Supporters** | Brand Champion + Non-Active Supporter | Educators who have previously engaged with JABC and have firsthand experience with its programs. They recognize the value of JABC and hold positive perceptions of the brand. While some remain active advocates and others have become inactive due to competing priorities or changing responsibilities, they represent a strong foundation for continued engagement and advocacy. |
| **Potential Adopters** | Brand Prospect + Brand Newbie | Educators who have limited or no direct experience with JABC. They range from those who are aware of the brand but have not yet participated to those with little or no awareness. They are open to external classroom programming but require greater awareness, understanding, and a compelling value proposition before engaging with JABC. |

A merged average is taken over the group's respondents directly, never as the
mean of its two member personas' means — averaging means would weight a
one-respondent Champion row equally with a five-respondent Non-Active Supporter
row. The reporting outputs — `persona_roster.csv`, `persona_validation.csv`, the
Brand Health Matrix — name only the two Brand Personas. The gate a respondent
passed through is an internal step of the classification and survives in one
place only: `respondent_brand_health_scores.csv` carries both
`reported_brand_persona` and `brand_persona`, so the margin, gate flags, and
reasoning on each row stay explainable. The config load rejects a persona that belongs to no group, since
its respondents would otherwise disappear from the matrix while still counting
as classified.

The engagement detector reads **raw answers rather than evidence records**,
because two of its strongest signals do not survive being shredded per-theme:

- **Interview structure.** The guide branches by persona, so a substantively
  answered Section F ("lapsed engagement") is direct evidence of lapse. Two
  guards keep this honest: only the *retrospective anchor* questions in
  Section E can establish JABC history (interviewers also used its follow-ups
  prospectively — "just apply online" is a wish, not a memory), and a direct
  denial of prior familiarity on Q3 overrides any inferred history.
- **Whether an answer names JABC.** "Last year we did a leadership program" is
  evidence about an outside provider, not about JABC, so recency and lapse
  cues are only counted inside JABC-scoped answers.

Every flag is exported with the answer excerpts that set it
(`engagement_evidence` in `respondent_brand_health_scores.csv`), so a
classification can be checked without rerunning anything.

**Two confidence numbers** are reported, deliberately kept apart.
`confidence` measures the evidence behind the whole profile; the persona-only
`classification_confidence` (engagement gate + margin + spread) is what drives
`manual_review_flag`. A Brand Newbie interview is thin by definition — there
is little to say about a program you have never run — so its overall
confidence is low while its persona is unambiguous. Routing review off the
overall number flagged every respondent, which says exactly as much as
flagging none of them.

## Factor Circumplex

`--generate_circumplex true` writes `factor_circumplex.png`: the top five
motivators and top five barriers, each circle wrapped in a family ring — blue
for motivators, orange for barriers — with a `factor_circumplex_positions.csv`
sidecar.

Two of the plotted barriers — *Difficulty integrating programs into curriculum*
and *Low awareness of JABC programs* — had no position on the approved diagram.
Both read as fundamental rather than add-on, so both sit left of centre; their
exact `x` was then pushed further left than a first pass had them, because with
`y` fixed by frequency and no nudging allowed at draw time, `x` is the only
axis available to stop three left-hand discs from covering each other's rings.
`tests/test_jabc_pipeline.py::test_circumplex_circles_do_not_overlap` holds that
invariant. *Limited instructional time and scheduling* merges the separately
coded scheduling factor; its frequency stays 11 rather than 11 + 7, since the
coded counts are per-mention and summing them would double-count anyone who
raised both. Coded factors that are no longer plotted (presenter/delivery
quality risk, flexibility, free access) stay in the config — they are still
part of the analysis and the evidence workbook.

**The two axes come from different places, and that is the point.**

| | Source | Meaning |
|---|---|---|
| Horizontal | **Authored** — transcribed from the approved diagram | "Fundamental factor for consideration" ↔ "Add-ons" |
| Vertical | **Measured** — coded frequency of mention | High positive effect (motivators, up) ↔ high negative effect (barriers, down) |

Each item's `x` lives in `circumplex_layout` in
`config/motivators_barriers.yaml` and is never recomputed. Nothing in this
pipeline measures how *decisive* a factor is, so deriving that position from a
number would quietly overwrite a human judgement with something that does not
mean the same thing. Circle size also tracks frequency, reinforcing the
vertical reading rather than adding a third variable.

Topics render as hand-drawn icons with a key below the plot — ten labels will
not fit legibly inside ten circles, and matplotlib's Agg backend cannot render
colour emoji (they come out as blank "tofu" boxes), so the glyphs are built
from primitive shapes.

**Nothing on the circumplex itself is derived from interview text.** The ring
used to be a persona-share donut, but a two-slice donut at ring size — on ten
circles, several of them overlapping — could be seen and not read: no slice was
labelled and no percentage was recoverable. The ring is now a plain family band
and the persona split moved to the deck, one full-size labelled pie per factor.

The split itself is unchanged: cue lexicons attribute mentions to personas, and
the slices are the two reported personas (the sidecar CSV keeps a share column
per classification persona, so a slice can be read back to its halves). A weak
lexicon makes an attribution less certain — reported as `detected_mentions` and
flagged on the pie below `min_mentions_for_ring` — but cannot move a circle or
contradict the coded frequencies. Where no cue fired at all, `analyze_drivers`
substitutes an even split to mean "unknown"; the pie slides detect that case and
draw an empty circle instead, since a printed 50% / 50% would be
indistinguishable from a measured one.

Two notes on reading it:

- **Four coded items are not plotted** — Flexibility (M5, 7), Free access
  (M7, 5), Unclear fit (B2, 9) and Low awareness (B6, 7). They do not appear in
  the approved diagram. Add them to `circumplex_layout.items` with an `x` to
  bring them in.
- **B3 and B4 overlap**, unavoidably: they tie on frequency (8) so they share a
  vertical position, and the diagram places them close horizontally. Since both
  axes are fixed, the circles cannot be nudged apart, so all fills are drawn
  before any ring — every ring stays fully visible however much the discs
  overlap.

### Editable slide deck

`--generate_deck true` writes `jabc_charts.pptx`: five slides holding every
chart **redrawn as native PowerPoint shapes**, not embedded images — the matrix
grid and its smiley faces, the circumplex with its icons and family rings, a
"who raised each factor" slide of labelled pies for the motivators and another
for the barriers, and the opportunity quadrant. Every circle, wedge, icon stroke and label is a shape
or text box you can move, restyle, retype or delete.

The PNGs remain the reference rendering; `pptx_export.py` is a second renderer
over the same functions (`build_brand_health_matrix`, `resolve_layout`,
`load_opportunities`), so the deck cannot disagree with the images. It needs
`python-pptx`; without it the deck is skipped the way the PNGs are skipped
without matplotlib.

Two implementation notes worth knowing before editing the module:

- **No `ARC` / `PIE` / `BLOCK_ARC` preset shapes.** They carry their sweep in
  adjustment values that renderers disagree about — macOS QuickLook draws
  nothing at all for a default `PIE` — which would silently drop every persona
  ring and smiley mouth. Curves are emitted as freeform point lists instead,
  which every renderer draws and PowerPoint still lets you edit point-by-point.
- **The vertical axis captions use text-box rotation.** PowerPoint honours it;
  some quick-preview tools show them unrotated.

### Evidence workbooks

`--generate_reports true` writes two independent three-column workbooks, one
per chart:

| File | Column 1 | Column 2 | Column 3 |
|---|---|---|---|
| `circumplex_evidence_report.xlsx` | Motivator / barrier | Coded frequency | Interviews, **derived** by cue matching |
| `opportunity_evidence_report.xlsx` | Opportunity | Coded mentions | Interviews, from the **coded roster** |

The two never read each other's data. The frequency column is the coded number
in both. The names column differs in kind: the opportunity roster is part of the
coding, so it is exact and its count matches; the motivator/barrier config
carries no per-person attribution, so those names are detected here by cue
matching and **will not always agree with the coded frequency** (B4 is coded 8
but only two transcripts trip its cues — a thin lexicon, not a smaller finding).

## Opportunity prioritization

`--generate_priority_matrix true` writes `opportunity_priority_matrix.png`:
the seven coded opportunity themes on a Value x Difficulty quadrant, plus an
`opportunity_validation.csv` sidecar.

| | Source | Meaning |
|---|---|---|
| Relative Value (x) | **Measured** | Coded mentions — how many educators independently raised it |
| Relative Difficulty (y) | **Authored** | How hard the change is for JABC, declared per theme |
| Bubble size | **Measured** | Number of people who raised it |

Only four distinct mention counts exist (6, 7, 8, 10), so tied themes share a
horizontal position and stack vertically by difficulty. The x-axis caption
therefore names what the horizontal position counts, and bubble collisions are
separated sideways (`Y_PUSH_DAMP`) rather than up and down — otherwise the
vertical spread of a tied stack reads as if frequency were the vertical axis.

Difficulty is not a property of a transcript — it depends on JABC's roadmap,
budget and partnerships — so it is declared in `config/opportunities.yaml`
against the anchors in `difficulty_scale`, with a one-line rationale per theme,
rather than derived from a number that would only look objective. **That field
is the one to argue about**; everything else on the chart is the coded data.

In the current coding each person is counted once per theme, so `mentions` and
`people` are the same number and bubble size reinforces horizontal position
rather than adding a third variable. `people` is kept as its own field because
that stops being true the moment a theme is coded per answer.

### Validating the rosters

`jabc/opportunities.py` re-checks on every run that each `mentions` count still
matches the length of its `mentioned_by` roster, that every named respondent
still exists in the interview folder, and which respondents appear in no theme
at all. Those are the facts that rot silently as files are added or re-coded.

It deliberately does **not** try to re-derive the coding. A keyword pass was
tried and proved much weaker than a human read: it flagged five attributions as
unsupported — Sarah Williams on awareness, Alvina Last on expert delivery,
Amanda Reid on low-prep, Kimberly Hlina and Soraya Rajan on communication
timing — and every one turned out correct on inspection. It had simply missed
"professional developmet day" (a typo), "the person coming into the classroom",
"take care of everything", "when big shifts were going to happen" and "prefer
to hear from JABC earlier in the school year". Treat any such flag as "go read
this answer", never as evidence the coding is wrong.

## Reading the score faces

Theme scores render as a six-band face scale, shared by the `.xlsx` export and
the heatmap so the two always agree. Worst to best:

| Band | Range | Colour | Face |
|---|---|---|---|
| Poor | below 2.0 | red | deep frown + sad brows |
| Weak | 2.0 – 2.6 | orange | frown |
| Neutral | 2.6 – 3.2 | yellow | flat bar |
| Fair | 3.2 – 3.6 | olive | slight smile |
| Good | 3.6 – 4.0 | green | smile |
| Strong | 4.0 and up | dark green | open grin + arced eyes |

The band count balances two opposite failures, both of which this scale has
actually hit. **Too many** and neighbours become indistinguishable — an earlier
eight-tier version graded hue and curvature in small steps and produced two
yellows differing only in how far the mouth turned up. **Too few** and the
bands stop discriminating — a five-tier version put 2.5–3.5 in one "Neutral"
band that swallowed roughly two thirds of a real matrix, because scored themes
cluster hard around the midpoint.

Six works because the cuts sit where the data actually falls (a narrower
2.6–3.2 middle, splitting the old neutral block) while every band still draws
from a *different hue family* — red / orange / yellow / olive / green / dark
green, with only one yellow. Expression is a second independent cue, so the
ranking survives greyscale printing and colour-blind readers.

**Caution on the two middle bands.** Theme scores here carry low evidence
coverage, so a 0.4-wide band is near the limit of what the underlying numbers
support. Treat a one-band difference as suggestive and check `evidence_status`
before acting on it.

The key ships as its own image, `brand_health_score_scale.png`, written
alongside the heatmap whenever `--generate_heatmap true` is passed. It is a
fixed reference that never changes with the data, so it gets placed once rather
than redrawn under every chart — and it keeps the matrix image a clean grid
that drops into a slide at any size. Both are drawn by the same
`_draw_score_face` helper, so the key cannot fall out of step with the chart it
explains.

## Not-applicable matrix cells

Ease of Engagement and Advocacy are left **blank** for Potential Adopters
(Brand Prospect + Brand Newbie) in every matrix output (CSV, `.xlsx`, heatmap).

Those two personas have no JABC participation history by definition, so they
were never routed through Section E (JABC experience) or asked Q9.3 (would you
recommend it). Any score they carried for those themes came from the "unknown
defaults to neutral 3.0" rule plus incidental keyword matches on answers about
*other* providers — it measured the absence of evidence, not their view of
JABC. Printing it beside a Champion's score, which comes from someone who
actually registered for a program and decided whether to recommend it, invites
a comparison the data cannot support.

Blanked cells are excluded from that persona's **Average Score** and from the
column's cross-persona average, so no suppressed number leaks back in through
an aggregate. They render as genuinely empty on a white fill — distinct from
the en dash used for "no respondents in this cell", which means measurement was
attempted and returned nothing.

The default lives in `jabc/matrix.py` (`NOT_APPLICABLE_THEMES`) so it applies
even if a caller forgets to thread config through, and is overridable per
persona with `not_applicable_themes` in `persona_rules.yaml`. It is declared
per classification persona and lifted to the reported groups by
`group_not_applicable_themes()`, which blanks a merged cell only when the theme
is not applicable to *every* member — if one member was genuinely asked the
question, the merged average carries real evidence and is published.

## Configuration

Everything content-specific lives in `config/*.yaml`, not in code:

- `theme_keywords.yaml` — positive/negative keyword dictionaries per theme
- `phrase_rules.yaml` — multi-word phrase rules, negation words, intensifiers
- `question_theme_mapping.yaml` — which questions/sections imply which themes
- `persona_rules.yaml` — engagement gates, definitions, and typical score ranges per persona
- `engagement_rules.yaml` — interview-section geometry, anchor questions, and the
  cue lexicons behind JABC recency/lapse and external-programming disposition
- `motivators_barriers.yaml` — the coded motivator/barrier tables plus the cues
  used to place them on the circumplex
- `scoring_weights.yaml` — the formula weights described above
- `sentiment_weights.yaml` — how much sentiment may influence each theme

**Tune these during a calibration pilot** (see below) rather than editing
the Python code — the defaults are a reasonable starting point, not a
final calibration. The values most likely to need adjustment once you see real
interview text are `engagement_rules.yaml`'s cue lexicons and its
`external_disposition_threshold` (the Prospect-vs-Newbie split), followed by
`persona_rules.yaml`'s `typical_range` bands. Gate flag names are validated at
config load, so a typo raises rather than silently making a persona
unreachable.

## Calibration workflow

To validate the automated scores against a human reviewer's judgment,
prepare a CSV with columns `respondent_id, theme, human_score,
human_persona` (one row per respondent/theme; `human_persona` repeats
across a respondent's rows) and run:

```bash
python jabc_brand_health_analyzer.py --input_dir ./interviews --output_dir ./outputs --calibration_csv ./human_review.csv
```

This produces `calibration_report.csv` with per-row differences plus a
console summary (mean absolute error, theme match rate, persona match
rate). Calibration data is kept entirely separate from the production
outputs.

## Design notes & known limitations

- **Respondent identity**: resolved via (1) explicit ID/name found in the
  workbook, (2) filename, in that priority order. Low-confidence
  resolutions are flagged `manual_review_flag = True`.
- **Multiple completed sheets in one workbook** are treated as separate
  respondents at reduced confidence (we cannot safely assume they're the
  same person) and flagged for manual review.
- **"Unknown" is never treated as "negative."** A theme or behavioral flag
  with no supporting evidence defaults to neutral (3.0) / `False`
  respectively, and is excluded from the weighted-average formula rather
  than pulling the score down. `test_missing_evidence_defaults_to_neutral_not_negative`
  in `tests/` locks this in.
- **Word-boundary matching** is used throughout (e.g. "familiar" won't
  match inside "unfamiliar"; "never" won't match inside "whenever") — see
  `tests/test_jabc_pipeline.py` for regression coverage of both.
- **Question-rule matching prefers the most specific match** found in the
  question text over the section/category text, so a generic category
  name (e.g. "Communication & Future Opportunities") can't shadow a more
  specific question-level rule (e.g. "would you recommend").
- The `EXPECTED_RELEVANT_QUESTIONS_PER_THEME` constant in `scoring.py` (used
  to normalize evidence coverage into 0-1) is a heuristic tuned for the
  reference JABC interview guide's typical length; adjust it if your
  interview guide asks meaningfully more or fewer questions per theme.

## Running tests

```bash
pip install pytest
pytest tests/ -v
```

28 tests cover phrase/negation/intensifier matching, explicit rating
parsing, sheet classification, identity resolution, scoring bounds and
"unknown ≠ negative" behavior, persona classification, and an end-to-end
run against the bundled synthetic sample data.

## Project layout

```
jabc_brand_health_analyzer.py   # CLI entrypoint
jabc/
  config_loader.py              # loads + validates YAML config
  excel_loader.py                # reads .xlsx workbooks
  sheet_classifier.py            # completed-response vs. reference sheets
  identity.py                    # respondent ID resolution
  extractor.py                   # raw question/answer extraction
  models.py                      # RawAnswer / EvidenceRecord / ThemeScoreResult / RespondentProfile
  text_utils.py                  # phrase/keyword/negation/intensifier matching
  sentiment.py                   # VADER wrapper
  evidence.py                    # structured evidence extraction
  behavioral.py                  # keyword-derived behavioral flags
  engagement.py                  # JABC relationship state + external-program disposition
  drivers.py                     # motivator/barrier detection for the circumplex
  scoring.py                     # deterministic theme scoring formula
  persona.py                     # engagement-gated persona classification
  confidence.py                  # confidence/uncertainty model
  matrix.py                      # Brand Health Matrix aggregation
  export.py                      # CSV/Excel writers, conditional formatting, heatmap
  calibration.py                 # human-review calibration workflow
  pipeline.py                    # orchestrates all of the above
config/                          # all tunable YAML configuration
sample_data/                     # synthetic demo workbooks + generator script
tests/                           # pytest suite
```
