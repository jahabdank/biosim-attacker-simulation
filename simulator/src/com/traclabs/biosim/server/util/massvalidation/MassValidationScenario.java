package com.traclabs.biosim.server.util.massvalidation;

import com.traclabs.biosim.server.framework.BioDriver;
import com.traclabs.biosim.server.framework.BiosimInitializer;
import com.traclabs.biosim.server.framework.IBioModule;
import com.traclabs.biosim.server.simulation.crew.CrewGroup;
import com.traclabs.biosim.server.simulation.environment.SimEnvironment;
import com.traclabs.biosim.server.simulation.food.BiomassPS;
import com.traclabs.biosim.server.simulation.food.BiomassStore;
import com.traclabs.biosim.server.simulation.food.FoodStore;
import com.traclabs.biosim.server.simulation.food.Shelf;
import com.traclabs.biosim.server.simulation.waste.DryWasteStore;
import com.traclabs.biosim.server.simulation.water.DirtyWaterStore;
import com.traclabs.biosim.server.simulation.water.GreyWaterStore;
import com.traclabs.biosim.server.simulation.water.PotableWaterStore;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

public final class MassValidationScenario {
    public static final String POTABLE_WATER = "potable_water";
    public static final String GREY_WATER = "grey_water";
    public static final String DIRTY_WATER = "dirty_water";
    public static final String FOOD_STORE = "food_store";
    public static final String BIOMASS_STORE = "biomass_store";
    public static final String DRY_WASTE = "dry_waste";
    public static final String ENV_O2 = "env_o2";
    public static final String ENV_CO2 = "env_co2";
    public static final String ENV_N2 = "env_n2";
    public static final String ENV_VAPOR = "env_vapor";
    public static final String ENV_OTHER = "env_other";
    public static final String CROP_STANDING_BIOMASS = "crop_standing_biomass";
    public static final String CROP_SHELF_WATER = "crop_shelf_water";
    public static final String CREW_BODY_MASS = "crew_body_mass";

    private static final AtomicInteger NEXT_SIM_ID = new AtomicInteger(10_000);

    private MassValidationScenario() {
    }

    public static MassLedger runScenario(Path xmlPath, int nTicks, Path outputDir,
            Map<String, Boolean> compartmentEnable) {
        int simID = NEXT_SIM_ID.getAndIncrement();
        try {
            String xml = Files.readString(xmlPath, StandardCharsets.UTF_8);
            BiosimInitializer initializer = BiosimInitializer.getInstance(simID);
            initializer.parseXmlConfiguration(xml);
            BioDriver bioDriver = initializer.getBioDriver();

            PotableWaterStore potableWater = module(initializer, "Potable_Water_Store", PotableWaterStore.class);
            GreyWaterStore greyWater = module(initializer, "Grey_Water_Store", GreyWaterStore.class);
            DirtyWaterStore dirtyWater = module(initializer, "Dirty_Water_Store", DirtyWaterStore.class);
            FoodStore foodStore = module(initializer, "Food_Store", FoodStore.class);
            BiomassStore biomassStore = module(initializer, "Biomass_Store", BiomassStore.class);
            DryWasteStore dryWasteStore = module(initializer, "Dry_Waste_Store", DryWasteStore.class);
            SimEnvironment env = module(initializer, "Crew_Quarters_Environment", SimEnvironment.class);
            BiomassPS biomassPS = module(initializer, "BiomassPS", BiomassPS.class);
            CrewGroup crewGroup = module(initializer, "Crew_Quarters_Group", CrewGroup.class);

            MassLedger ledger = new MassLedger(outputDir.resolve("ledger.csv"), outputDir.resolve("summary.json"));
            ledger.setScenario("MassValidationInit");
            ledger.setTickLengthHours(bioDriver.getTickLength());
            ledger.setModules(moduleNames(bioDriver));
            ledger.addNote("Accounted external terms are intentionally empty: the scenario wires stores, atmosphere, crew body-mass accumulator, crop standing biomass, and crop shelf water inside the tracked boundary.");
            ledger.addNote("Crew body mass is a conservation accumulator from actual per-tick BioSim flows, not a biological body-mass model.");
            ledger.addNote("Food consumed is read from CrewGroup.getFoodMassConsumed() because CrewPerson.getFoodConsumed() exposes calories, not kg, and FoodConsumerDefinition.actualFlowRates are cumulative in current BioSim.");
            ledger.addNote("Dry-waste flow is read from CrewGroup.getDryWasteProduced(), which sums the per-person simulated dry-waste flow produced during each BioDriver tick.");
            ledger.addNote("crop_shelf_water tracks water buffered inside BiomassPS shelves after gatherWater(); without it, water moved out of stores before plant uptake would appear as unaccounted drift.");
            ledger.addNote("PowerStore and PowerPS are included to satisfy BiomassPS power needs but excluded from mass accounting because power is energy, not mass.");

            addCompartment(ledger, compartmentEnable, POTABLE_WATER,
                    () -> potableWater.getCurrentLevel() * MassConstants.WATER_KG_PER_LITER);
            addCompartment(ledger, compartmentEnable, GREY_WATER,
                    () -> greyWater.getCurrentLevel() * MassConstants.WATER_KG_PER_LITER);
            addCompartment(ledger, compartmentEnable, DIRTY_WATER,
                    () -> dirtyWater.getCurrentLevel() * MassConstants.WATER_KG_PER_LITER);
            addCompartment(ledger, compartmentEnable, FOOD_STORE, foodStore::getCurrentLevel);
            addCompartment(ledger, compartmentEnable, BIOMASS_STORE, biomassStore::getCurrentLevel);
            addCompartment(ledger, compartmentEnable, DRY_WASTE, dryWasteStore::getCurrentLevel);
            addCompartment(ledger, compartmentEnable, ENV_O2,
                    () -> env.getO2Store().getCurrentLevel() * MassConstants.M_O2_KG_PER_MOL);
            addCompartment(ledger, compartmentEnable, ENV_CO2,
                    () -> env.getCO2Store().getCurrentLevel() * MassConstants.M_CO2_KG_PER_MOL);
            addCompartment(ledger, compartmentEnable, ENV_N2,
                    () -> env.getNitrogenStore().getCurrentLevel() * MassConstants.M_N2_KG_PER_MOL);
            addCompartment(ledger, compartmentEnable, ENV_VAPOR,
                    () -> env.getVaporStore().getCurrentLevel() * MassConstants.M_H2O_KG_PER_MOL);
            addCompartment(ledger, compartmentEnable, ENV_OTHER,
                    () -> env.getOtherStore().getCurrentLevel() * MassConstants.M_AR_KG_PER_MOL);
            addCompartment(ledger, compartmentEnable, CROP_STANDING_BIOMASS,
                    () -> Arrays.stream(biomassPS.getShelves())
                            .mapToDouble(shelf -> shelf.getPlant().getCurrentTotalWetBiomass()).sum());
            addCompartment(ledger, compartmentEnable, CROP_SHELF_WATER,
                    () -> Arrays.stream(biomassPS.getShelves())
                            .mapToDouble(shelf -> shelf.getWaterLevel() * MassConstants.WATER_KG_PER_LITER).sum());
            addCompartment(ledger, compartmentEnable, CREW_BODY_MASS, new CrewBodyMassSnapshotter(crewGroup));

            bioDriver.reset();
            ledger.setSimulationTicks(bioDriver.getTicks());
            ledger.recordTick(0);
            for (int tick = 1; tick <= nTicks; tick++) {
                bioDriver.advanceOneTick();
                if (bioDriver.getTicks() != tick) {
                    throw new IllegalStateException("BioDriver did not advance the production simulation: expected "
                            + tick + " ticks but got " + bioDriver.getTicks());
                }
                ledger.setSimulationTicks(bioDriver.getTicks());
                ledger.recordTick(tick);
            }
            return ledger;
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        } finally {
            BiosimInitializer.deleteInstance(simID);
        }
    }

    private static void addCompartment(MassLedger ledger, Map<String, Boolean> enabled, String key,
            CompartmentSnapshotter snapshotter) {
        if (enabled == null || enabled.getOrDefault(key, true)) {
            ledger.addCompartment(key, snapshotter);
        }
    }

    private static <T> T module(BiosimInitializer initializer, String name, Class<T> type) {
        IBioModule module = initializer.getModule(name);
        if (module == null) {
            throw new IllegalStateException("Required module not found: " + name);
        }
        if (!type.isInstance(module)) {
            throw new IllegalStateException("Module " + name + " is " + module.getClass().getName()
                    + ", expected " + type.getName());
        }
        return type.cast(module);
    }

    private static List<String> moduleNames(BioDriver bioDriver) {
        return Arrays.stream(bioDriver.getModules())
                .map(IBioModule::getModuleName)
                .sorted(Comparator.naturalOrder())
                .toList();
    }

    private static double sum(float[] values) {
        double total = 0.0;
        for (float value : values) {
            total += value;
        }
        return total;
    }

    private static final class CrewBodyMassSnapshotter implements CompartmentSnapshotter {
        private final CrewGroup crewGroup;
        private double crewBodyMassKg = 0.0;

        private CrewBodyMassSnapshotter(CrewGroup crewGroup) {
            this.crewGroup = crewGroup;
        }

        @Override
        public double snapshotKg() {
            double foodConsumedKg = crewGroup.getFoodMassConsumed();
            double potableWaterConsumedKg = sum(crewGroup.getPotableWaterConsumerDefinition().getActualFlowRates())
                    * MassConstants.WATER_KG_PER_LITER;
            double o2ConsumedKg = crewGroup.getO2Consumed() * MassConstants.M_O2_KG_PER_MOL;

            double co2ProducedKg = crewGroup.getCO2Produced() * MassConstants.M_CO2_KG_PER_MOL;
            double vaporProducedKg = crewGroup.getVaporProduced() * MassConstants.M_H2O_KG_PER_MOL;
            double greyWaterProducedKg = sum(crewGroup.getGreyWaterProducerDefinition().getActualFlowRates())
                    * MassConstants.WATER_KG_PER_LITER;
            double dirtyWaterProducedKg = sum(crewGroup.getDirtyWaterProducerDefinition().getActualFlowRates())
                    * MassConstants.WATER_KG_PER_LITER;
            double dryWasteProducedKg = crewGroup.getDryWasteProduced();

            crewBodyMassKg += (foodConsumedKg + potableWaterConsumedKg + o2ConsumedKg)
                    - (co2ProducedKg + vaporProducedKg + greyWaterProducedKg + dirtyWaterProducedKg
                    + dryWasteProducedKg);
            return crewBodyMassKg;
        }
    }
}
