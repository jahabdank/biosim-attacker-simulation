package com.traclabs.biosim.integration;

import com.traclabs.biosim.server.framework.BioDriver;
import com.traclabs.biosim.server.framework.BiosimInitializer;
import com.traclabs.biosim.server.framework.IBioModule;
import com.traclabs.biosim.server.simulation.crew.CrewGroup;
import com.traclabs.biosim.server.simulation.crew.CrewPerson;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashSet;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertTrue;

class CrewTransferAtomicityIT {
    private static final Path XML = Path.of("configuration/test/CrewTransferInit.xml");
    private static final Set<String> ROSTER = Set.of("Crew1", "Crew2", "Crew3", "Crew4");

    @ParameterizedTest
    @ValueSource(ints = {801, 802, 803, 804, 805, 806})
    void everyCompletedTickRetainsExactlyOneMembershipPerPerson(int id) throws Exception {
        try {
            BiosimInitializer initializer = BiosimInitializer.getInstance(id);
            initializer.parseXmlConfiguration(Files.readString(XML));
            BioDriver driver = initializer.getBioDriver();
            CrewGroup base = (CrewGroup) BiosimInitializer.getModule(id, "BaseGroup");
            CrewGroup eva = (CrewGroup) BiosimInitializer.getModule(id, "EvaGroup");
            // Both iteration orders must commit transfers only after all groups tick.
            driver.setActiveSimModules(id % 2 == 0
                    ? new IBioModule[]{base, eva} : new IBioModule[]{eva, base});
            driver.reset();
            CrewPerson[] people = base.getCrewPeople();
            assertEquals(4, people.length);
            int departures = 0;
            int returns = 0;
            for (int tick = 1; tick <= 7200; tick++) {
                int[] nextActivityTimes = new int[people.length];
                for (int i = 0; i < people.length; i++) {
                    int elapsed = people[i].getTimeActivityPerformed() + 1;
                    nextActivityTimes[i] = elapsed >= people[i].getCurrentActivity().getTimeLength()
                            ? 0 : elapsed;
                }
                int previousEvaSize = eva.getCrewSize();
                driver.advanceTicks(1);
                assertEquals(tick, driver.getTicks());
                Set<String> names = new HashSet<>();
                for (IBioModule module : driver.getModules()) {
                    if (module instanceof CrewGroup group) {
                        for (CrewPerson person : group.getCrewPeople()) {
                            assertTrue(names.add(person.getName()), "Duplicate membership at tick " + tick);
                            assertSame(group, person.getCurrentCrewGroup(), "Group pointer at tick " + tick);
                        }
                    }
                }
                assertEquals(ROSTER, names, "Roster gap at tick " + tick + " in simulation " + id);
                for (int i = 0; i < people.length; i++) {
                    assertEquals(nextActivityTimes[i], people[i].getTimeActivityPerformed(),
                            "Person did not tick exactly once at tick " + tick);
                }
                if (eva.getCrewSize() > previousEvaSize)
                    departures++;
                if (eva.getCrewSize() < previousEvaSize)
                    returns++;
            }
            assertTrue(departures > 100, "Fixture did not repeatedly start EVA");
            assertTrue(returns > 100, "Fixture did not repeatedly end EVA");
        } finally {
            BiosimInitializer.deleteInstance(id);
        }
    }
}
