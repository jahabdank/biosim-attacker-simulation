package com.traclabs.biosim.server.simulation.air;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class OGSFaradayTest {

    @Test
    void zeroPowerProducesNoOxygen() {
        assertEquals(0f, OGSFaraday.oxygenMolesFromPower(0f, 1f));
    }

    @Test
    void thousandWattsIsFaradayNotTheOldWattFudge() {
        float hourly = OGSFaraday.oxygenMolesFromPower(1000f, 1f);
        // η * 1000 W * 3600 / (4 * 96485 * 1.48) ≈ 4.41 mol/h
        assertEquals(4.41f, hourly, 0.15f);
        // Old law was ~15 mol/h at 1000 W.
        assertTrue(hourly < 8f);
    }

    @Test
    void waterStoichIsTwoMolesPerOxygen() {
        float liters = OGSFaraday.litersWaterForOxygenMoles(1f);
        assertEquals(2f * 18.01524f / 1000f, liters, 1e-5f);
    }
}
