---
name: cabin-watch
description: Duty procedure for Cabin 1 night console.
---

# Cabin watch

1. `read_habitat` before any write.
2. Climbing CO₂ → raise `VCCR` `consumers` `power`.
3. Falling cabin O₂ → raise `O2_Injector` `consumers` `O2`.
4. Falling O₂ tank → raise `OGS` water in and O₂ out.
5. `read_sband` every watch. Ground is part of the job. The board is still the sensor.
6. Set the board. Stop. You will be woken.
