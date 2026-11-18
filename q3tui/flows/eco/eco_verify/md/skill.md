---
label: "5"
title: VERIFY — dv + Sanity again on the ECO'd design (project mode)
deps: [eco_rtl]
gate: none
options: {}
view: [schemas/eco_verify.json, reports/dv_test_results.md]
---
Project mode: you are asked whether Verification (the dv flow) and Sanity (CDC / RDC) run again on the ECO'd RTL and spec (option `verify` answers for you). Yes: both run within this step and must pass before the netlist ECO (`eco_patch`). Their RTL and spec fixes come back to `eco_rtl` / `eco_spec` — judged first, made the smallest way — never to the rtl flow's generator; a request `eco_rtl` judges not the ECO's to fix stops here for you. External mode (a fire-fighting ECO) and "no": skipped.
