package com.traclabs.biosim.server.simulation.environment;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class FanDamperTest {

    @Test
    void fullDamperMixingIsAboutTenMinutes() {
        float hourly = FanDamper.molesThisTick(1f, 55f, 296.15f, 1f);
        float molesInRoom = 55f * 18000f / (8.314f * 296.15f);
        float mixingHours = molesInRoom / hourly;
        assertTrue(mixingHours > 0.1f && mixingHours < 0.3f, "mixingHours=" + mixingHours);
    }

    @Test
    void zeroDamperMovesNoAir() {
        assertEquals(0f, FanDamper.molesThisTick(0f, 55f, 296.15f, 1f / 60f));
        assertEquals(0f, FanDamper.wattsForDamper(0f));
    }
}
