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
python -m pytest -q          # offline extraction, calculation and dashboard regressions
```

## Sections

| Section | What it shows |
|---|---|
| Overview | Cumulative production KPIs; **field facts** panel (drainage strategy, producing formations, groups, age, lithology, depth, water depth, HPHT, P/T, concept, discovery/PDO/start years, producer and injector counts, in-place and recoverable volumes, recovery factors, reserve intensity); description texts |
| Production | Monthly oil/NGL/water-cut and gas/condensate rates; annual production by product with estimated producing-well count; water cut and GOR history |
| Wells & reservoir | Development wells by purpose and status, drilling timeline, well list (CSV), formation tops of the field's wells filtered to the extracted producing formations |
| Reserves | Produced vs remaining vs recoverable gauges; reserve revisions over time |
| Investments | Annual investments |
| Economics | Editable scenario prices/FX/OPEX; annual pre-tax cash flow and payback; imported prognosis or illustrative decline with an economic-limit estimate |
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
  HPHT status is **stated HPHT**, **explicitly stated non-HPHT**, or **not stated**. Absence of the
  term is not evidence of normal pressure or non-HPHT conditions.
* **Discovery, PDO and production-start years**, number of development phases, development concept tags
  (FPSO, subsea tie-back/template, fixed platform, concrete GBS, TLP, semi-sub, unmanned, power from shore).
* **Well counts stated in text** (producers, injectors, slots) — shown separately from the authoritative
  counts in the wellbore table. **Recovery factors stated in text**, reservoir quality, sub-area (Tampen, Utsira High …).
* **Development type** distinguishes platform, floating, subsea and combined schemes from development
  text; historical/future phases may coexist, so retain the original description alongside the label.
* **Gas and liquid export routes** retain source clauses from Transport. **Reservoir thickness** and
  **footprint** are extracted only when units and explicit contextual phrases are present. Geographic
  production region/sub-area is separate from reservoir footprint; a field-map boundary is not net pay area.

Descriptions are always visible in two editorial columns, rather than collapsed expanders.
The overview also shows source-linked reservoir/fluid observations from `data/reservoir_parameters.csv`,
starting with Kvitebjørn. Each observation carries reservoir/conditions, units, source URL and locator.
No generic porosity, permeability or PVT correlations are substituted for missing literature data.

The initial Kvitebjørn review found **title-anchored indexed excerpts**, not accessible full papers,
for Tarbert permeability (reported averages 60–75 mD), Ness gross thickness (~65 m at 34/11-1),
Tarbert thickness (6–15 m generally in one report versus 25–30 m for a lower interval in another),
and initial P/T (770.5 bar / 150 °C). All are labelled **provisional indexed excerpt** with both the
publication URL and the evidence-access URL. Reservoir/interval scopes differ; thickness values are
not net pay and have not been reconciled. The overview keeps this caveat visible.

Sources: [Walderhaug, AAPG Bulletin (2000)](https://doi.org/10.1306/a9673e96-1738-11d7-8645000102c1865d),
[Downs & Fleming, SPE (2020)](https://onepetro.org/SPEFD/proceedings-abstract/20FD/2-20FD/447156),
[Talukdar et al., SPE (2009)](https://doi.org/10.2118/121976-MS).
No securely verified numerical porosity was retained; the relevant Walderhaug study is linked for
review. Detailed fluid composition, dew point, viscosity, Z-factor, condensate density/API, net pay
and reservoir footprint remain gaps. Missing literature values are explicitly not inferred.

Coverage on the live corpus (142 fields): depth 96 %, formations 82 %, discovery/PDO/start years ≥ 89 %,
drainage strategy 100 % (incl. "Not stated").

## Pressure / temperature (`utils/pt.py`, `data/reservoir_pt.csv`)

SODIR has no P/T table; descriptions only flag HPHT. Values come from, in order:
1. a CSV you upload in **Benchmark → Reservoir P/T** (session only; flexible column names),
2. the built-in initial reservoir pressure/temperature table for ~27 fields; legacy rows without a
   directly checked source URL are explicitly labelled **unverified**, not scientifically validated,
3. numbers stated in the SODIR text,
4. a **hydrostatic (0.101 bar/m) and geothermal (4 °C + 35 °C/km of sediment)** estimate from the text
   depth. HPHT fields never receive a pressure estimate.

The source and confidence are shown next to every value. Verify before any decision use.

## Economics: screening, not actual profit or an official prognosis

The Economics page requires acknowledgment of assumptions before calculating. Defaults are illustrative.
Historical product volumes are repriced at fixed user-supplied USD prices and NOK/USD, with user fixed
and variable OPEX, and source nominal investment. This is a counterfactual screening scenario, **not
actual historical profitability**. No tax, financing, tariffs, equity allocation or abandonment is modeled;
there is no inflation adjustment in this page. Historical costs must be complete within the modeled
interval; missing years/invalid volumes are explicit errors. SODIR zeros can be placeholders.

* Liquid revenue = million Sm³ × 6.28981 bbl/Sm³ × USD/bbl × NOK/USD (million NOK).
  Gas revenue = billion Sm³ × 1,000 × USD/Sm³ × NOK/USD (million NOK).
* OPEX = o.e. × 6.28981 × variable USD/boe × FX + fixed million NOK/year in producing years.
  Oil equivalent for this model is oil + gas + condensate + 1.9 × NGL in SODIR volume units.
  Fixed OPEX before production is omitted, another limitation.
* Annual free cash flow = revenue − OPEX − investment. Operating margin excludes investment.
  Capital payback is the first non-negative cumulative year after a negative balance; a zero initial
  balance alone is not payback. Later capital may reverse recovery. No fractional-year interpolation.
* Discounted cash flow assumes year-end cash flows discounted from the start of the first modeled
  year. NPV and discounted payback use the same user discount rate.
* No forecast means no cessation estimate. An optional exponential decline applies a user effective
  annual decline to every product from the cutoff-year mix. It ignores reserve/facilities constraints,
  new wells and compression; it is **not** an operator/SODIR prognosis.
* CSV/XLSX prognosis imports require consecutive whole years immediately after the historical cutoff
  and oil/gas/condensate/ngl product volumes (same units as above). Omitted products mean zero; blanks,
  negatives, nonfinite values, gaps and duplicate years are rejected. Optional `investment_mnok`
  supplies annual future capital; otherwise the user supplies a fixed annual investment assumption.
* The first forecast year with operating margin ≤ 0 (or zero production) is the scenario economic limit;
  the preceding year is labelled the last operating year. This assumes no restart and excludes capital
  from the limit test. If the limit is not reached, cessation is **undetermined beyond the horizon**,
  not assumed at the last forecast year. Full forecasts remain untruncated for transparency.

The overview shows the last user-calculated scenario, clearly marked as not auto-refreshed.
Economics exports retain inputs, units in column names, historical/scenario row basis and forecast mode.

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
* **Investment cost**: annual/cumulative reported field investment, investment per recoverable/produced
  boe, field investment per development wellbore/producer, and annual investment per annual produced boe.
  Uses the same peer filters and category colours, with selected-field highlighting, rankings, category
  distributions, annual histories and downloadable metric/coverage tables.

### Map themes and sketch tools

The layer menu offers Street (OpenStreetMap), Light, Gray and Dark (CARTO), and Satellite (Esri).
SODIR WMS overlays and the selected-field boundary remain independent of the basemap.
Leaflet.draw adds editable lines, polygons, rectangles, circles and markers. Lines show summed
great-circle segment distances; polygons/rectangles show approximate geodesic areas; circles show
radius and approximate planar area. A metric scale is included. These are screening tools, not
survey/navigation measurements.

Export drawings as GeoJSON before switching field, overlays or page: iframe redraws discard sketches.
GeoJSON circles are represented as centre points with `shape`, `radius_m` and `area_m2` properties.
Measurements update after edits; drawings and measurements are not uploaded or saved by the app.
Basemap tiles and Leaflet/Leaflet.draw assets require internet access; errors are displayed if unavailable.

### Investment methodology and adjustments

[SODIR's investment report](https://factpages.sodir.no/en/field/TableView/Investments) labels the source
amounts as **million NOK, nominal values**. Historical totals therefore mix price years unless adjusted.
The benchmark excludes the current calendar year and later years; the default cutoff is the latest
nonzero investment year in the filtered peer set. Inspect reported zeros carefully: recent years can
contain placeholders. Missing years remain gaps, never zero-filled; coverage is included in exports.
Negative source revisions are retained.

* 1 Sm³ o.e. = **6.28981 boe**. Million currency / (million Sm³ o.e. × 6.28981) gives currency/boe.
* Investment per produced boe uses cumulative reported production through the investment cutoff,
  including early/test production. Investment per recoverable boe uses the **latest** total recoverable
  volume, not a reconstruction of reserves as of the cutoff. Neither ratio is full-life cost or breakeven.
* Investment per well uses development **wellbores completed through the cutoff**, excluding
  predrilled/never-drilled records and missing completion years. Sidetracks are separate wellbores.
  Total field capital includes facilities and other investment: this is **not individual well drilling cost**.
* FX is optional: choose USD/EUR/GBP and supply a fixed **NOK per currency unit** rate. All years are
  divided by that rate, not converted at historical exchange rates. No live FX rate is supplied.
* Constant-price adjustment is optional: upload a CSV with `year,index`, positive finite indices for
  every investment year and the reference year. Annual nominal cost is multiplied by
  `index(reference year) / index(investment year)`, then FX is applied. Missing/invalid indices are
  rejected explicitly; no inflation series is invented. Choose an index suitable for your analysis
  (consumer inflation and upstream capital-cost indices are not interchangeable).
* Costs are gross field investment only: no OPEX, equity allocation, financing, tax or abandonment
  model is added. Currency, price basis, FX, reference year and annual factors accompany the downloads.

### Definitions

* Years since start = calendar year − first production year + 1 (current calendar year excluded as partial).
* Per-well values divide by production wells completed and not yet plugged in that year (wells without a
  plugged date stay counted, so late-life counts are conservative).
* Missing or invalid well years (including SODIR's zero placeholders) are excluded from completion-year
  charts and annual producer estimates, but the well records remain in overall well counts.
* Formation tops are matched to the field's development wellbores. Where SODIR has no matching rows,
  the app explains the gap and offers discovery-well tops when available, only after explicit selection.
  Discovery-well intervals are not field-wide reservoir depths or confirmation of productive intervals.
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
