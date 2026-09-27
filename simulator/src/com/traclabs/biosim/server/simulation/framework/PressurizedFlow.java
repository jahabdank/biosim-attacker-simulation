package com.traclabs.biosim.server.simulation.framework;

/**
 * Gas inject from tank ΔP. XML desired/max stay hourly nameplate caps;
 * the physical flow is k * max(0, P_tank − P_dest). k is mol/h per kPa.
 * When the tank is well above cabin pressure the nameplate binds; when
 * ΔP collapses the inject rate falls with it.
 */
public final class PressurizedFlow {
    /** mol/h per kPa of driving ΔP. High-pressure cylinder through a metering valve. */
    public static final float K_MOL_PER_HOUR_PER_KPA = 0.1f;

    private PressurizedFlow() {
    }

    public static float molesThisTick(float tankPressureKpa, float destPressureKpa,
                                      float hourlyCap, float tickLengthHours) {
        if (hourlyCap <= 0f || tickLengthHours <= 0f)
            return 0f;
        float dP = tankPressureKpa - destPressureKpa;
        if (dP <= 0f)
            return 0f;
        float physicalHourly = K_MOL_PER_HOUR_PER_KPA * dP;
        float hourly = Math.min(hourlyCap, physicalHourly);
        return hourly * tickLengthHours;
    }
}
