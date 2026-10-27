# Sample plans

| # | Trip | Dates | Travellers | Visiting | Verdict
|---|---|---|---|---|---|
| 1 | Austin, TX → Richmond, VA | 10 Nov – 17 Nov 2026 | 2 adults, 1 child | elderly | **Stop** (high)
| 2 | New York, NY → Portland, OR | 28 Sep – 3 Nov 2026 | 2 adults, 1 child | none | **Caution** (moderate)
| 3 | New York, NY → Philadelphia, PA | 13 Dec – 17 Dec 2026 | 2 adults, 0 children | none | **Go** (low)

---

## 1. Stop: Austin, TX → Richmond, VA

### Input

| Field | Entered on the page | Sent to the planner |
|---|---|---|
| Location | Austin to Richmond | from Austin, TX to Richmond, VA (county: City of Richmond) |
| Dates | 10/11/2026 to 17/11/2026 | 2026-11-10 to 2026-11-17 |
| Travellers | 2 adults, 1 child | `adults: 2, children: 1` |
| Visiting | elderly | `with: ["older_adult"]` |

### Output

> **Stop: Reconsider, or go with full precautions**
>
> A lot of COVID-19 in Virginia's wastewater, and it is rising. Flu is showing
> up in a fair share of samples in Virginia, and the trend is rising. Counted
> as high because the household includes older adults.

| Source | Level | Finding | Written by |
|---|---|---|---|
| COVID-19 in wastewater | high | 100% of 2 samples positive in Virginia, up from 61% two weeks before (+39 points); latest sample 13 Oct | nemotron-3-ultra-550b-a55b |
| Flu (influenza A) in wastewater | moderate | 7% of 30 samples from 22 sites positive in Virginia, up from 0% (+7 points); latest sample 20 Oct | nemotron-3-ultra-550b-a55b |
| Whooping cough | low | Virginia: 200 cases this year (2.25 per 100,000), lower than last year and below the national 3.47. Texas: 1,212 (3.82 per 100,000) | template |
| Weather | low | Mild, mostly sunny, highs in the 70s, evenings in the 40s–50s; slight chance of showers Sunday and Monday | nemotron-3.5-lightning-30b-a3b |
| CDC guidance | advice | Visiting an older adult (65+): high-dose, recombinant or adjuvanted flu vaccine, ideally by the end of October; contact a provider promptly with flu symptoms | rules (CDC text) |

**Before you go**

- [ ] Check the wastewater readings again a few days before you travel.
- [ ] Wear a well-fitted mask on the journey and in crowded indoor places.
- [ ] Keep hand hygiene strict around older relatives and air the rooms you share.
- [ ] Dress in layers with a warm coat, hat and gloves for cool evenings in the 40s‑50s to protect older joints from stiffness.
- [ ] Wear non-slip, supportive footwear and use an umbrella or rain‑gear with a sturdy handle to prevent falls on potentially wet surfaces during the slight Sunday‑Monday showers.
- [ ] Stay home if you have symptoms, and read the CDC guidance section below.

**Best days outdoors:** today, Wednesday, Thursday, Friday, Saturday, Sunday, Monday.

**How the agents got there**

- Richmond City had no recent wastewater samples. The evaluator asked the COVID-19 and flu agents again at state level, and the planner used the Virginia answers.
- The evaluator reviewed three drafts. The composer's Nemotron prose cited a figure (95, from "N95") that is not in the fact sheet, so the planner used the template prose instead.

---

## 2. Caution: New York, NY → Portland, OR

### Input

| Field | Entered on the page | Sent to the planner |
|---|---|---|
| Location | New York to Portland | from New York, NY to Portland, OR (county: Multnomah County) |
| Dates | 28/09/2026 to 03/11/2026 | 2026-09-28 to 2026-11-03 |
| Travellers | 2 adults, 1 child | `adults: 2, children: 1` |
| Visiting | none | `with: []` |

The page fills in the top geocoder match, so "Portland" becomes Portland, Oregon.

### Output

> **Caution: Go with care**
>
> Whooping cough in Oregon is lower than at this point last year and above the
> national rate. Go with care. Overnight: 77% chance of rain; Tuesday: 87%
> chance of rain; Tuesday Night: 96% chance of rain; Wednesday: 81% chance of
> rain; Wednesday Night: 70% chance of rain; Thursday: 74% chance of rain.

| Source | Level | Finding | Written by |
|---|---|---|---|
| COVID-19 in wastewater | no level | No samples in Multnomah County in the two weeks asked about; the latest reading (21–27 Sep) had 2 of 2 samples positive | nemotron-3-ultra-550b-a55b |
| Flu (influenza A) in wastewater | no level | No samples in the two weeks asked about; the latest reading (28 Sep – 4 Oct) had 1 of 2 samples positive | nemotron-3-ultra-550b-a55b |
| Whooping cough | moderate | Oregon: 331 cases this year (7.75 per 100,000), lower than last year but above the national 3.47. New York: 656 (3.28 per 100,000) | template |
| Weather | moderate | Rain through Thursday night (74% to 96% chance) and cool; drier and partly sunny from Friday | nemotron-3.5-lightning-30b-a3b |
| CDC guidance | advice | Visiting family and friends: stay home with respiratory symptoms; after 24 hours without fever, take extra care for 5 days | rules (CDC text) |

A source with no level does not count toward the verdict, so Caution comes from
whooping cough and the weather.

**Before you go**

- [ ] Make sure everyone visiting is up to date with whooping cough (Tdap) vaccination, at least two weeks before the visit.
- [ ] Overnight: 77% chance of rain
- [ ] Tuesday: 87% chance of rain
- [ ] Stay home if you have symptoms, and read the CDC guidance section below.

**Best days outdoors:** Friday, Saturday, Sunday, Monday.

**How the agents got there**

- The evaluator asked the COVID-19 and flu agents again at state level. Those answers were no better, so the planner kept the county answers.
- As in sample 1, the composer's prose cited figures not in the fact sheet, so the template prose was used.

---

## 3. Go: New York, NY → Philadelphia, PA

### Input

| Field | Entered on the page | Sent to the planner |
|---|---|---|
| Location | New York to Philadelphia | from New York, NY to Philadelphia, PA (county: Philadelphia County) |
| Dates | 13/12/2026 to 17/12/2026 | 2026-12-13 to 2026-12-17 |
| Travellers | 2 adults, 0 children | `adults: 2, children: 0` |
| Visiting | none | `with: []` |

### Output

> **Go: Good to go**
>
> Philadelphia County wastewater shows little flu activity, and Pennsylvania
> whooping cough cases are below last year's level and near the national rate.
> The weather forecast only covers the next 7 days, so check again closer to
> your December 13-17 travel dates for an updated outlook.

| Source | Level | Finding | Written by |
|---|---|---|---|
| COVID-19 in wastewater | no level | No samples in the two weeks asked about; the latest reading (28 Sep – 4 Oct) had 6 of 6 samples positive from 3 sites | nemotron-3-ultra-550b-a55b |
| Flu (influenza A) in wastewater | low | 0% of 1 sample positive in Philadelphia County, flat against two weeks before; latest sample 13 Oct | nemotron-3-ultra-550b-a55b |
| Whooping cough | low | Pennsylvania: 329 cases this year (2.52 per 100,000), lower than last year and close to the national 3.47. New York: 656 (3.28 per 100,000) | template |
| Weather | low | Mild and mostly sunny, highs in the 60s–70s, evenings in the 50s; showers likely Sunday and Monday | nemotron-3.5-lightning-30b-a3b |
| CDC guidance | advice | Visiting family and friends: stay home with respiratory symptoms; after 24 hours without fever, take extra care for 5 days | rules (CDC text) |

**Before you go**

- [ ] Carry a light rain jacket for Sunday and Monday evenings when showers become more likely.
- [ ] Bring a light layer for evenings cooling into the 50s.
- [ ] Wash hands frequently and carry hand sanitizer.
- [ ] Monitor for any respiratory symptoms during the visit.

**Best days outdoors:** today, Wednesday, Thursday, Friday, Saturday, Sunday, Monday.

**How the agents got there**

- The evaluator passed the third draft, so this plan's summary and checklist are Nemotron prose (nemotron-3-ultra-550b-a55b), checked against the fact sheet.
- The evaluator asked the COVID-19 agent again at state level and kept the county answer.