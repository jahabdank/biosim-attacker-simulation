package com.traclabs.biosim.server.util.massvalidation;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class MassLedgerUnitTest {
    @TempDir
    Path tempDir;

    @Test
    void computesResidualAndWritesCsv() throws Exception {
        AtomicReference<Double> level = new AtomicReference<>(10.0);
        MassLedger ledger = new MassLedger(tempDir.resolve("ledger.csv"), tempDir.resolve("summary.json"));
        ledger.addCompartment("store", level::get);

        ledger.recordTick(0);
        level.set(10.5);
        ledger.recordTick(1);

        MassLedger.ValidationResult result = ledger.validate(MassConstants.TOL_ABS_KG);

        assertFalse(result.passed);
        assertEquals(0.5, result.maxAbsResidual, 1.0e-12);
        assertTrue(Files.readString(ledger.getCsvPath()).contains("residual_kg"));
        assertEquals(2, ledger.getRowCount());
    }

    @Test
    void accountedTermCanBalanceDrift() {
        AtomicReference<Double> level = new AtomicReference<>(10.0);
        MassLedger ledger = new MassLedger(tempDir.resolve("balanced.csv"), tempDir.resolve("balanced.json"));
        ledger.addCompartment("store", level::get);
        ledger.addAccountedTerm("known_source", tick -> tick == 0 ? 0.0 : 0.5, "synthetic known source");

        ledger.recordTick(0);
        level.set(10.5);
        ledger.recordTick(1);

        MassLedger.ValidationResult result = ledger.validate(MassConstants.TOL_ABS_KG);

        assertTrue(result.passed);
        assertEquals(0.0, result.maxAbsResidual, 1.0e-12);
    }
}
