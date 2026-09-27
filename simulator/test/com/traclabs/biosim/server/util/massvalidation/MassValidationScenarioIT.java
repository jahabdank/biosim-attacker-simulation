package com.traclabs.biosim.server.util.massvalidation;

import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class MassValidationScenarioIT {
    private static final int N_TICKS = 200;
    private static final Path XML_PATH = Path.of("configuration/test/MassValidationInit.xml");

    @Test
    void massConservationHolds() throws Exception {
        MassLedger ledger = MassValidationScenario.runScenario(
                XML_PATH, N_TICKS, Path.of("target/mass-validation"), Map.of());
        MassLedger.ValidationResult result = ledger.validate(MassConstants.TOL_ABS_KG);

        assertTrue(Files.exists(ledger.getCsvPath()));
        assertTrue(Files.exists(ledger.getSummaryPath()));
        assertEquals(N_TICKS + 1, ledger.getRowCount());
        assertEquals(N_TICKS, ledger.getSimulationTicks(),
                "BioDriver did not execute the requested production simulation ticks");
        assertRequiredHeaderColumns(Files.readString(ledger.getCsvPath()).lines().findFirst().orElseThrow());
        assertScenarioStateChanged(ledger);
        assertTrue(result.passed,
                "max residual " + result.maxAbsResidual + " kg at tick " + result.worstTick
                        + " (" + result.worstCompartmentDelta + ")");
    }

    @Test
    void brokenLedgerFailsLoudly() {
        MassLedger ledger = MassValidationScenario.runScenario(
                XML_PATH, N_TICKS, Path.of("target/mass-validation-broken"),
                Map.of(MassValidationScenario.CROP_SHELF_WATER, false));
        MassLedger.ValidationResult result = ledger.validate(MassConstants.TOL_ABS_KG);

        assertFalse(result.passed);
        assertTrue(result.maxAbsResidual > MassConstants.TOL_ABS_KG);
        assertThrows(AssertionError.class, () -> assertTrue(result.passed));
    }

    private static void assertScenarioStateChanged(MassLedger ledger) {
        assertTrue(ledger.getCompartmentDelta(MassValidationScenario.POTABLE_WATER) < -1.0,
                "Crew/crop simulation did not consume potable water");
        assertTrue(ledger.getCompartmentDelta(MassValidationScenario.FOOD_STORE) < -1.0,
                "Crew simulation did not consume food");
        assertTrue(ledger.getCompartmentDelta(MassValidationScenario.DRY_WASTE) > 0.1,
                "Crew simulation did not produce dry waste");
        assertTrue(ledger.getCompartmentDelta(MassValidationScenario.CREW_BODY_MASS) > 1.0,
                "Crew body-mass accumulator did not receive simulated flows");
        assertTrue(ledger.getCompartmentDelta(MassValidationScenario.CROP_SHELF_WATER) > 1.0,
                "Crop subsystem did not buffer water during production simulation ticks");
    }

    private static void assertRequiredHeaderColumns(String header) {
        assertTrue(header.contains("tick"));
        assertTrue(header.contains(MassValidationScenario.POTABLE_WATER));
        assertTrue(header.contains(MassValidationScenario.GREY_WATER));
        assertTrue(header.contains(MassValidationScenario.DIRTY_WATER));
        assertTrue(header.contains(MassValidationScenario.FOOD_STORE));
        assertTrue(header.contains(MassValidationScenario.BIOMASS_STORE));
        assertTrue(header.contains(MassValidationScenario.DRY_WASTE));
        assertTrue(header.contains(MassValidationScenario.ENV_O2));
        assertTrue(header.contains(MassValidationScenario.ENV_CO2));
        assertTrue(header.contains(MassValidationScenario.ENV_N2));
        assertTrue(header.contains(MassValidationScenario.ENV_VAPOR));
        assertTrue(header.contains(MassValidationScenario.ENV_OTHER));
        assertTrue(header.contains(MassValidationScenario.CROP_STANDING_BIOMASS));
        assertTrue(header.contains(MassValidationScenario.CROP_SHELF_WATER));
        assertTrue(header.contains(MassValidationScenario.CREW_BODY_MASS));
        assertTrue(header.contains("residual_kg"));
    }
}
