package com.traclabs.biosim.server.simulation.framework;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class StoreTankPressureTest {

    @Test
    void pressureIsNRTOverV() {
        Store store = new Store(0, "O2_Store");
        store.setTankVolume(250f);
        store.setCurrentLevel(2000f);
        float expected = 2000f * 8.314f * 296.15f / 250f;
        assertEquals(expected, store.getTankPressureKpa(), 1f);
    }

    @Test
    void missingVolumeIsZeroPressure() {
        Store store = new Store(0, "O2_Store");
        store.setCurrentLevel(2000f);
        assertEquals(0f, store.getTankPressureKpa());
    }
}
