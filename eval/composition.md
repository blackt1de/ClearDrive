# eval-v1 composition

Generated from `eval/eval_set.json` and `eval/codeless_set.json` at freeze. Methods-section numbers; nothing here is rounded up.

## Eval set: 102 cases

| Case type | Count |
|---|---|
| reconstructed (NHTSA complaint, confirmed repair) | 62 |
| synthetic (built from diagnostics.py rules) | 40 |

**Synthetic share: 39.2%** (cap 40%).

### By primary label

| Label | Reconstructed | Synthetic | Total |
|---|---|---|---|
| vacuum_intake_leak | 4 | 3 | 7 |
| fuel_delivery | 4 | 3 | 7 |
| maf_sensor | 1 | 6 | 7 |
| ignition_component | 5 | 2 | 7 |
| fuel_injector | 5 | 2 | 7 |
| catalytic_converter | 4 | 3 | 7 |
| oxygen_sensor | 3 | 4 | 7 |
| evap_system | 5 | 2 | 7 |
| valve_timing_air_aux | 4 | 3 | 7 |
| air_fuel_metering_other | 8 | 0 | 8 |
| ignition_system_sensor | 4 | 3 | 7 |
| emissions_control_other | 3 | 3 | 6 |
| idle_speed_auxiliary | 2 | 4 | 6 |
| control_module | 4 | 2 | 6 |
| transmission | 6 | 0 | 6 |

Labels below 5 cases: none.
Labels with fewer than 5 **reconstructed** cases (topped up with synthetic): vacuum_intake_leak (4), fuel_delivery (4), maf_sensor (1), catalytic_converter (4), oxygen_sensor (3), valve_timing_air_aux (4), ignition_system_sensor (4), emissions_control_other (3), idle_speed_auxiliary (2), control_module (4).

### By make

| Make | Cases |
|---|---|
| Ford | 22 |
| Chevrolet | 13 |
| Toyota | 11 |
| Honda | 11 |
| Nissan | 8 |
| Jeep | 6 |
| GMC | 5 |
| Hyundai | 5 |
| Volkswagen | 4 |
| Subaru | 4 |
| Kia | 4 |
| Volvo | 3 |
| Ram | 3 |
| Audi | 3 |

14 makes.

### By OBD era

| Era | Cases |
|---|---|
| pre-CAN | 28 |
| CAN | 74 |
| OBDonUDS | 0 |

**OBDonUDS is not represented.** There is no sourced list of which vehicles use SAE J1979-2, and tagging one would be a guess (ruling, 2026-09-25). Acceptance criterion 3 ("all three OBD eras") is therefore only partly met. Era is assigned by model year: pre-CAN before 2008, CAN from 2008.

## Codeless set (H4): 30 profiles, 119 documented issues

| Make | Profiles |
|---|---|
| Toyota | 3 |
| GMC | 3 |
| Hyundai | 3 |
| Kia | 3 |
| Subaru | 3 |
| Chevrolet | 2 |
| Honda | 2 |
| Nissan | 2 |
| Ram | 2 |
| Audi | 2 |
| Volvo | 2 |
| Ford | 1 |
| Jeep | 1 |
| Volkswagen | 1 |

14 makes. Eras: pre-CAN 10, CAN 20, OBDonUDS 0.

Every documented issue is an NHTSA recall, as returned by the backend's own retrieval call (`knowledge.search_nhtsa_recalls`, top 5). `known_issues.json` was not used: its entries have no `source` field, so they meet neither qualifying condition (two or more independent sources, or a recall).

## How the reconstructed cases were chosen

- **Sweep.** Every NHTSA complaint for the 14 ruled makes, MY2000–2022, plus the `known_issues.json` vehicles outside that range: 5,671 model-years and about 1.1M complaints. Of these, 12,007 state a P code.
- **Shortlist.** 1,069 mention a completed repair near a component, and 780 remain after dropping narratives with failure or recurrence cues.
- **Adjudication.** 251 were read in full by the executor; 62 were accepted. Each case has a quoted repair sentence (`eval/sources/adjudication.json`), and every rejection has a reason.
- **Label.** Taken from the component repaired, not from the DTC.
- **Payload.** Vehicle plus the stated DTCs. Every measurement is null (ruling, 2026-09-25), so no value is constructed from the label.
- **Known bias.** Complaints that name both a code and a successful repair skew toward components owners can name, such as throttle bodies, coils and converters. Labels such as MAF and idle/auxiliary rest mostly on synthetic cases.
