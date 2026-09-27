package com.traclabs.biosim.server.util.massvalidation;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

public final class MassLedger {
    public static final double TOL_ABS_KG = MassConstants.TOL_ABS_KG;

    private final Path csvPath;
    private final Path summaryPath;
    private final LinkedHashMap<String, CompartmentSnapshotter> compartments = new LinkedHashMap<>();
    private final LinkedHashMap<String, AccountedTermComputer> accountedTerms = new LinkedHashMap<>();
    private final LinkedHashMap<String, String> accountedRationales = new LinkedHashMap<>();
    private final List<Row> rows = new ArrayList<>();
    private final List<String> modules = new ArrayList<>();
    private final List<String> notes = new ArrayList<>();
    private String scenario = "MassValidationInit";
    private double tickLengthHours = 1.0;
    private int simulationTicks = 0;
    private double maxAbsResidual = 0.0;
    private int worstTick = -1;
    private String worstCompartmentDelta = "";

    public MassLedger(Path csvPath, Path summaryPath) {
        this.csvPath = csvPath;
        this.summaryPath = summaryPath;
    }

    public void setScenario(String scenario) {
        this.scenario = scenario;
    }

    public void setTickLengthHours(double tickLengthHours) {
        this.tickLengthHours = tickLengthHours;
    }

    public void setSimulationTicks(int simulationTicks) {
        this.simulationTicks = simulationTicks;
    }

    public void setModules(List<String> moduleNames) {
        modules.clear();
        modules.addAll(moduleNames);
    }

    public void addNote(String note) {
        notes.add(note);
    }

    public void addCompartment(String key, CompartmentSnapshotter snap) {
        compartments.put(key, snap);
    }

    public void addAccountedTerm(String key, AccountedTermComputer term, String oneLineRationale) {
        accountedTerms.put(key, term);
        accountedRationales.put(key, oneLineRationale);
    }

    public void recordTick(int tick) {
        LinkedHashMap<String, Double> compartmentValues = new LinkedHashMap<>();
        double total = 0.0;
        for (Map.Entry<String, CompartmentSnapshotter> entry : compartments.entrySet()) {
            double kg = entry.getValue().snapshotKg();
            compartmentValues.put(entry.getKey(), kg);
            total += kg;
        }

        LinkedHashMap<String, Double> termValues = new LinkedHashMap<>();
        double accountedSum = 0.0;
        for (Map.Entry<String, AccountedTermComputer> entry : accountedTerms.entrySet()) {
            double kg = entry.getValue().computeKg(tick);
            termValues.put(entry.getKey(), kg);
            accountedSum += kg;
        }

        double delta = rows.isEmpty() ? 0.0 : total - rows.get(rows.size() - 1).totalKg;
        double residual = rows.isEmpty() ? 0.0 : delta - accountedSum;
        Row row = new Row(tick, compartmentValues, termValues, total, delta, accountedSum, residual);
        rows.add(row);

        double absResidual = Math.abs(residual);
        if (absResidual > maxAbsResidual) {
            maxAbsResidual = absResidual;
            worstTick = tick;
            worstCompartmentDelta = findLargestCompartmentDelta();
        }

        writeCsv();
    }

    public ValidationResult validate(double tolAbsKg) {
        boolean passed = maxAbsResidual <= tolAbsKg;
        ValidationResult result = new ValidationResult(passed, maxAbsResidual, worstTick, worstCompartmentDelta);
        writeSummary(tolAbsKg, result);
        return result;
    }

    public double getMaxAbsResidual() {
        return maxAbsResidual;
    }

    public List<String> getCompartmentKeys() {
        return Collections.unmodifiableList(new ArrayList<>(compartments.keySet()));
    }

    public List<String> getAccountedTermKeys() {
        return Collections.unmodifiableList(new ArrayList<>(accountedTerms.keySet()));
    }

    public Path getCsvPath() {
        return csvPath;
    }

    public Path getSummaryPath() {
        return summaryPath;
    }

    public int getRowCount() {
        return rows.size();
    }

    public int getSimulationTicks() {
        return simulationTicks;
    }

    public double getCompartmentDelta(String key) {
        if (rows.size() < 2) {
            return 0.0;
        }
        Row first = rows.get(0);
        Row last = rows.get(rows.size() - 1);
        if (!first.compartments.containsKey(key) || !last.compartments.containsKey(key)) {
            throw new IllegalArgumentException("Unknown compartment: " + key);
        }
        return last.compartments.get(key) - first.compartments.get(key);
    }

    private String findLargestCompartmentDelta() {
        if (rows.size() < 2) {
            return "";
        }
        Row current = rows.get(rows.size() - 1);
        Row previous = rows.get(rows.size() - 2);
        String worstKey = "";
        double worstDelta = 0.0;
        for (String key : compartments.keySet()) {
            double delta = current.compartments.get(key) - previous.compartments.get(key);
            if (Math.abs(delta) > Math.abs(worstDelta)) {
                worstDelta = delta;
                worstKey = key;
            }
        }
        return worstKey + "=" + format(worstDelta);
    }

    private void writeCsv() {
        try {
            Files.createDirectories(csvPath.getParent());
            StringBuilder out = new StringBuilder();
            out.append("tick");
            for (String key : compartments.keySet()) {
                out.append(',').append(key);
            }
            for (String key : accountedTerms.keySet()) {
                out.append(',').append(key);
            }
            out.append(",total_kg,delta_kg,accounted_sum_kg,residual_kg\n");
            for (Row row : rows) {
                out.append(row.tick);
                for (String key : compartments.keySet()) {
                    out.append(',').append(format(row.compartments.get(key)));
                }
                for (String key : accountedTerms.keySet()) {
                    out.append(',').append(format(row.accountedTerms.get(key)));
                }
                out.append(',').append(format(row.totalKg));
                out.append(',').append(format(row.deltaKg));
                out.append(',').append(format(row.accountedSumKg));
                out.append(',').append(format(row.residualKg));
                out.append('\n');
            }
            Files.writeString(csvPath, out.toString(), StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    private void writeSummary(double tolAbsKg, ValidationResult result) {
        try {
            Files.createDirectories(summaryPath.getParent());
            StringBuilder out = new StringBuilder();
            out.append("{\n");
            appendJsonField(out, "scenario", scenario, true, 1);
            appendJsonField(out, "ticks_run", Math.max(0, rows.size() - 1), true, 1);
            appendJsonField(out, "bio_driver_ticks", simulationTicks, true, 1);
            appendJsonField(out, "tick_length_hours", tickLengthHours, true, 1);
            out.append("  \"modules\": [");
            for (int i = 0; i < modules.size(); i++) {
                if (i > 0) {
                    out.append(',');
                }
                out.append('"').append(jsonEscape(modules.get(i))).append('"');
            }
            out.append("],\n");
            out.append("  \"compartments\": [\n");
            int index = 0;
            Row first = rows.isEmpty() ? null : rows.get(0);
            for (String key : compartments.keySet()) {
                out.append("    {\"key\":\"").append(jsonEscape(key)).append("\",\"unit\":\"kg\",\"initial_kg\":")
                        .append(format(first == null ? 0.0 : first.compartments.get(key))).append("}");
                if (++index < compartments.size()) {
                    out.append(',');
                }
                out.append('\n');
            }
            out.append("  ],\n");
            out.append("  \"accounted_terms\": [");
            index = 0;
            for (String key : accountedTerms.keySet()) {
                if (index++ > 0) {
                    out.append(',');
                }
                out.append("{\"key\":\"").append(jsonEscape(key)).append("\",\"unit\":\"kg\",\"rationale\":\"")
                        .append(jsonEscape(accountedRationales.get(key))).append("\"}");
            }
            out.append("],\n");
            appendJsonField(out, "tol_abs_kg", tolAbsKg, true, 1);
            appendJsonField(out, "tol_abs_justification", MassConstants.TOL_ABS_JUSTIFICATION, true, 1);
            appendJsonField(out, "max_abs_residual_kg", result.maxAbsResidual, true, 1);
            appendJsonField(out, "worst_tick", result.worstTick, true, 1);
            appendJsonField(out, "worst_compartment_delta", result.worstCompartmentDelta, true, 1);
            appendJsonField(out, "boundary", "after-tick", true, 1);
            appendJsonField(out, "passed", result.passed, true, 1);
            out.append("  \"notes\": [");
            for (int i = 0; i < notes.size(); i++) {
                if (i > 0) {
                    out.append(',');
                }
                out.append('"').append(jsonEscape(notes.get(i))).append('"');
            }
            out.append("]\n");
            out.append("}\n");
            Files.writeString(summaryPath, out.toString(), StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    private static void appendJsonField(StringBuilder out, String key, String value, boolean comma, int indent) {
        out.append(" ".repeat(indent * 2)).append('"').append(jsonEscape(key)).append("\": \"")
                .append(jsonEscape(value)).append('"');
        if (comma) {
            out.append(',');
        }
        out.append('\n');
    }

    private static void appendJsonField(StringBuilder out, String key, double value, boolean comma, int indent) {
        out.append(" ".repeat(indent * 2)).append('"').append(jsonEscape(key)).append("\": ").append(format(value));
        if (comma) {
            out.append(',');
        }
        out.append('\n');
    }

    private static void appendJsonField(StringBuilder out, String key, int value, boolean comma, int indent) {
        out.append(" ".repeat(indent * 2)).append('"').append(jsonEscape(key)).append("\": ").append(value);
        if (comma) {
            out.append(',');
        }
        out.append('\n');
    }

    private static void appendJsonField(StringBuilder out, String key, boolean value, boolean comma, int indent) {
        out.append(" ".repeat(indent * 2)).append('"').append(jsonEscape(key)).append("\": ").append(value);
        if (comma) {
            out.append(',');
        }
        out.append('\n');
    }

    private static String format(double value) {
        return String.format(Locale.ROOT, "%.12e", value);
    }

    private static String jsonEscape(String value) {
        StringBuilder escaped = new StringBuilder();
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            switch (c) {
                case '"' -> escaped.append("\\\"");
                case '\\' -> escaped.append("\\\\");
                case '\b' -> escaped.append("\\b");
                case '\f' -> escaped.append("\\f");
                case '\n' -> escaped.append("\\n");
                case '\r' -> escaped.append("\\r");
                case '\t' -> escaped.append("\\t");
                default -> {
                    if (c < 0x20) {
                        escaped.append(String.format(Locale.ROOT, "\\u%04x", (int) c));
                    } else {
                        escaped.append(c);
                    }
                }
            }
        }
        return escaped.toString();
    }

    private static final class Row {
        private final int tick;
        private final LinkedHashMap<String, Double> compartments;
        private final LinkedHashMap<String, Double> accountedTerms;
        private final double totalKg;
        private final double deltaKg;
        private final double accountedSumKg;
        private final double residualKg;

        private Row(int tick, LinkedHashMap<String, Double> compartments, LinkedHashMap<String, Double> accountedTerms,
                double totalKg, double deltaKg, double accountedSumKg, double residualKg) {
            this.tick = tick;
            this.compartments = compartments;
            this.accountedTerms = accountedTerms;
            this.totalKg = totalKg;
            this.deltaKg = deltaKg;
            this.accountedSumKg = accountedSumKg;
            this.residualKg = residualKg;
        }
    }

    public static final class ValidationResult {
        public final boolean passed;
        public final double maxAbsResidual;
        public final int worstTick;
        public final String worstCompartmentDelta;

        public ValidationResult(boolean passed, double maxAbsResidual, int worstTick, String worstCompartmentDelta) {
            this.passed = passed;
            this.maxAbsResidual = maxAbsResidual;
            this.worstTick = worstTick;
            this.worstCompartmentDelta = worstCompartmentDelta;
        }
    }
}
