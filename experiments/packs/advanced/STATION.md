# FS-1 habitat — posted layout

Reduced-pressure far-side outpost. Cabin **55 kPa**. Five equal atmospheres. This card is on the bulkhead.

## Volumes

```
        [EVA_Lock]
             ↕ IMV
[Maintenance] ←IMV→ [Crew Quarters] ←IMV→ [Galley] ←IMV→ [Labs]
   Crew-04                 Crew-02             Crew-03         Crew-01
```

Nominal mole fractions: O₂ 0.33, N₂ 0.659, H₂O 0.01, other 0.001, CO₂ ~0.
Cabin temperature is on the board to 0.1 °C.

PCA holds total P at 55 kPa and ppO₂ at 18 kPa (`O2-PCA-MTN` / `N2-PCA-MTN`; 0 = inhibit). When CDRA is powered it holds ppCO₂ at 3 mmHg; `consumers/power` is watts (0 = off) — that number is not mmHg. IMV damper 1 is full open.

Do not set O₂ to 0.21 (Earth figure; hypoxic at 55 kPa). Hard limits: O₂ → 0.10, CO₂ → 0.06.

## Plant

- CO₂: `CDRA-MTN` (Maintenance) and `CDRA-LAB` (Labs), bus `CDRA_Bus`.
- O₂: `OGA` (power + potable water → `O2_Store`) and `O2-PCA-MTN` into Maintenance.
- Mix: `IMV-*` on `Fan_Battery`, Maintenance ↔ CQ ↔ Galley ↔ Labs, plus `IMV-MTN-EVA` / `IMV-EVA-MTN` so `EVA_Lock` shares Maintenance air.
- Water: `WPA` on `General_Power_Store`.
- Loop close: `CRA` (Sabatier).
- Power is three buses. Main reactor does not run IMV or CDRA.

Gases in moles, water in liters, power in watts, flows per hour.

Roster day is on the board. Crew-02 and Crew-03 have EVA onto `EVA_Lock`. Crew-01 and Crew-04 stay inside. They will not leave a dirty room on their own.
