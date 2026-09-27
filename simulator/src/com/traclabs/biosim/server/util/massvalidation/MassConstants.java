package com.traclabs.biosim.server.util.massvalidation;

/**
 * Constants used by the BioSim humans + crops mass-accounting scenario.
 */
public final class MassConstants {
    public static final double M_O2_KG_PER_MOL = 0.0319988;
    public static final double M_CO2_KG_PER_MOL = 0.0440095;
    public static final double M_N2_KG_PER_MOL = 0.0280134;
    public static final double M_H2O_KG_PER_MOL = 0.01801528;
    public static final double M_AR_KG_PER_MOL = 0.039948;
    public static final double WATER_KG_PER_LITER = 0.99823;
    public static final double TOL_ABS_KG = 1.0e-2;
    public static final String TOL_ABS_JUSTIFICATION = "BioSim store levels are `float` (IEEE 754 single precision, ~7 decimal "
            + "digits). The largest compartment in this scenario is `potable_water`, "
            + "initialized at 10000 L \u2248 9982.3 kg. One ULP at 1e4 magnitude is "
            + "~1.2e-3 kg. Per-tick residual sums two such totals, so worst-case "
            + "floating-point round-off per tick is bounded by ~2.4e-3 kg. We pin "
            + "`TOL_ABS_KG = 1.0e-2` (about 4\u00d7 that bound) as a fixed ceiling that "
            + "covers documented `float` rounding only. Drift larger than this is by "
            + "definition not floating-point noise and MUST be attributed to a named "
            + "accounted term, not absorbed by widening the tolerance.";

    private MassConstants() {
    }
}
