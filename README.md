# NCS Field Intelligence · SODIR Field Explorer

Streamlit app for Norwegian continental shelf fields: production, reserves, wells, reservoir facts
extracted from SODIR description texts, an indicative pressure/temperature layer, and a peer
**benchmark workspace** (normalised profiles, reserve intensity, recovery factors, producers vs
injectors, GOR / water cut, profile import and average-profile generation).

Consulting-style design: deep-navy / electric-blue palette, serif action titles, thin rules, a source
line under every exhibit, and one warm accent reserved for the item in focus (selected field or imported profile).

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
python -m pytest -q          # 36 offline tests (extraction, benchmark maths, figures, dashboard flows)
```

## Sections

| Section | What it shows |
|---|---|
| Overview | Cumulative production KPIs; **field facts** panel (drainage strategy, producing formations, groups, age, lithology, depth, water depth, HPHT, P/T, concept, discovery/PDO/start years, producer and injector counts, in-place and recoverable volumes, recovery factors, reserve intensity); description texts |
| Production | Monthly oil/NGL/water-cut and gas/condensate rates; annual production by product with estimated producing-well count; water cut and GOR history |
| Wells & reservoir | Development wells by purpose and status, drilling timeline, well list (CSV), formation tops of the field's wells filtered to the extracted producing formations |
| Reserves | Produced vs remaining vs recoverable gauges; reserve revisions over time |
| Investments | Annual investments |
| Map | SODIR WMS layers with field boundary, or the official FactMaps viewer |
| Benchmark | Peer-set analysis (below) |
| Data & QA | Attribute coverage across fields, extraction audit for the selected field with source text, method notes |

## Data sources (all SODIR FactPages CSV exports, cached one hour)

`field`, `field_production_monthly`, `field_production_yearly`, `field_reserves`, `field_in_place_volumes`,
`field_description`, `field_investment_yearly`, `wellbore_development_all` (purpose, status, content,
completion and plugging dates, depths), `wellbore_formation_top` (loaded on demand).

## Text extraction (`utils/extract.py`)

Rule-based, conservative (empty when nothing matches). From the five description sections per field:

* **Drainage strategy** — mechanisms found in *Recovery strategy* / *Status* (pressure depletion, water
  injection, gas injection, WAG, natural water drive, gas cap, compaction, gas lift, pumps, EOR, PWRI).
  The *primary* strategy is taken from the sentence that states how the field *is produced*
  ("based primarily on pressure depletion … produced water was reinjected" → depletion), otherwise
  by precedence WAG > water & gas > water > gas > water drive > depletion.
* **Producing formations / groups / ages / lithology** — proper names preceding *Formation(s)* / *Group*
  (group names do not leak into formations), chronostratigraphic terms, rock types; `intra-Draupne` handled.
* **Reservoir depth** (min–max, water-depth sentences excluded), **water depth**, **HPHT** flag.
* **Discovery, PDO and production-start years**, number of development phases, development concept tags
  (FPSO, subsea tie-back/template, fixed platform, concrete GBS, TLP, semi-sub, unmanned, power from shore).
* **Well counts stated in text** (producers, injectors, slots) — shown separately from the authoritative
  counts in the wellbore table. **Recovery factors stated in text**, reservoir quality, sub-area (Tampen, Utsira High …).

Coverage on the live corpus (142 fields): depth 96 %, formations 82 %, discovery/PDO/start years ≥ 89 %,
drainage strategy 100 % (incl. "Not stated").

## Pressure / temperature (`utils/pt.py`, `data/reservoir_pt.csv`)

SODIR has no P/T table; descriptions only flag HPHT. Values come from, in order:
1. a CSV you upload in **Benchmark → Reservoir P/T** (session only; flexible column names),
2. the built-in **curated table** of initial reservoir pressure/temperature for ~27 fields from public
   literature — *indicative*, each row carries a confidence (high/medium/low) and a source note,
3. numbers stated in the SODIR text,
4. a **hydrostatic (0.101 bar/m) and geothermal (4 °C + 35 °C/km of sediment)** estimate from the text
   depth. HPHT fields never receive a pressure estimate.

The source and confidence are shown next to every value. Verify before any decision use.

## Benchmark workspace

* **Settings**: product (o.e., oil, gas), normalisation (annual volume · per producing well · % of
  recoverable = reserve intensity · % of in place), x-axis (years since start / calendar year), colour by
  (HC type, drainage strategy, area, main group/formation, lithology, age, status, concept, HPHT),
  start-year definition (first year ≥ 0/5/10/25 % of peak, to skip test production).
* **Peer-set filters**: hydrocarbon phase, area, drainage strategy, status, producing formation, group,
  lithology, pressure regime, in-place and recoverable volume ranges, production start year, minimum years on production.
* **Production profiles**: spaghetti per field coloured by category, P10–P90 band, P50 and mean, selected field in accent; envelope and profiles downloadable.
* **Reserve intensity**: recoverable and in-place o.e. per drilled producer, peak offtake (% of recoverable per year), years to peak — box plots by the chosen category.
* **Recovery factor**: RF vs in-place (log) bubble chart, ranking bars, box by category, RFs stated in text.
  Ratios > 100 % (SODIR books condensate as recoverable oil for some gas fields) are excluded and listed.
* **Producers vs injectors**: drilled or active wells on log–log axes with 1:2 and 1:1 reference lines; injector/producer ratio and well counts by category.
* **GOR & water cut**: GOR (Sm³/Sm³), water cut, gas share of o.e., CGR versus years since start, with the peer median.
* **Compare & type curve**: import a CSV/Excel profile (`year` plus any of `oil` [MSm³], `gas` [GSm³],
  `water`, `wells`; template provided) and overlay it on the envelope; generate an **average profile**
  (P50/mean/P10/P90 of the peer set) scaled to your recoverable or in-place volume, optionally rescaled
  so the cumulative equals the stated volume; download as CSV.
* **Reservoir P/T**: pressure vs depth with the hydrostatic line, table with confidence and source, upload/download.
* **Peer table**: the full master table for the filtered peer set (CSV).

### Definitions

* Years since start = calendar year − first production year + 1 (current calendar year excluded as partial).
* Per-well values divide by production wells completed and not yet plugged in that year (wells without a
  plugged date stay counted, so late-life counts are conservative).
* Recovery factor = latest recoverable ÷ in-place volume per product; produced share = cumulative ÷ recoverable.
* Reserve intensity = recoverable o.e. ÷ drilled production wells; peak offtake = peak annual o.e. ÷ recoverable o.e.
* Gas: 1 billion Sm³ = 1 million Sm³ o.e.

## Layout of the code

```
app.py                  Streamlit UI (sections, benchmark workspace)
style.css               consulting-style theme (CSS variables injected by app.py; light / dark)
.streamlit/config.toml  Streamlit theme (electric-blue primary colour)
utils/theme.py          plotly templates, palette, style() with action title + source line
utils/data.py           SODIR loaders (cached), monthly/yearly/wells preparation, latest estimates per field
utils/extract.py        rule-based text extraction
utils/pt.py             pressure/temperature layer
utils/benchmark.py      master table, normalisation, envelopes, ratios, filters, profile import, type curve
utils/figures.py        benchmark exhibits
utils/callbaks_figure.py, utils/maps.py   field charts and map helpers
data/reservoir_pt.csv   curated P/T table (editable)
tests/                  offline tests
```
