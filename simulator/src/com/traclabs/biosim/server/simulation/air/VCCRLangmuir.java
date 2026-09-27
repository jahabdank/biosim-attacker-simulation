package com.traclabs.biosim.server.simulation.air;

import com.traclabs.biosim.server.framework.Malfunction;
import com.traclabs.biosim.server.framework.MalfunctionIntensity;
import com.traclabs.biosim.server.simulation.environment.Air;
import com.traclabs.biosim.server.simulation.environment.SimEnvironment;

/**
 * Opt-in lumped two-state CO2 removal (XML implementation="LANGMUIR").
 * Adsorb: volumetric blower, Langmuir in y_CO2, CO2 held in an internal bed.
 * Desorb: return air without stripping; dump the bed over the half-cycle.
 * Power desired is watts this tick (0 = off). Optional ppCo2SetpointMmHg
 * holds cabin ppCO2 when power is on; omitted = run whenever powered.
 */
public class VCCRLangmuir extends AbstractVCCR {

    static final float HALF_CYCLE_HOURS = 2f;
    /** Blower volumetric flow at adsorb nameplate power. Liters/hour. */
    static final float Q_REF_LITERS_PER_HOUR = 80000f;
    static final float W_ADSORB_WATTS = 400f;
    static final float W_DESORB_WATTS = 1200f;
    static final float LANGMUIR_ALPHA = 0.85f;
    static final float LANGMUIR_BETA = 80f;
    /** Do not take cabin y_CO2 below this mole fraction (600 ppm). */
    static final float Y_CO2_FLOOR = 6.0e-4f;
    private static final float R_KPA_LITERS = 8.314f;

    enum BedState {
        ADSORB, DESORB
    }

    private float currentCO2Produced = 0f;
    private float currentPowerConsumed = 0f;
    private float operationalEfficiency = 1.0f;
    private float bedInventoryMoles = 0f;
    private float hoursInState = 0f;
    private float desorbDumpRateMolPerHour = 0f;
    private BedState bedState;
    /** NaN = no ppCO2 controller; run whenever power desired > 0. */
    private float ppCo2SetpointMmHg = Float.NaN;

    public VCCRLangmuir(int pID, String pName) {
        super(pID, pName);
        bedState = initialState(pName);
    }

    public void setPpCo2SetpointMmHg(float mmHg) {
        ppCo2SetpointMmHg = mmHg;
    }

    static BedState initialState(String pName) {
        if (pName != null && pName.toLowerCase().contains("backup"))
            return BedState.DESORB;
        return BedState.ADSORB;
    }

    /**
     * Air processed this tick. Same ideal-gas form as Fan: n = Q P/(R T) * tickLength.
     * Q scales with power received versus adsorb nameplate. Zero watts moves no air.
     */
    static float molesAirThisTick(float powerWatts, float pressureKpa,
                                  float temperatureKelvin, float tickLengthHours) {
        if (powerWatts <= 0f || pressureKpa <= 0f || temperatureKelvin <= 0f
                || tickLengthHours <= 0f)
            return 0f;
        float q = Q_REF_LITERS_PER_HOUR * (powerWatts / W_ADSORB_WATTS);
        float molesPerHour = q * pressureKpa / (R_KPA_LITERS * temperatureKelvin);
        return molesPerHour * tickLengthHours;
    }

    /**
     * CO2 moles removed from a slug. Langmuir in mole fraction, clamped so the
     * returned air does not go below Y_CO2_FLOOR.
     */
    static float co2RemovedFromSlug(float nAir, float nCo2InSlug) {
        if (nAir <= 0f || nCo2InSlug <= 0f)
            return 0f;
        float y = nCo2InSlug / nAir;
        if (y <= Y_CO2_FLOOR)
            return 0f;
        float langmuir = nAir * y * LANGMUIR_ALPHA / (1f + LANGMUIR_BETA * y);
        float floorLeave = Y_CO2_FLOOR * nAir;
        float maxTake = nCo2InSlug - floorLeave;
        if (maxTake <= 0f)
            return 0f;
        return Math.min(langmuir, maxTake);
    }

    static float powerNeededWatts(BedState state) {
        return state == BedState.DESORB ? W_DESORB_WATTS : W_ADSORB_WATTS;
    }

    /** ppCO2 in mmHg from the cabin the unit draws. */
    static float ppCo2MmHg(SimEnvironment env) {
        if (env == null)
            return 0f;
        return env.getCO2Store().getPressure() * 7.500616827f;
    }

    public void tick() {
        super.tick();
        gatherPower();
        gatherAndPushAir();
        dumpBedIfDesorbing();
        advanceCycle();
    }

    private void gatherPower() {
        float commanded = 0f;
        if (myPowerConsumerDefinition.getDesiredFlowRates().length > 0)
            commanded = myPowerConsumerDefinition.getDesiredFlowRate(0);
        SimEnvironment src = null;
        SimEnvironment[] sources = myAirConsumerDefinition.getEnvironments();
        if (sources != null && sources.length > 0)
            src = sources[0];
        boolean finishDesorb = bedState == BedState.DESORB && bedInventoryMoles > 0f;
        if (operationalEfficiency <= 0f) {
            currentPowerConsumed = 0f;
            return;
        }
        if (commanded <= 0f && !finishDesorb) {
            currentPowerConsumed = 0f;
            return;
        }
        boolean holdSetpoint = !Float.isNaN(ppCo2SetpointMmHg) && ppCo2SetpointMmHg > 0f;
        if (holdSetpoint && commanded > 0f && !finishDesorb
                && ppCo2MmHg(src) <= ppCo2SetpointMmHg) {
            currentPowerConsumed = 0f;
            return;
        }
        float need = powerNeededWatts(bedState) * operationalEfficiency;
        currentPowerConsumed = myPowerConsumerDefinition.takeAmount(need);
    }

    private void gatherAndPushAir() {
        currentCO2Produced = 0f;
        if (currentPowerConsumed <= 0f)
            return;
        SimEnvironment[] sources = myAirConsumerDefinition.getEnvironments();
        if (sources == null || sources.length < 1 || sources[0] == null)
            return;
        SimEnvironment src = sources[0];
        // Blower Q follows adsorb nameplate, not heater watts.
        float blowerWatts = Math.min(currentPowerConsumed, W_ADSORB_WATTS);
        float molesAir = molesAirThisTick(blowerWatts, src.getTotalPressure(),
                src.getTemperatureInKelvin(), getTickLength());
        Air airConsumed = myAirConsumerDefinition.getAirFromEnvironment(molesAir, 0);
        float nAir = airConsumed.o2Moles + airConsumed.co2Moles + airConsumed.nitrogenMoles
                + airConsumed.otherMoles + airConsumed.vaporMoles;
        if (bedState == BedState.ADSORB) {
            float removed = co2RemovedFromSlug(nAir, airConsumed.co2Moles);
            airConsumed.co2Moles -= removed;
            bedInventoryMoles += removed;
        }
        myAirProducerDefinition.pushAirToEnvironment(airConsumed, 0);
    }

    private void dumpBedIfDesorbing() {
        if (bedState != BedState.DESORB || currentPowerConsumed <= 0f)
            return;
        float heaterFrac = W_DESORB_WATTS > 0f
                ? Math.min(1f, currentPowerConsumed / W_DESORB_WATTS) : 0f;
        float dump = desorbDumpRateMolPerHour * getTickLength() * heaterFrac;
        if (dump > bedInventoryMoles)
            dump = bedInventoryMoles;
        if (dump <= 0f)
            return;
        bedInventoryMoles -= dump;
        currentCO2Produced = myCO2ProducerDefinition.pushResourceToStores(dump);
    }

    private void advanceCycle() {
        if (currentPowerConsumed <= 0f)
            return;
        hoursInState += getTickLength();
        if (hoursInState >= HALF_CYCLE_HOURS)
            switchState();
    }

    private void switchState() {
        if (bedState == BedState.ADSORB) {
            bedState = BedState.DESORB;
            desorbDumpRateMolPerHour = HALF_CYCLE_HOURS > 0f
                    ? bedInventoryMoles / HALF_CYCLE_HOURS : 0f;
        } else {
            if (bedInventoryMoles > 0f)
                currentCO2Produced += myCO2ProducerDefinition
                        .pushResourceToStores(bedInventoryMoles);
            bedInventoryMoles = 0f;
            desorbDumpRateMolPerHour = 0f;
            bedState = BedState.ADSORB;
        }
        hoursInState = 0f;
    }

    @Override
    protected void performMalfunctions() {
        if (myMalfunctions.size() > 0) {
            operationalEfficiency = 1.0f;
            MalfunctionIntensity worstIntensity = MalfunctionIntensity.LOW_MALF;
            for (Malfunction malfunction : myMalfunctions.values()) {
                if (malfunction.getIntensity().ordinal() > worstIntensity.ordinal()) {
                    worstIntensity = malfunction.getIntensity();
                }
                if (!malfunction.hasPerformed()) {
                    myLogger.debug("Performing malfunction: " + malfunction);
                    malfunction.setPerformed(true);
                }
            }
            if (worstIntensity == MalfunctionIntensity.LOW_MALF) {
                operationalEfficiency = 0.75f;
            } else if (worstIntensity == MalfunctionIntensity.MEDIUM_MALF) {
                operationalEfficiency = 0.25f;
            } else if (worstIntensity == MalfunctionIntensity.SEVERE_MALF) {
                operationalEfficiency = 0.0f;
            }
        } else {
            operationalEfficiency = 1.0f;
        }
    }

    public void reset() {
        super.reset();
        currentPowerConsumed = 0f;
        currentCO2Produced = 0f;
        operationalEfficiency = 1.0f;
        bedInventoryMoles = 0f;
        hoursInState = 0f;
        desorbDumpRateMolPerHour = 0f;
        bedState = initialState(getModuleName());
    }

    public void log() {
        myLogger.debug("power_consumed=" + currentPowerConsumed);
        myLogger.debug("operational_efficiency=" + operationalEfficiency);
        myLogger.debug("bed_inventory_mol=" + bedInventoryMoles);
    }

    BedState getBedState() {
        return bedState;
    }

    public float getBedInventoryMoles() {
        return bedInventoryMoles;
    }
}
