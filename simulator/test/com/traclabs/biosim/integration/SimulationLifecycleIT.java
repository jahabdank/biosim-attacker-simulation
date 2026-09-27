package com.traclabs.biosim.integration;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.traclabs.biosim.server.framework.BioDriver;
import com.traclabs.biosim.server.framework.BiosimInitializer;
import com.traclabs.biosim.server.framework.SimulationController;
import io.javalin.Javalin;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.lang.reflect.Field;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.locks.LockSupport;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

@Timeout(20)
class SimulationLifecycleIT {
    private static final String XML = """
            <biosim xmlns="http://www.traclabs.com/biosim">
              <Globals runTillN="%d" runTillCrewDeath="false" startPaused="true"
                       runTillPlantDeath="false" exitWhenFinished="false" driverStutterLength="0"/>
              <SimBioModules>
                <environment>
                  <SimEnvironment moduleName="Cabin" initialVolume="18000"/>
                </environment>
              </SimBioModules>
            </biosim>
            """;
    private final ObjectMapper mapper = new ObjectMapper();
    private final Map<Integer, Thread> workers = new HashMap<>();
    private Javalin app;
    private HttpClient client;

    @BeforeEach
    void startServer() {
        SimulationController controller = new SimulationController();
        controller.setWriteTicks(false);
        app = Javalin.create(config -> config.showJavalinBanner = false);
        controller.registerEndpoints(app);
        app.start("127.0.0.1", 0);
        client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    }

    @AfterEach
    void stopServer() throws Exception {
        for (Map.Entry<Integer, Thread> entry : workers.entrySet()) {
            BiosimInitializer.getInstance(entry.getKey()).getBioDriver().endSimulation();
            join(entry.getValue());
            BiosimInitializer.deleteInstance(entry.getKey());
        }
        if (client != null)
            client.close();
        if (app != null)
            app.stop();
    }

    @ParameterizedTest
    @ValueSource(ints = {1, 3, 60})
    void batchAcknowledgementAndTerminalSnapshotAgree(int limit) throws Exception {
        int id = startPaused(limit);
        JsonNode ack = post("/api/simulation/" + id + "/tick?n=" + (limit + 10), "");
        assertEquals(limit, ack.get("ticks").asInt());
        assertEquals(limit, ack.get("advanced").asInt());
        assertTerminalSnapshot(id, limit);
        join(workers.get(id));
        assertTerminalSnapshot(id, limit);

        for (String suffix : new String[]{"?n=10", "?n=1", ""}) {
            JsonNode repeated = post("/api/simulation/" + id + "/tick" + suffix, "");
            assertEquals(limit, repeated.get("ticks").asInt());
            assertEquals(0, repeated.get("advanced").asInt());
            assertTerminalSnapshot(id, limit);
        }
    }

    @Test
    void stoppingPausedWorkerLeavesZeroTickSnapshotAndZeroProgress() throws Exception {
        int id = startPaused(3);
        BiosimInitializer.getInstance(id).getBioDriver().endSimulation();
        join(workers.get(id));
        assertTerminalSnapshot(id, 0);
        JsonNode ack = post("/api/simulation/" + id + "/tick?n=10", "");
        assertEquals(0, ack.get("ticks").asInt());
        assertEquals(0, ack.get("advanced").asInt());
        assertTerminalSnapshot(id, 0);
    }

    @Test
    void concurrentBatchAcknowledgementsCountOnlyTheirOwnProgress() throws Exception {
        int id = startPaused(3);
        HttpRequest request = postRequest("/api/simulation/" + id + "/tick?n=10", "");
        var first = client.sendAsync(request, HttpResponse.BodyHandlers.ofString());
        var second = client.sendAsync(request, HttpResponse.BodyHandlers.ofString());
        JsonNode firstAck = json(first.get(5, TimeUnit.SECONDS));
        JsonNode secondAck = json(second.get(5, TimeUnit.SECONDS));
        assertEquals(3, firstAck.get("ticks").asInt());
        assertEquals(3, secondAck.get("ticks").asInt());
        assertEquals(3, firstAck.get("advanced").asInt() + secondAck.get("advanced").asInt());
        join(workers.get(id));
        assertTerminalSnapshot(id, 3);
    }

    private int startPaused(int limit) throws Exception {
        int id = post("/api/simulation/start", XML.formatted(limit)).get("simId").asInt();
        BioDriver driver = BiosimInitializer.getInstance(id).getBioDriver();
        Field field = BioDriver.class.getDeclaredField("myTickThread");
        field.setAccessible(true);
        Thread worker;
        synchronized (driver) {
            worker = (Thread) field.get(driver);
        }
        workers.put(id, worker);
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
        while (worker.isAlive() && worker.getState() != Thread.State.WAITING && System.nanoTime() < deadline)
            LockSupport.parkNanos(TimeUnit.MILLISECONDS.toNanos(1));
        assertEquals(Thread.State.WAITING, worker.getState(), "Driver never entered its paused wait");
        return id;
    }

    private void assertTerminalSnapshot(int id, int ticks) throws Exception {
        HttpRequest request = HttpRequest.newBuilder(uri("/api/simulation/" + id))
                .timeout(Duration.ofSeconds(5)).GET().build();
        JsonNode globals = json(client.send(request, HttpResponse.BodyHandlers.ofString())).get("globals");
        assertEquals(ticks, globals.get("ticksGoneBy").asInt());
        assertTrue(globals.get("simulationEnded").asBoolean());
        assertFalse(globals.get("simulationStarted").asBoolean());
    }

    private JsonNode post(String path, String body) throws Exception {
        return json(client.send(postRequest(path, body), HttpResponse.BodyHandlers.ofString()));
    }

    private HttpRequest postRequest(String path, String body) {
        return HttpRequest.newBuilder(uri(path)).timeout(Duration.ofSeconds(5))
                .header("Content-Type", "application/xml")
                .POST(HttpRequest.BodyPublishers.ofString(body)).build();
    }

    private URI uri(String path) {
        return URI.create("http://127.0.0.1:" + app.port() + path);
    }

    private JsonNode json(HttpResponse<String> response) throws Exception {
        assertEquals(200, response.statusCode(), response.body());
        return mapper.readTree(response.body());
    }

    private static void join(Thread worker) throws InterruptedException {
        worker.join(5000);
        assertFalse(worker.isAlive(), "Stopped driver thread remained alive");
    }
}
