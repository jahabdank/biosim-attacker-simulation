package com.traclabs.biosim.server.simulation.framework;

import com.traclabs.biosim.server.simulation.environment.SimEnvironment;

/**
 * Lumped PCA: O2 injector holds ppO2 (desired is kPa), N2 injector holds
 * total P (desired is kPa). Desired 0 is inhibit. No vent.
 */
public final class PcaLaw {
    static final float PPO2_DEADBAND_KPA = 0.25f;
    static final float P_DEADBAND_KPA = 0.5f;
    static final float P_CEILING_ABOVE_SET_KPA = 2f;
    static final float PPO2_MIN_FOR_N2_KPA = 16f;

    private PcaLaw() {
    }

    public static float ppO2Kpa(SimEnvironment env) {
        if (env == null)
            return 0f;
        return env.getO2Store().getPressure();
    }

    public static boolean shouldInjectOxygen(SimEnvironment env, float ppO2SetKpa) {
        if (env == null || ppO2SetKpa <= 0f)
            return false;
        float p = env.getTotalPressure();
        float ppO2 = ppO2Kpa(env);
        if (ppO2 >= ppO2SetKpa - PPO2_DEADBAND_KPA)
            return false;
        return p < ppO2SetKpa + 40f;
    }

    public static boolean shouldInjectNitrogen(SimEnvironment env, float pSetKpa) {
        if (env == null || pSetKpa <= 0f)
            return false;
        float p = env.getTotalPressure();
        if (p >= pSetKpa - P_DEADBAND_KPA)
            return false;
        if (p >= pSetKpa + P_CEILING_ABOVE_SET_KPA)
            return false;
        return ppO2Kpa(env) >= PPO2_MIN_FOR_N2_KPA;
    }
}
