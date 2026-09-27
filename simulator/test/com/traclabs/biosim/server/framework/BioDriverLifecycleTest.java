package com.traclabs.biosim.server.framework;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.locks.LockSupport;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

@Timeout(15)
class BioDriverLifecycleTest {
    private final BioDriver driver = new BioDriver(9001);
    private final List<Thread> workers = new CopyOnWriteArrayList<>();

    @AfterEach
    void tearDown() throws Exception {
        driver.setLooping(false);
        driver.endSimulation();
        for (Thread worker : workers)
            join(worker);
    }

    @Test
    void unstartedAndResetFixturesCanStepButEndedFixturesCannot() {
        driver.setRunTillN(3);
        driver.advanceTicks(10);
        assertEquals(3, driver.getTicks());
        assertTrue(driver.isEnded());
        assertFalse(driver.isStarted());
        driver.advanceTicks(10);
        driver.advanceOneTick();
        assertEquals(3, driver.getTicks());

        driver.reset();
        assertFalse(driver.isEnded());
        driver.advanceOneTick();
        assertEquals(1, driver.getTicks());
        assertTrue(driver.isPaused());
        assertFalse(driver.isStarted());
    }

    @Test
    void batchBoundaryDoesNotWakePausedWorkerForAnExtraTick() throws Exception {
        driver.setRunTillN(3);
        Thread worker = startPaused();
        driver.advanceTicks(10);
        join(worker);
        assertEquals(3, driver.getTicks());
        assertTrue(driver.isEnded());
        assertFalse(driver.isStarted());
        driver.advanceTicks(10);
        assertEquals(3, driver.getTicks());
    }

    @Test
    void stopWhilePausedTerminatesWithoutTicking() throws Exception {
        Thread worker = startPaused();
        driver.endSimulation();
        join(worker);
        assertEquals(0, driver.getTicks());
        assertTrue(driver.isEnded());
        driver.setPauseSimulation(false);
        driver.advanceTicks(10);
        assertEquals(0, driver.getTicks());
    }

    @Test
    void stoppedWorkerCannotReestablishStartedState() throws Exception {
        Thread worker;
        synchronized (driver) {
            driver.setPauseSimulation(true);
            driver.startSimulation();
            worker = rememberWorker();
            driver.endSimulation();
        }
        join(worker);
        assertFalse(driver.isStarted());
        assertTrue(driver.isEnded());
        assertEquals(0, driver.getTicks());
    }

    @Test
    void restartRevokesOldPausedWorkerWithoutAnExtraTick() throws Exception {
        Thread previous = startPaused();
        driver.startSimulation();
        Thread replacement = rememberWorker();
        join(previous);
        awaitState(replacement, Thread.State.WAITING);
        assertEquals(0, driver.getTicks());
        assertTrue(driver.isStarted());
        assertFalse(driver.isEnded());
        driver.advanceOneTick();
        assertEquals(1, driver.getTicks());
    }

    @Test
    void stopWakesThrottledWorkerWithoutWaitingForTheDelay() throws Exception {
        driver.setDriverStutterLength(60000);
        Thread worker = startPaused();
        CountDownLatch ticked = new CountDownLatch(1);
        driver.addTickListener((id, tick) -> ticked.countDown());
        driver.setPauseSimulation(false);
        await(ticked);
        awaitState(worker, Thread.State.TIMED_WAITING);
        driver.endSimulation();
        join(worker);
        assertEquals(1, driver.getTicks());
    }

    @Test
    void callbackCanPauseAndResumeWithoutChangingTickNumbering() throws Exception {
        AtomicInteger callbacks = new AtomicInteger();
        CountDownLatch[] paused = {new CountDownLatch(1), new CountDownLatch(1)};
        driver.addTickListener((id, tick) -> {
            int index = callbacks.getAndIncrement();
            assertEquals(index, tick);
            assertEquals(tick, driver.getTicks());
            assertTrue(driver.isStarted());
            driver.setPauseSimulation(true);
            paused[index].countDown();
        });
        Thread worker = startPaused();
        for (int expected = 1; expected <= 2; expected++) {
            driver.setPauseSimulation(false);
            await(paused[expected - 1]);
            awaitState(worker, Thread.State.WAITING);
            assertEquals(expected, driver.getTicks());
            assertEquals(expected, callbacks.get());
            assertTrue(driver.isPaused());
        }
    }

    @ParameterizedTest
    @ValueSource(booleans = {false, true})
    void pauseOrEndWaitsForTheInFlightTickBoundary(boolean end) throws Exception {
        CountDownLatch entered = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        BioModule module = new BioModule(9001, "BlockingModule") {
            @Override
            public void tick() {
                entered.countDown();
                try {
                    await(release);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    throw new AssertionError(e);
                }
                super.tick();
            }
        };
        driver.setModules(new IBioModule[]{module});
        driver.setActiveSimModules(new IBioModule[]{module});
        driver.setDriverStutterLength(60000);
        Thread worker = startPaused();
        Thread control = new Thread(() -> {
            if (end)
                driver.endSimulation();
            else
                driver.setPauseSimulation(true);
        }, "Lifecycle test control");
        try {
            driver.setPauseSimulation(false);
            await(entered);
            control.start();
            awaitState(control, Thread.State.BLOCKED);
        } finally {
            release.countDown();
            join(control);
        }
        if (end)
            join(worker);
        else
            awaitState(worker, Thread.State.WAITING);
        assertEquals(1, driver.getTicks());
        assertEquals(1, module.getMyTicks());
        assertEquals(end, driver.isEnded());
    }

    @Test
    void automaticLoopingRestartsAtTheBoundaryAndRetainsCallbackOrder() throws Exception {
        driver.setRunTillN(3);
        driver.setLooping(true);
        List<Integer> ticks = new ArrayList<>();
        CountDownLatch callbacks = new CountDownLatch(6);
        driver.addTickListener((id, tick) -> {
            workers.add(Thread.currentThread());
            ticks.add(tick);
            if (ticks.size() == 6)
                driver.setLooping(false);
            callbacks.countDown();
        });
        driver.startSimulation();
        await(callbacks);
        join(workers.get(workers.size() - 1));
        assertEquals(List.of(0, 1, 2, 0, 1, 2), ticks);
        assertEquals(3, driver.getTicks());
        assertTrue(driver.isEnded());
        assertFalse(driver.isStarted());
    }

    @ParameterizedTest
    @ValueSource(booleans = {false, true})
    void callbackStopSuppressesLoopingAndRemainingBatchTicks(boolean automatic) throws Exception {
        driver.setLooping(true);
        driver.setRunTillN(1);
        AtomicInteger callbacks = new AtomicInteger();
        driver.addTickListener((id, tick) -> {
            callbacks.incrementAndGet();
            driver.endSimulation();
        });
        if (automatic) {
            Thread worker = startPaused();
            driver.setPauseSimulation(false);
            join(worker);
        } else {
            driver.advanceTicks(10);
        }
        assertEquals(1, callbacks.get());
        assertEquals(1, driver.getTicks());
        assertTrue(driver.isEnded());
        driver.advanceTicks(10);
        assertEquals(1, driver.getTicks());
    }

    private Thread startPaused() throws Exception {
        driver.setPauseSimulation(true);
        driver.startSimulation();
        Thread worker = rememberWorker();
        awaitState(worker, Thread.State.WAITING);
        return worker;
    }

    private Thread rememberWorker() throws Exception {
        Field field = BioDriver.class.getDeclaredField("myTickThread");
        field.setAccessible(true);
        synchronized (driver) {
            Thread worker = (Thread) field.get(driver);
            assertNotNull(worker);
            workers.add(worker);
            return worker;
        }
    }

    private static void await(CountDownLatch latch) throws InterruptedException {
        assertTrue(latch.await(5, TimeUnit.SECONDS), "Worker did not reach the test barrier");
    }

    private static void awaitState(Thread thread, Thread.State state) {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
        while (thread.isAlive() && thread.getState() != state && System.nanoTime() < deadline)
            LockSupport.parkNanos(TimeUnit.MILLISECONDS.toNanos(1));
        assertEquals(state, thread.getState(), "Worker did not reach the expected lifecycle state");
    }

    private static void join(Thread thread) throws InterruptedException {
        thread.join(5000);
        assertFalse(thread.isAlive(), "Lifecycle worker did not terminate");
    }
}
