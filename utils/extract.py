"""Rule-based extraction of reservoir and development facts from SODIR field descriptions.

Each field has five free-text sections (Development, Reservoir, Recovery strategy,
Transport, Status). The functions below turn those into structured, comparable
attributes. Every rule is deliberately conservative: when nothing matches, the
attribute is left empty rather than guessed.
"""
import re

import pandas as pd

SECTIONS = ("Development", "Reservoir", "Recovery strategy", "Transport", "Status")

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
}
AGE_WORDS = {
    "triassic", "jurassic", "cretaceous", "paleocene", "palaeocene", "eocene", "oligocene",
    "miocene", "pliocene", "permian", "carboniferous", "devonian", "tertiary", "paleogene",
    "neogene", "quaternary", "precambrian", "lower", "middle", "upper", "early", "late",
}
NOT_FORMATION = AGE_WORDS | {
    "the", "and", "in", "of", "main", "overlying", "underlying", "several", "both", "other",
    "a", "an", "this", "these", "sandstone", "chalk", "reservoir", "reservoirs", "group",
    "formation", "formations", "age", "thin", "deeper", "shallower", "injected", "or",
}
AGE_PATTERN = re.compile(
    r"\b((?:Lower|Middle|Upper|Early|Late)\s+)?(Triassic|Jurassic|Cretaceous|Paleocene|Palaeocene|"
    r"Eocene|Oligocene|Miocene|Pliocene|Permian|Carboniferous|Devonian|Paleogene|Neogene|Tertiary)\b",
    re.I,
)
LITHOLOGY_PATTERN = re.compile(
    r"\b(sandstones?|chalk|carbonates?|limestones?|dolomites?|spiculites?|conglomerates?|"
    r"injectites?|basement|siltstones?|shale)\b", re.I,
)
FORMATION_PATTERN = re.compile(
    r"((?:[A-ZÆØÅ][\w\-æøåÆØÅ]*(?:,\s*|\s+and\s+|\s+))+?)Formations?\b"
)
GROUP_PATTERN = re.compile(r"\b([A-ZÆØÅ][\w\-æøåÆØÅ]*(?:/[A-ZÆØÅ][\w\-æøåÆØÅ]*)?)\s+Group\b")
INTRA_PATTERN = re.compile(r"\bintra-([A-ZÆØÅ][\w\-æøå]+)", re.I)
CONCEPT_TAGS = (
    ("FPSO", r"\bFPSO\b|floating production,? storage and offloading|production, storage and offloading"),
    ("Subsea tie-back", r"\bsubsea\b.*?\b(tied|tie)[- ]?(back|in)|\btied[- ]back\b|\btie[- ]in\b"),
    ("Subsea template", r"\bsubsea (template|facility|installation|production system)|\btemplates?\b"),
    ("Fixed platform", r"\b(fixed|steel jacket|jacket|wellhead platform|integrated|PDQ)\b"),
    ("Concrete GBS", r"\bconcrete\b|\bgravity[- ]base"),
    ("TLP", r"tension[- ]leg"),
    ("Semi-submersible", r"semi-?submersible"),
    ("Spar / FSU", r"\bspar\b|\bFSU\b|storage unit"),
    ("Unmanned", r"\bunmanned\b|remotely operated|not normally manned"),
    ("Power from shore", r"power from (shore|land)|electrified|electrification"),
    ("Onshore processing", r"onshore (plant|facility|processing|terminal)|processed onshore|\bland plant\b"),
)
DRIVE_TAGS = (
    ("Pressure depletion", r"pressure depletion|natural depletion|\bdepletion\b|blow-?down"),
    ("Water injection", r"water injection|water-?flood|injection of (produced |sea)?water|water injector|reinjection of produced water|produced water (is|was|are) (re)?injected|(gas and water|water and gas) injection|water (?:is|was|will be) injected"),
    ("Gas injection", r"gas injection|gas (is |was |will be |are )?(also )?(re-?)?injected|reinjection of gas|gas re-?injection|gas injector|(gas and water|water and gas) injection"),
    ("WAG", r"water[- ]alternating[- ]gas|\bWAG\b|\bSWAG\b|\bFAWAG\b"),
    ("Natural water drive", r"aquifer|water drive|natural water"),
    ("Gas cap expansion", r"gas cap"),
    ("Compaction drive", r"compaction"),
    ("Gas lift", r"gas[- ]lift"),
    ("Pumps / ESP", r"\bESP\b|electric(al)? submersible|subsea (boosting|pump|compression)|multiphase pump|wet gas compress"),
    ("EOR (chemical / polymer / foam)", r"\bpolymer\b|\bfoam\b|low[- ]salinity|surfactant|\bEOR\b|microbial"),
    ("Produced water reinjection", r"produced water (is |was |are )?(re-?)?injected|reinjection of produced water|PWRI"),
)
PRIMARY_CLAUSE = re.compile(
    r"(?:is|was|are|were|will be|being)\s+(?:currently\s+|mainly\s+|primarily\s+)?(?:produced|recovered|drained|developed)\s+"
    r"(?:by|with|through|using|under)\s+([^.]+)|"
    r"(?:strategy|mechanism|drive)\s+(?:is|was|will be)\s+(?:based\s+(?:primarily\s+|mainly\s+)?on\s+|primarily\s+|mainly\s+)?([^.]+)",
    re.I,
)
PRIMARY_DRIVE_ORDER = ("WAG", "Water & gas injection", "Water injection", "Gas injection",
                       "Natural water drive", "Pressure depletion")


def _num(token):
    token = token.lower().replace(",", "")
    if token.isdigit():
        return int(token)
    return NUMBER_WORDS.get(token)


def _metres(fragment):
    """Return (min, max) metres from '2300-2700 metres', 'about 2,500 metres', 'more than 4000 metres'."""
    fragment = fragment.replace(",", "").replace("–", "-").replace("—", "-")
    match = re.search(r"(\d{2,5})\s*(?:-|to)\s*(\d{2,5})\s*(?:m\b|metres|meters)", fragment)
    if match:
        low, high = sorted((int(match.group(1)), int(match.group(2))))
        return low, high
    match = re.search(r"(\d{2,5})\s*(?:m\b|metres|meters)", fragment)
    if match:
        value = int(match.group(1))
        return value, value
    return None


def _clean_names(raw):
    names = []
    for part in re.split(r",\s*|\s+and\s+|\s+", raw.strip()):
        part = part.strip("-–,. ")
        if not part or part.lower() in NOT_FORMATION or part[0].islower():
            continue
        names.append(part.replace("-", "-"))
    return names


def _dedupe(items):
    seen, result = set(), []
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def extract_formations(text):
    """Formation names (without the word Formation) mentioned in the text."""
    found = []
    for match in FORMATION_PATTERN.finditer(text or ""):
        raw = match.group(1)
        # 'Shetland Group and Lista Formation' -> only names after the last 'Group'
        if "Group" in raw:
            raw = raw.rsplit("Group", 1)[1]
        names = _clean_names(raw)
        # 'Upper Cretaceous Tor Formation' -> keep only trailing proper names after age words
        found.extend(names[-6:])
    for match in INTRA_PATTERN.finditer(text or ""):
        found.append(match.group(1).capitalize() if match.group(1).isupper() else match.group(1))
    return _dedupe(found)


def extract_groups(text):
    found = []
    for match in GROUP_PATTERN.finditer(text or ""):
        name = match.group(1)
        if name.lower() not in NOT_FORMATION:
            found.append(name)
    return _dedupe(found)


def extract_ages(text):
    ages = []
    for match in AGE_PATTERN.finditer(text or ""):
        qualifier = (match.group(1) or "").strip().title()
        period = match.group(2).title().replace("Palaeocene", "Paleocene")
        ages.append(f"{qualifier} {period}".strip())
    return _dedupe(ages)


def extract_lithology(text):
    found = [m.group(1).lower().rstrip("s") for m in LITHOLOGY_PATTERN.finditer(text or "")]
    found = ["chalk" if f == "chalk" else f for f in found]
    return _dedupe(found)


def extract_reservoir_depth(text):
    """Reservoir depth range (m) from the Reservoir section; excludes water-depth sentences."""
    text = text or ""
    candidates = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if re.search(r"water depth", sentence, re.I):
            continue
        for match in re.finditer(
            r"(?:depths?|located|lies?|lying|found|reservoirs?)\s+(?:of|at|is|are|between)?\s*(?:a depth of\s*)?(?:about|approximately|around|more than|over|some|roughly)?\s*"
            r"([\d,]{3,6}(?:\s*(?:-|–|to)\s*[\d,]{3,6})?)\s*(?:m\b|metres|meters)(?!\s+(?:thick|of (?:oil|gas)|oil|gas))", sentence, re.I,
        ):
            parsed = _metres(match.group(0))
            if parsed and 300 <= parsed[0] <= 7000:
                candidates.append(parsed)
    if not candidates:
        return None, None
    return min(c[0] for c in candidates), max(c[1] for c in candidates)


def extract_water_depth(text):
    match = re.search(r"water depth(?: in the area)? is\s+(?:about|approximately|around)?\s*([\d,]+(?:\s*(?:-|–|to)\s*[\d,]+)?\s*(?:m\b|metres|meters))", text or "", re.I)
    if not match:
        return None, None
    parsed = _metres(match.group(1))
    return parsed if parsed else (None, None)


def extract_years(text):
    text = text or ""
    years = {}
    match = re.search(r"discovered in (\d{4})", text, re.I)
    if match:
        years["discovery_year"] = int(match.group(1))
    match = re.search(r"\(PDO\)[^.]*?approved in (?:\w+ )?(\d{4})", text, re.I) or \
        re.search(r"PDO[^.]*?approved in (?:\w+ )?(\d{4})", text, re.I)
    if match:
        years["pdo_year"] = int(match.group(1))
    starts = [int(m.group(1)) for m in re.finditer(
        r"production (?:from [^.]*? )?(?:started|commenced|began|start-up was) in (?:\w+ )?(\d{4})", text, re.I)]
    starts += [int(m.group(1)) for m in re.finditer(
        r"In (?:\w+ )?(\d{4}),? (?:the )?(?:test |ordinary )?production(?: from [^.,]*?)? (?:started|commenced|began)", text, re.I)]
    if starts:
        years["production_start_text"] = min(starts)
    match = re.search(r"(?:production )?(?:ceased|was shut down|shut down|closed down|stopped) in (?:\w+ )?(\d{4})", text, re.I)
    if match:
        years["shutdown_year"] = int(match.group(1))
    phases = {m.group(0).upper() for m in re.finditer(r"Phase\s+(?:I{1,3}V?|IV|V|\d)\b", text)}
    if phases:
        years["development_phases"] = len(phases)
    elif re.search(r"(multiple|several|a number of) phases|phased development", text, re.I):
        years["development_phases"] = 2
    return years


def extract_well_counts(text):
    """Well counts stated in the text: (producers, injectors, total slots). None when not stated."""
    text = (text or "").replace("\n", " ")
    producers = injectors = None
    for match in re.finditer(r"\b([\w,]+)\s+(?:horizontal\s+|multilateral\s+|oil\s+|gas\s+|subsea\s+|long\s+)?(?:production|producing|producer)\s+wells?", text, re.I):
        value = _num(match.group(1))
        if value:
            producers = (producers or 0) + value
    for match in re.finditer(r"\b([\w,]+)\s+(?:horizontal\s+|water\s+|gas\s+|subsea\s+)?(?:injection|injector)\s+wells?", text, re.I):
        value = _num(match.group(1))
        if value:
            injectors = (injectors or 0) + value
    match = re.search(r"\b([\w,]+)\s+well slots", text, re.I)
    slots = _num(match.group(1)) if match else None
    return producers, injectors, slots


def extract_recovery_factor(text):
    """Recovery factors stated in the text as fractions; returns (initial, expected)."""
    values = [int(m.group(1)) for m in re.finditer(r"recovery factor[^.]*?(\d{1,2})\s*(?:per cent|percent|%)", text or "", re.I)]
    if not values:
        return None, None
    return (values[0] / 100, values[-1] / 100) if len(values) > 1 else (None, values[0] / 100)


def extract_tags(text, table):
    return [label for label, pattern in table if re.search(pattern, text or "", re.I | re.S)]


def classify_drive(mechanisms):
    """Primary drainage strategy from the list of mechanisms found in the text."""
    has = set(mechanisms)
    if "WAG" in has:
        return "WAG"
    if {"Water injection", "Gas injection"} <= has:
        return "Water & gas injection"
    if "Water injection" in has:
        return "Water injection"
    if "Gas injection" in has:
        return "Gas injection"
    if "Natural water drive" in has:
        return "Natural water drive"
    if "Pressure depletion" in has or "Gas cap expansion" in has or "Compaction drive" in has:
        return "Pressure depletion"
    return "Not stated"


def primary_drive(recovery_text, mechanisms):
    """Prefer the mechanism in the sentence that states how the field *is produced*.

    'The strategy is based primarily on pressure depletion ... produced water was
    reinjected' should read as depletion, not water injection.
    """
    match = PRIMARY_CLAUSE.search(recovery_text or "")
    if match:
        clause = match.group(1) or match.group(2) or ""
        primary = classify_drive(extract_tags(clause, DRIVE_TAGS))
        if primary != "Not stated":
            return primary
    return classify_drive(mechanisms)


def extract_sub_area(text):
    text = text or ""
    match = re.search(r"\bin the ([A-ZÆØÅ][\w\-æøå]+(?: [A-ZÆØÅ][\w\-æøå]+)?) area\b", text)
    if match and match.group(1).lower() not in ("same", "surrounding", "southern", "northern"):
        return match.group(1)
    match = re.search(r"\bon (?:the )?([A-ZÆØÅ][\w\-æøå]+(?: [A-ZÆØÅ][\w\-æøå]+)?) High\b", text)
    if match:
        return f"{match.group(1)} High"
    match = re.search(r"\b(Haltenbanken|Tampen|Utsira High|Halten Terrace|Dønna Terrace|Hammerfest Basin|Viking Graben|Horda Platform|Ekofisk|Sleipner|Balder|Alvheim|Oseberg|Troll|Norne|Heidrun|Gjøa|Snorre|Statfjord) area\b", text)
    return match.group(1) if match else None


def hpht_flag(text):
    return bool(re.search(r"\bHPHT\b|\bHTHP\b|high pressure and high temperature|high temperature and high pressure", text or "", re.I))


def extract_pressure_temperature(text):
    """Explicit numbers only: 'xxx bar' and 'yyy °C / degrees Celsius'."""
    text = text or ""
    pressure = re.search(r"(\d{2,4})\s*bar\b", text, re.I)
    temperature = re.search(r"(\d{2,3})\s*(?:°\s*C|degrees? C(?:elsius)?|deg C)", text, re.I)
    return (int(pressure.group(1)) if pressure else None, int(temperature.group(1)) if temperature else None)


def sections_for_field(descriptions, field):
    """Dict heading -> text for one field (empty strings when missing)."""
    out = {section: "" for section in SECTIONS}
    if descriptions is None or descriptions.empty or "fldName" not in descriptions:
        return out
    rows = descriptions.loc[descriptions["fldName"] == field]
    for _, row in rows.iterrows():
        heading = str(row.get("fldDescriptionHeading") or "")
        text = row.get("fldDescriptionText")
        if pd.isna(text):
            continue
        for section in SECTIONS:
            if section.lower() in heading.lower():
                out[section] = (out[section] + " " + str(text)).strip()
    return out


def extract_field_facts(sections):
    """Structured facts for one field from its description sections."""
    reservoir = sections.get("Reservoir", "")
    recovery = sections.get("Recovery strategy", "")
    development = sections.get("Development", "")
    status = sections.get("Status", "")
    everything = " ".join(sections.values())
    mechanisms = extract_tags(recovery + " " + status, DRIVE_TAGS)
    depth_min, depth_max = extract_reservoir_depth(reservoir)
    water_min, water_max = extract_water_depth(development)
    producers, injectors, slots = extract_well_counts(development + " " + recovery + " " + status)
    rf_initial, rf_expected = extract_recovery_factor(recovery + " " + status)
    pressure_bar, temperature_c = extract_pressure_temperature(reservoir)
    facts = dict(
        formations=extract_formations(reservoir),
        groups=extract_groups(reservoir),
        ages=extract_ages(reservoir),
        lithology=extract_lithology(reservoir),
        depth_min_m=depth_min, depth_max_m=depth_max,
        depth_mid_m=(depth_min + depth_max) / 2 if depth_min is not None else None,
        water_depth_min_m=water_min, water_depth_max_m=water_max,
        hpht=hpht_flag(reservoir),
        pressure_bar_text=pressure_bar, temperature_c_text=temperature_c,
        mechanisms=mechanisms,
        drainage_strategy=primary_drive(recovery, mechanisms),
        gas_lift="Gas lift" in mechanisms,
        concept=extract_tags(development, CONCEPT_TAGS),
        sub_area=extract_sub_area(development),
        producers_text=producers, injectors_text=injectors, well_slots_text=slots,
        rf_initial_text=rf_initial, rf_expected_text=rf_expected,
        reservoir_quality=_quality(reservoir),
    )
    facts.update(extract_years(development + " " + status))
    facts["text_length"] = len(everything)
    return facts


def _quality(text):
    match = re.search(r"(?:reservoir )?quality is (?:generally |mostly |mainly )?((?:very |moderately |relatively )?(?:excellent|very good|good|moderate|poor|variable|varying)(?: to (?:very good|good|moderate|poor))?)", text or "", re.I)
    if match:
        return match.group(1).lower()
    match = re.search(r"\b(excellent|very good|good|moderate|poor|variable|varying) (?:reservoir )?(?:quality|properties)", text or "", re.I)
    return match.group(1).lower() if match else None


def facts_table(descriptions):
    """DataFrame indexed by field with one column per extracted fact."""
    if descriptions is None or descriptions.empty or "fldName" not in descriptions:
        return pd.DataFrame()
    rows = {}
    for field in descriptions["fldName"].dropna().unique():
        rows[field] = extract_field_facts(sections_for_field(descriptions, field))
    table = pd.DataFrame.from_dict(rows, orient="index")
    table.index.name = "fldName"
    for column in ("formations", "groups", "ages", "lithology", "mechanisms", "concept"):
        table[column] = table[column].apply(lambda v: v if isinstance(v, list) else [])
    table["main_formation"] = table["formations"].apply(lambda v: v[0] if v else None)
    table["main_group"] = table["groups"].apply(lambda v: v[0] if v else None)
    table["main_age"] = table["ages"].apply(lambda v: v[0] if v else None)
    table["main_lithology"] = table["lithology"].apply(lambda v: v[0] if v else None)
    return table
