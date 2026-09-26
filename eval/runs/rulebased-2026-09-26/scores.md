# Scores: rulebased-2026-09-26

**H1 macro-F1: 0.7401**; top-1 accuracy 0.7549 over 102 cases.

**H4 hit rate: 0.0** (threshold 0.5).

H4 system-level null (fixed generic response, scored the same way): 0.0.

H4 part-level null (fixed generic response naming parts): 0.3333. Read H4 against both nulls, not against the threshold alone.

| Label | P | R | F1 | Support |
|---|---|---|---|---|
| vacuum_intake_leak | 0.0 | 0.0 | 0.0 | 7 |
| fuel_delivery | 0.4118 | 0.7 | 0.5185 | 10 |
| maf_sensor | 1.0 | 0.5455 | 0.7059 | 11 |
| ignition_component | 0.7778 | 0.875 | 0.8235 | 8 |
| fuel_injector | 1.0 | 0.375 | 0.5455 | 8 |
| catalytic_converter | 1.0 | 1.0 | 1.0 | 7 |
| oxygen_sensor | 1.0 | 0.875 | 0.9333 | 8 |
| evap_system | 1.0 | 0.5714 | 0.7273 | 7 |
| valve_timing_air_aux | 1.0 | 0.875 | 0.9333 | 8 |
| air_fuel_metering_other | 0.8889 | 0.8889 | 0.8889 | 9 |
| ignition_system_sensor | 1.0 | 1.0 | 1.0 | 8 |
| emissions_control_other | 0.8571 | 1.0 | 0.9231 | 6 |
| idle_speed_auxiliary | 0.8333 | 0.8333 | 0.8333 | 6 |
| control_module | 0.6 | 0.4286 | 0.5 | 7 |
| transmission | 0.8333 | 0.7143 | 0.7692 | 7 |

Unmapped LIKELY CAUSES (text present, no taxonomy label): 0
Cases with no saved response: 0 []
Failed calls: n/a (no model calls)
