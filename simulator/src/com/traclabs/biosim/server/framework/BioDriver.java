package com.traclabs.biosim.server.framework;

import com.traclabs.biosim.server.simulation.crew.CrewGroup;
import com.traclabs.biosim.server.simulation.food.BiomassPS;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/*
 *
 * @author Scott Bell
 */

public class BioDriver {
    // The ID of this instance of BioSim
    private final int myID;
    private final Logger myLogger;
    private final Map<String, IBioModule> myModuleMap = new HashMap<String, IBioModule>();
    // The thread to run the simulation
    private Thread myTickThread;
    // Flag to see whether the BioDriver is paused (started but not ticking)
    private boolean simulationIsPaused = false;
    // Flag to see whether the BioDriver is started at all
    private boolean simulationStarted = false;
    // Flag to see whether the BioDriver has ended due to meeting end criteria
    private boolean simulationEnded = false;
    // If <runTillN == true, this is the number of ticks to run for.
    private int nTicks = -1;
    // The number of ticks gone by
    private int ticksGoneBy;
    // Tells whether simulation runs until crew death
    private boolean runTillCrewDeath = false;
    // Tells whether simulation runs until plant death
    private boolean runTillPlantDeath = false;
    // Tells whether simulation runs till a fixed number of ticks
    // If <runTillN == true, this is the number of ticks to run for.
    private boolean runTillN = false;
    // How long BioDriver should pause between ticks
    private int myDriverStutterLength;
    private boolean exitWhenFinished = false;
    // If we loop after end conditions of a simulation run have been met (crew
    // death or n-ticks)
    private boolean looping = false;
    private CrewGroup[] crewsToWatch;

    private BiomassPS[] plantsToWatch;

    private IBioModule[] modules;

    private IBioModule[] activeSimModules;

    private IBioModule[] passiveSimModules;

    private IBioModule[] prioritySimModules;

    private IBioModule[] sensors;

    private IBioModule[] actuators;

    private float myTickLength = 1f;

    private final List<TickListener> tickListeners = new ArrayList<>();

    /**
     * Constructs the BioDriver
     *
     * @param pID The ID of this instance of the BioSim (must be the same for
     *            all modules in the instance)
     */
    public BioDriver(int pID) {
        myID = pID;
        modules = new IBioModule[0];
        activeSimModules = new IBioModule[0];
        passiveSimModules = new IBioModule[0];
        prioritySimModules = new IBioModule[0];
        sensors = new IBioModule[0];
        actuators = new IBioModule[0];
        crewsToWatch = new CrewGroup[0];
        plantsToWatch = new BiomassPS[0];
        myLogger = LoggerFactory.getLogger(BioDriver.class);
    }

    /**
     * Starts the simulation
     */
    public synchronized void startSimulation() {
        reset();
        simulationStarted = true;
        myTickThread = new Thread(new Ticker(), "Biosim Tick Thread");
        myTickThread.start();
        notifyAll();
    }

    /**
     * Returns the name of this instance of BioDriver
     *
     * @return The name of this instance (BioDriver + ID)
     */
    public String getName() {
        return "BioDriver";
    }

    /**
     * Checks to see if the simulation is paused.
     *
     * @return <code>true</code> if paused, <code>false</code> if not
     */
    public synchronized boolean isPaused() {
        return simulationIsPaused;
    }

    /**
     * Checks to see if the simulation has started.
     *
     * @return <code>true</code> if started, <code>false</code> if not
     */
    public synchronized boolean isStarted() {
        return simulationStarted;
    }

    /**
     * Checks to see if the simulation has ended due to meeting end criteria.
     *
     * @return <code>true</code> if ended, <code>false</code> if not
     */
    public synchronized boolean isEnded() {
        return simulationEnded;
    }

    /**
     * Tells The ID of this module. Should be the same as every other module in
     * this BioSim instance
     *
     * @return The ID of this module. Should be the same as every other module
     * in this BioSim instance
     */
    public int getID() {
        return myID;
    }

    /**
     * Simulation runs till all the crew dies if true.
     */
    public synchronized void setRunTillCrewDeath(boolean pRunTillDead) {
        runTillCrewDeath = pRunTillDead;
    }

    public synchronized void setExitWhenFinished(boolean exitWhenFinished) {
        this.exitWhenFinished = exitWhenFinished;
    }


    /**
     * Simulation runs till all the crew dies if true.
     */
    public synchronized void setRunTillPlantDeath(boolean pRunTillDead) {
        runTillPlantDeath = pRunTillDead;
    }

    public IBioModule[] getModules() {
        return modules;
    }

    public void setModules(IBioModule[] pModules) {
        modules = pModules;
        for (IBioModule module : pModules) {
            myModuleMap.put(module.getModuleName(), module);
        }
    }

    public IBioModule[] getSensors() {
        return sensors;
    }

    public void setSensors(IBioModule[] pSensors) {
        sensors = pSensors;
    }

    public IBioModule[] getActiveSimModules() {
        return activeSimModules;
    }

    public void setActiveSimModules(IBioModule[] pSimModules) {
        activeSimModules = pSimModules;
    }

    public IBioModule[] getPassiveSimModules() {
        return passiveSimModules;
    }

    public void setPassiveSimModules(IBioModule[] pSimModules) {
        passiveSimModules = pSimModules;
    }

    public IBioModule[] getPrioritySimModules() {
        return prioritySimModules;
    }

    public void setPrioritySimModules(IBioModule[] pSimModules) {
        prioritySimModules = pSimModules;
    }

    public IBioModule[] getActuators() {
        return actuators;
    }

    public void setActuators(IBioModule[] pActuators) {
        actuators = pActuators;
    }

    public IBioModule[] getSimModules() {
        IBioModule[] simModules = new IBioModule[activeSimModules.length
                + passiveSimModules.length + prioritySimModules.length];
        System.arraycopy(activeSimModules, 0, simModules, 0, activeSimModules.length);
        System.arraycopy(passiveSimModules, 0, simModules, activeSimModules.length, passiveSimModules.length);
        for (int i = 0; i < prioritySimModules.length; i++)
            simModules[i + activeSimModules.length + passiveSimModules.length] = prioritySimModules[i];
        return simModules;
    }

    public String[] getModuleNames() {
        String[] moduleNameArray = new String[modules.length];
        for (int i = 0; i < moduleNameArray.length; i++)
            moduleNameArray[i] = modules[i].getModuleName();
        return moduleNameArray;
    }

    public String[] getSensorNames() {
        String[] sensorNameArray = new String[sensors.length];
        for (int i = 0; i < sensorNameArray.length; i++)
            sensorNameArray[i] = sensors[i].getModuleName();
        return sensorNameArray;
    }

    public String[] getActuatorNames() {
        String[] actuatorNameArray = new String[actuators.length];
        for (int i = 0; i < actuatorNameArray.length; i++)
            actuatorNameArray[i] = actuators[i].getModuleName();
        return actuatorNameArray;
    }

    public String[] getActiveSimModuleNames() {
        String[] simModuleNameArray = new String[activeSimModules.length];
        for (int i = 0; i < simModuleNameArray.length; i++)
            simModuleNameArray[i] = activeSimModules[i].getModuleName();
        return simModuleNameArray;
    }

    public String[] getPassiveSimModuleNames() {
        String[] simModuleNameArray = new String[passiveSimModules.length];
        for (int i = 0; i < simModuleNameArray.length; i++)
            simModuleNameArray[i] = passiveSimModules[i].getModuleName();
        return simModuleNameArray;
    }

    public String[] getPrioritySimModuleNames() {
        String[] simModuleNameArray = new String[prioritySimModules.length];
        for (int i = 0; i < simModuleNameArray.length; i++)
            simModuleNameArray[i] = prioritySimModules[i].getModuleName();
        return simModuleNameArray;
    }

    public String[] getSimModuleNames() {
        IBioModule[] simModules = getSimModules();
        String[] simModuleNameArray = new String[simModules.length];
        for (int i = 0; i < simModules.length; i++)
            simModuleNameArray[i] = simModules[i].getModuleName();
        return simModuleNameArray;
    }

    public void setCrewsToWatch(CrewGroup[] pCrewGroups) {
        crewsToWatch = pCrewGroups;
    }

    public void setPlantsToWatch(BiomassPS[] pPlants) {
        plantsToWatch = pPlants;
    }

    /**
     * Simulation runs till n ticks.
     *
     * @param pTicks ticks to run simulation
     */
    public synchronized void setRunTillN(int pTicks) {
        nTicks = pTicks;
        if (nTicks > 0)
            runTillN = true;
    }

    /**
     * If n-ticks have been reached or the crew is dead, the simulation restarts
     */
    public synchronized void setLoopSimulation(boolean pLooping) {
        looping = pLooping;
    }

    public synchronized void setPauseSimulation(boolean pPaused) {
        simulationIsPaused = pPaused;
        notifyAll();
    }

    /**
     * Tells how long the simulation pauses between full simulation ticks.
     *
     * @return How long the simulation pauses between full simulation ticks.
     */
    public int getDriverStutterLength() {
        return myDriverStutterLength;
    }

    /**
     * Sets how long BioDriver should pause between full simulation ticks (e.g.,
     * tick all modules, wait, tick all modules, wait, etc.)
     *
     * @param pDriverStutterLength the length (in milliseconds) for the driver to pause between
     *                             ticks
     */
    public synchronized void setDriverStutterLength(int pDriverStutterLength) {
        if (pDriverStutterLength > 0)
            myLogger.debug("BioDriver" + myID + ": driver pause of "
                    + pDriverStutterLength + " milliseconds");
        myDriverStutterLength = pDriverStutterLength;
    }

    /**
     * Tells whether BioDriver is looping the simulation after end conditions
     * have been met.
     *
     * @return Whether BioDriver is looping the simulation after end conditions
     * have been met.
     */
    public synchronized boolean isLooping() {
        return looping;
    }

    /**
     * Tells whether BioDriver should loop the simulation after end conditions
     * have been met.
     *
     * @param pLoop Whether BioDriver should loop the simulation after end
     *              conditions have been met.
     */
    public synchronized void setLooping(boolean pLoop) {
        looping = pLoop;
    }

    /**
     * Tells whether the simulation has met an end condition and has stopped.
     *
     * @return Whether the simulation has met an end condition and has stopped.
     */
    public synchronized boolean isDone() {
        if (runTillN) {
            if (ticksGoneBy >= nTicks) {
                myLogger.info("BioDriver" + myID
                        + ": Reached user defined tick limit of " + nTicks);
                return true;
            }
        }
        if (runTillCrewDeath) {
            for (int i = 0; i < crewsToWatch.length; i++) {
                if (crewsToWatch[i].anyDead()) {
                    myLogger.info("BioDriver" + myID
                            + ": simulation ended due to crew death at "
                            + ticksGoneBy);
                    return true;
                }
            }
        }
        if (runTillPlantDeath) {
            for (int i = 0; i < plantsToWatch.length; i++) {
                if (plantsToWatch[i].isAnyPlantDead()) {
                    myLogger.info("BioDriver" + myID
                            + ": simulation ended due to plant death at "
                            + ticksGoneBy);
                    return true;

                }
            }
        }
        return false;
    }

    /**
     * Tells the number of times BioDriver has ticked the simulation
     *
     * @return The number of times BioDriver has ticked the simulation
     */
    public synchronized int getTicks() {
        return ticksGoneBy;
    }

    /**
     * Ends the simulation entirely.
     */
    public synchronized void endSimulation() {
        myTickThread = null;
        simulationStarted = false;
        simulationEnded = true;
        notifyAll();
        myLogger.info("BioDriver" + myID + ": simulation ended on tick "
                + ticksGoneBy);
        if (exitWhenFinished)
            System.exit(0);
    }

    /**
     * Pauses automatic execution and advances one tick unless the simulation has ended.
     */
    public synchronized void advanceOneTick() {
        advanceTicks(1);
    }

    /**
     * Advance n ticks while paused. Lets a REST client batch ticks in one
     * request instead of posting /tick once per tick. Ended simulations do not
     * advance until reset or restarted; unstarted fixtures may be stepped directly.
     */
    public synchronized void advanceTicks(int n) {
        if (n < 1 || simulationEnded)
            return;
        if (!simulationIsPaused)
            setPauseSimulation(true);
        if (isDone()) {
            endSimulation();
            return;
        }
        for (int i = 0; i < n; i++) {
            tick();
            if (simulationEnded)
                return;
            if (isDone()) {
                endSimulation();
                return;
            }
        }
    }

    /**
     * Starts a malfunction on every module
     *
     * @param pIntensity The intensity of the malfunction <br>
     *                   Options are: <br>
     *                   &nbsp;&nbsp;&nbsp;
     *                   <code>MalfunctionIntensity.SEVERE_MALF</code><br>
     *                   &nbsp;&nbsp;&nbsp;
     *                   <code>MalfunctionIntensity.MEDIUM_MALF</code><br>
     *                   &nbsp;&nbsp;&nbsp; <code>MalfunctionIntensity.LOW_MALF</code>
     *                   <br>
     * @param pLength    The length (time-wise) of the malfunction <br>
     *                   Options are: <br>
     *                   &nbsp;&nbsp;&nbsp;
     *                   <code>MalfunctionLength.TEMPORARY_MALF</code><br>
     *                   &nbsp;&nbsp;&nbsp;
     *                   <code>MalfunctionLength.PERMANENT_MALF</code><br>
     */
    public void startMalfunction(MalfunctionIntensity pIntensity,
                                 MalfunctionLength pLength) {
        for (int i = 0; i < modules.length; i++) {
            IBioModule currentBioModule = (modules[i]);
            currentBioModule.startMalfunction(pIntensity, pLength);
        }
    }

    private String getTicksInHumanReadableFormat() {
        // ticks are 1 hour by default, but need to multiply by tick length
        // to get actual hours
        float hours = ticksGoneBy * getTickLength();
        int days = (int) (hours / 24);
        hours = hours % 24;
        return days + " days, " + hours + " hours";
    }

    /**
     * Resets the simulation by calling every known server's reset method.
     * Typically this means resetting the various gas levels, crew people, water
     * levels, etc.
     */
    public synchronized void reset() {
        myLogger.debug("BioDriver" + myID + ": Resetting simulation");
        ticksGoneBy = 0;
        simulationEnded = false;
        for (IBioModule currentBioModule : modules) {
            myLogger.debug("resetting " + currentBioModule.getModuleName());
            currentBioModule.reset();
            currentBioModule.setTickLength(getTickLength());
        }
    }

    /**
     * Automatic ticks and lifecycle transitions share the driver monitor.
     */
    private void runSimulation() {
        Thread currentThread = Thread.currentThread();
        while (true) {
            synchronized (this) {
                try {
                    while (simulationIsPaused && myTickThread == currentThread)
                        wait();
                    // A stop or restart can revoke this worker while it is waiting.
                    if (myTickThread != currentThread || simulationEnded)
                        return;

                    tick();
                    // Callbacks may stop or restart the simulation during the tick.
                    if (myTickThread != currentThread || simulationEnded)
                        return;
                    if (isDone()) {
                        myLogger.info("🎬 Simulation ended after " + getTicksInHumanReadableFormat());
                        endSimulation();
                        if (looping)
                            startSimulation();
                        return;
                    }

                    // Release the monitor while throttled so pause/end can wake the worker.
                    if (myDriverStutterLength > 0)
                        wait(myDriverStutterLength);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    return;
                }
            }
        }
    }

    /**
     * Ticks every server. The SimEnvironment is ticked first as it keeps track
     * of time for the rest of the server. The other server are ticked in no
     * particular order by enumerating through the module hashtable. When every
     * server has been ticked, BioDriver notifies all it's listeners that
     * this has happened.
     */
    private void tick() {
        myLogger.debug("BioDrive: begin tick " + ticksGoneBy);
        // Iterate through the actuators and tick them
        for (IBioModule currentBioModule : actuators)
            currentBioModule.tick();
        // Iterate through the active sim modules and tick them
        for (IBioModule currentBioModule : activeSimModules) {
            currentBioModule.tick();
        }
        // Iterate through the passive sim modules and tick them
        for (IBioModule currentBioModule : passiveSimModules)
            currentBioModule.tick();
        // Iterate through the priority sim modules and tick them
        for (IBioModule currentBioModule : prioritySimModules)
            currentBioModule.tick();
        // Commit transfers together so roster membership cannot depend on group order.
        for (IBioModule currentBioModule : modules) {
            if (currentBioModule instanceof CrewGroup crewGroup)
                crewGroup.applyScheduledTransfers();
        }
        // Iterate through the sensors and tick them
        for (IBioModule currentBioModule : sensors)
            currentBioModule.tick();

        // Notify listeners after the tick is complete
        notifyTickListeners();

        ticksGoneBy++;
    }

    /**
     * @return tick length, in seconds
     */
    public float getTickLength() {
        return myTickLength;
    }

    /**
     * @param pTickLength in hours
     */
    public void setTickLength(float pTickLength) {
        myTickLength = pTickLength;
    }

    /**
     * Adds a listener to be notified when a tick occurs.
     *
     * @param listener The listener to add
     */
    public void addTickListener(TickListener listener) {
        if (!tickListeners.contains(listener)) {
            tickListeners.add(listener);
        }
    }

    /**
     * Removes a previously registered tick listener.
     *
     * @param listener The listener to remove
     */
    public void removeTickListener(TickListener listener) {
        tickListeners.remove(listener);
    }

    /**
     * Notifies all registered listeners that a tick has occurred.
     */
    private void notifyTickListeners() {
        for (TickListener listener : tickListeners) {
            listener.tickOccurred(myID, ticksGoneBy);
        }
    }

    private class Ticker implements Runnable {
        /**
         * Invoked by the myTickThread.start() method call and necessary to
         * implement Runnable. Lifecycle state is established before this worker starts.
         */
        public void run() {
            myLogger.debug("BioDriver" + myID + ": Running simulation...");
            runSimulation();
        }
    }
}
