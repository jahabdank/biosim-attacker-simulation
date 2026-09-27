package com.traclabs.biosim.server.simulation.air;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class VCCRLangmuirLawTest {

    @Test
    void zeroPowerMovesNoAir() {
        assertEquals(0f, VCCRLangmuir.molesAirThisTick(0f, 55f, 296.15f, 1f / 60f));
    }

    @Test
    void adsorbNameplateIsIdealGasFlow() {
        float hourly = VCCRLangmuir.molesAirThisTick(VCCRLangmuir.W_ADSORB_WATTS, 55f, 296.15f, 1f);
        float expected = VCCRLangmuir.Q_REF_LITERS_PER_HOUR * 55f / (8.314f * 296.15f);
        assertEquals(expected, hourly, 5f);
    }

    @Test
    void langmuirDoesNotStripTheWholeSlug() {
        float nAir = 30f;
        float nCo2 = 0.3f;
        float removed = VCCRLangmuir.co2RemovedFromSlug(nAir, nCo2);
        assertTrue(removed > 0f && removed < nCo2, "removed=" + removed);
    }

    @Test
    void floorStopsRemovalAt600ppm() {
        float nAir = 1000f;
        float nCo2 = VCCRLangmuir.Y_CO2_FLOOR * nAir;
        assertEquals(0f, VCCRLangmuir.co2RemovedFromSlug(nAir, nCo2));
    }
}
