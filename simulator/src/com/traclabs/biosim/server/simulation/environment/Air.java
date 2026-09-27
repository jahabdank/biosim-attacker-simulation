package com.traclabs.biosim.server.simulation.environment;

public final class Air {
    private static final long serialVersionUID = 1L;
    public float o2Moles;
    public float co2Moles;
    public float otherMoles;
    public float vaporMoles;
    public float nitrogenMoles;
    /** Celsius of this slug. Default matches SimEnvironment initial T. */
    public float temperatureC = 23f;

    public Air() {
    }

    public float totalMoles() {
        return o2Moles + co2Moles + otherMoles + vaporMoles + nitrogenMoles;
    }

    public Air(float o2Moles, float co2Moles, float otherMoles, float vaporMoles, float nitrogenMoles) {
        this.o2Moles = o2Moles;
        this.co2Moles = co2Moles;
        this.otherMoles = otherMoles;
        this.vaporMoles = vaporMoles;
        this.nitrogenMoles = nitrogenMoles;
    }
}
