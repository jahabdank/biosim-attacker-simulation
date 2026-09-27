package com.traclabs.biosim.server.simulation.environment;

import com.traclabs.biosim.server.framework.Malfunction;
import com.traclabs.biosim.server.framework.MalfunctionIntensity;
import com.traclabs.biosim.server.framework.MalfunctionLength;
import com.traclabs.biosim.server.simulation.framework.SimBioModule;
import com.traclabs.biosim.server.simulation.water.DirtyWaterProducer;
import com.traclabs.biosim.server.simulation.water.DirtyWaterProducerDefinition;

/**
 * The basic Dehumidifier implementation.
 *
 * @author Scott Bell
 */
public class Dehumidifier extends SimBioModule implements AirConsumer, DirtyWaterProducer {

    // Cabin XML holds ~1 % H₂O. 0.52 never condensed. CCAA target ~2 %.
    public static final float OPTIMAL_MOISTURE_CONCENTRATION = 0.02f;
    public static final float T_HX_C = 10f;
    public static final float UA_W_PER_K = 20f;
    public static final float H_FG_J_PER_MOL = 44100f;

    // Consumers, Producers
    private final AirConsumerDefinition myAirConsumerDefinition;
    private final DirtyWaterProducerDefinition myDirtyWaterProducerDefinition;

    // 1.0 = fully operational, 0.0 = completely non-operational
    private float operationalEfficiency = 1.0f;

    public Dehumidifier(int pID, String pName) {
        super(pID, pName);
        myAirConsumerDefinition = new AirConsumerDefinition(this);
        myDirtyWaterProducerDefinition = new DirtyWaterProducerDefinition(this);
    }

    public Dehumidifier() {
        this(0, "Unnamed Dehumidifier");
    }

    private static float calculateMolesNeededToRemove(SimEnvironment pEnvironment) {
        float currentWaterMolesInEnvironment = pEnvironment.getVaporStore().getCurrentLevel();
        float totalMolesInEnvironment = pEnvironment.getTotalMoles();
        if ((currentWaterMolesInEnvironment / totalMolesInEnvironment) > OPTIMAL_MOISTURE_CONCENTRATION) {
            float waterMolesAtOptimalConcentration =
                    ((totalMolesInEnvironment - currentWaterMolesInEnvironment) * OPTIMAL_MOISTURE_CONCENTRATION)
                    / (1 - OPTIMAL_MOISTURE_CONCENTRATION);
            return currentWaterMolesInEnvironment - waterMolesAtOptimalConcentration;
        }
        return 0f;
    }

    private static float waterMolesToLiters(float pMoles) {
        return (pMoles * 18.01524f) / 1000f; // 1000g/liter, 18.01524g/mole
    }

    static float dewPointC(float temperatureC, float yH2O, float totalPressureKpa) {
        if (yH2O <= 0f || totalPressureKpa <= 0f)
            return -100f;
        float pvHpa = yH2O * totalPressureKpa * 10f;
        if (pvHpa <= 0f)
            return -100f;
        double ln = Math.log(pvHpa / 6.112);
        return (float) (243.12 * ln / (17.62 - ln));
    }

    static float saturationVaporPressureHpa(float temperatureC) {
        return 6.112f * (float) Math.exp(17.62 * temperatureC / (243.12 + temperatureC));
    }

    static float molesToCondense(float temperatureC, float yH2O, float totalMoles,
                                 float totalPressureKpa, float tickLengthHours, float ua, float efficiency) {
        if (totalMoles <= 0f || yH2O <= 0f || tickLengthHours <= 0f || efficiency <= 0f)
            return 0f;
        if (dewPointC(temperatureC, yH2O, totalPressureKpa) <= T_HX_C)
            return 0f;
        float esHpa = saturationVaporPressureHpa(T_HX_C);
        float pHpa = totalPressureKpa * 10f;
        if (pHpa <= 0f)
            return 0f;
        float ySat = esHpa / pHpa;
        if (ySat >= 1f)
            return 0f;
        float vapor = yH2O * totalMoles;
        float dry = totalMoles - vapor;
        float vaporAtSat = ySat / (1f - ySat) * dry;
        float excess = vapor - vaporAtSat;
        if (excess <= 0f)
            return 0f;
        float qHx = ua * Math.max(0f, temperatureC - T_HX_C) * efficiency;
        float uaLimit = qHx * tickLengthHours * 3600f / H_FG_J_PER_MOL;
        return Math.min(excess, Math.max(0f, uaLimit));
    }

    private float condenseOneNode(SimEnvironment env, int i) {
        float desiredHourly = myAirConsumerDefinition.getDesiredFlowRate(i) * operationalEfficiency;
        if (desiredHourly <= 0f) {
            myAirConsumerDefinition.getActualFlowRates()[i] = 0f;
            return 0f;
        }
        float qHx = UA_W_PER_K * Math.max(0f, env.getTemperature() - T_HX_C) * operationalEfficiency;
        env.addHeatWatts(-qHx);
        float total = env.getTotalMoles();
        float y = total > 0f ? env.getVaporStore().getCurrentLevel() / total : 0f;
        float molesNeeded = molesToCondense(env.getTemperature(), y, total,
                env.getTotalPressure(), getTickLength(), UA_W_PER_K, operationalEfficiency);
        if (molesNeeded <= 0f) {
            myAirConsumerDefinition.getActualFlowRates()[i] = 0f;
            return 0f;
        }
        float tick = getTickLength();
        float cap = Math.min(molesNeeded, myAirConsumerDefinition.getMaxFlowRate(i) * tick);
        float taken = env.getVaporStore().take(Math.min(cap, desiredHourly * tick));
        myAirConsumerDefinition.getActualFlowRates()[i] = taken;
        return taken;
    }

    public AirConsumerDefinition getAirConsumerDefinition() {
        return myAirConsumerDefinition;
    }

    public DirtyWaterProducerDefinition getDirtyWaterProducerDefinition() {
        return myDirtyWaterProducerDefinition;
    }

    @Override
    public void tick() {
        super.tick();
        dehumidifyEnvironments();
    }

    private void dehumidifyEnvironments() {
        if (myLogger.isDebugEnabled()) {
            float beforeWater = myAirConsumerDefinition.getEnvironments()[0].getVaporStore().getCurrentLevel();
            float beforeTotal = myAirConsumerDefinition.getEnvironments()[0].getTotalMoles();
            myLogger.debug("Before: Water concentration " + (beforeWater / beforeTotal));
        }

        float molesOfWaterGathered = 0f;
        for (int i = 0; i < myAirConsumerDefinition.getEnvironments().length; i++) {
            SimEnvironment env = myAirConsumerDefinition.getEnvironments()[i];
            if (env.isOneNodeThermal()) {
                molesOfWaterGathered += condenseOneNode(env, i);
                continue;
            }
            float molesNeededToRemove = calculateMolesNeededToRemove(env);
            if (molesNeededToRemove > 0) {
                float tick = getTickLength();
                float resourceToGatherFirst = Math.min(molesNeededToRemove, myAirConsumerDefinition.getMaxFlowRate(i) * tick);
                float desired = myAirConsumerDefinition.getDesiredFlowRate(i) * operationalEfficiency * tick;
                float resourceToGatherFinal = Math.min(resourceToGatherFirst, desired);

                float taken = myAirConsumerDefinition.getEnvironments()[i]
                        .getVaporStore().take(resourceToGatherFinal);
                myAirConsumerDefinition.getActualFlowRates()[i] = taken;
                molesOfWaterGathered += taken;
            }
        }

        float waterPushedToStore = myDirtyWaterProducerDefinition
                .pushResourceToStores(waterMolesToLiters(molesOfWaterGathered));

        if (myLogger.isDebugEnabled()) {
            float afterWater = myAirConsumerDefinition.getEnvironments()[0].getVaporStore().getCurrentLevel();
            float afterTotal = myAirConsumerDefinition.getEnvironments()[0].getTotalMoles();
            myLogger.debug("After: Pushed " + waterPushedToStore
                    + " liters (gathered " + molesOfWaterGathered
                    + " moles), concentration now " + (afterWater / afterTotal));
        }
    }

    @Override
    protected void performMalfunctions() {
        if (!myMalfunctions.isEmpty()) {
            // Default to fully operational
            operationalEfficiency = 1.0f;

            // Get the most severe malfunction
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

            // Apply reduction based on intensity
            if (worstIntensity == MalfunctionIntensity.LOW_MALF) {
                operationalEfficiency = 0.75f;
            } else if (worstIntensity == MalfunctionIntensity.MEDIUM_MALF) {
                operationalEfficiency = 0.25f;
            } else if (worstIntensity == MalfunctionIntensity.SEVERE_MALF) {
                operationalEfficiency = 0.0f;
            }
        } else {
            // No malfunctions, fully operational
            operationalEfficiency = 1.0f;
        }
    }

    @Override
    public void reset() {
        super.reset();
        myAirConsumerDefinition.reset();
        myDirtyWaterProducerDefinition.reset();
        operationalEfficiency = 1.0f;
    }

    @Override
    public void log() {
        myLogger.debug("operational_efficiency=" + operationalEfficiency);
    }
}
