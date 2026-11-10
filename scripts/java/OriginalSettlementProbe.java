import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;

/** Compile together with OriginalTreeProbe.java. No target application is started.
 * Original lC terminal snapshots -> lK factory -> lH direct ranking overload -> lF/lG.
 * Expected chips use an independent contribution-level pot partition, not HRC's winner-sort loop.
 */
public final class OriginalSettlementProbe {
    static Class<?> cls(String name) throws Exception { return OriginalTreeProbe.cls(name); }
    static Object field(Object value, String name, Class<?> type) throws Exception { return OriginalTreeProbe.field(value, name, type); }
    static Object zero(Object value, String name, Class<?> result) throws Exception { return OriginalTreeProbe.zero(value, name, result); }
    static Map<String,Object> obj(Object... pairs) { return OriginalTreeProbe.ordered(pairs); }
    static void emit(Object value) { OriginalTreeProbe.emit(value); }

    record Fixture(String id, long[] remaining, long[] contributed, int foldedMask, int[] ranksBySeat,
                   long extraAnte, boolean expectDetailAgreement) {}
    record Expected(long[] finalChips, long[] refund, List<Map<String,Object>> pots) {}

    static Expected partition(Fixture fixture) {
        int n = fixture.remaining.length;
        long[] won = fixture.remaining.clone(), refunds = new long[n];
        long previous = 0;
        boolean firstPot = true;
        List<Map<String,Object>> pots = new ArrayList<>();
        for (long level : Arrays.stream(fixture.contributed).filter(v -> v > 0).distinct().sorted().toArray()) {
            List<Integer> contributors = new ArrayList<>(), eligible = new ArrayList<>();
            for (int seat = 0; seat < n; seat++) if (fixture.contributed[seat] >= level) {
                contributors.add(seat);
                if ((fixture.foldedMask & (1 << seat)) == 0) eligible.add(seat);
            }
            long value = (level - previous) * contributors.size();
            previous = level;
            if (contributors.size() == 1) {
                int seat = contributors.get(0);
                if (eligible.isEmpty()) throw new IllegalArgumentException("Invalid lone folded excess in fixture");
                won[seat] += value; refunds[seat] += value;
                pots.add(obj("kind", "uncalled_refund", "amount", value, "seat", seat));
                continue;
            }
            if (firstPot) { value += fixture.extraAnte; firstPot = false; }
            int best = eligible.stream().mapToInt(seat -> fixture.ranksBySeat[seat]).max().orElseThrow();
            List<Integer> winners = eligible.stream().filter(seat -> fixture.ranksBySeat[seat] == best).sorted(Comparator.reverseOrder()).toList();
            long share = value / winners.size(), remainder = value % winners.size();
            for (int seat : winners) won[seat] += share;
            // Explicit tested odd-chip convention: highest seat index for equal-contribution ties.
            // All tie fixtures have equal winning contributions; no claim about arbitrary ties.
            won[winners.get(0)] += remainder;
            pots.add(obj("kind", "pot", "level", level, "amount", value, "eligible", eligible,
                "winners", winners, "share", share, "oddChips", remainder, "oddRecipient", winners.get(0)));
        }
        return new Expected(won, refunds, pots);
    }

    static Object snapshot(Fixture fixture) throws Exception {
        int n = fixture.remaining.length, everyone = (1 << n) - 1;
        // Reviewed lC constructor order: extraAnte,remaining,street,previous,folded,streetNo,
        // participants,lastActor,betCount,callCount,auxiliaryActedMask. All active seats have acted.
        Constructor<?> constructor = cls("lC").getDeclaredConstructor(long.class, long[].class, long[].class, long[].class,
            int.class, int.class, int.class, int.class, int.class, int.class, int.class);
        constructor.setAccessible(true);
        Object state = constructor.newInstance(fixture.extraAnte, fixture.remaining.clone(), fixture.contributed.clone(), new long[n],
            fixture.foldedMask, 0, everyone, -1, 1, 0, everyone);
        return OriginalTreeProbe.method(cls("lK"), "a", cls("lK"), cls("lC")).invoke(null, state);
    }

    static void run(Fixture fixture, Object noRake) throws Exception {
        Object terminal = snapshot(fixture);
        int[] active = (int[])field(terminal, "a", int[].class);
        int[] ranks = Arrays.stream(active).map(seat -> fixture.ranksBySeat[seat]).toArray();
        Object result;
        try {
            result = OriginalTreeProbe.method(cls("lH"), "a", cls("lF"), cls("lK"), int[].class, List.class, boolean.class)
                .invoke(noRake, terminal, ranks, List.of(), true);
        } catch (InvocationTargetException ex) { throw new RuntimeException(fixture.id, ex.getCause()); }
        long[] chips = (long[])zero(result, "a", long[].class);
        List<Map<String,Object>> originalPots = new ArrayList<>();
        long[] detailSum = new long[chips.length];
        long rake = 0;
        int potCount = (int)zero(result, "b", int.class);
        for (int i = 0; i < potCount; i++) {
            Object pot = OriginalTreeProbe.invoke(result, "a", cls("lG"), new Class<?>[]{int.class}, i);
            long[] awards = (long[])field(pot, "a", long[].class);
            long potRake = (long)field(pot, "a", long.class);
            rake += potRake;
            for (int j = 0; j < awards.length; j++) detailSum[j] += awards[j];
            originalPots.add(obj("awards", awards, "rake", potRake));
        }
        long initialTotal = fixture.extraAnte + Arrays.stream(fixture.remaining).sum() + Arrays.stream(fixture.contributed).sum();
        boolean conserved = Arrays.stream(chips).sum() + rake == initialTotal;
        boolean detailAgrees = true;
        long[] detailDelta = new long[chips.length];
        for (int i = 0; i < chips.length; i++) {
            detailDelta[i] = chips[i] - fixture.remaining[i] - detailSum[i];
            detailAgrees &= detailDelta[i] == 0;
        }
        Expected expected = partition(fixture);
        boolean chipAgreement = Arrays.equals(chips, expected.finalChips);
        emit(obj("kind", "settlement_case", "id", fixture.id,
            "input", obj("remaining", fixture.remaining, "contributed", fixture.contributed,
                "foldedMask", fixture.foldedMask, "ranksBySeat", fixture.ranksBySeat, "extraAnte", fixture.extraAnte,
                "terminalConstruction", "original lC private constructor + original lK.a(lC) sweep; synthetic terminal snapshot, not action replay"),
            "expected", obj("finalChips", expected.finalChips, "independentPots", expected.pots,
                "uncalledRefund", expected.refund, "detailAgreement", fixture.expectDetailAgreement,
                "basis", "independent ascending contribution partitions; equal-contribution tie odd chips to highest seat; detail mismatch expectation from audited bytecode"),
            "actual", obj("activeSeats", active, "rankInput", ranks,
                "lKRemaining", field(terminal, "a", long[].class), "lKStreetContributions", field(terminal, "b", long[].class),
                "lKPreviousContributions", field(terminal, "c", long[].class), "finalChips", chips,
                "potDetails", originalPots, "potAwardSum", detailSum, "finalMinusRemainingMinusPotAwards", detailDelta,
                "detailAgreement", detailAgrees, "eliminatedBy", zero(result, "a", int[][].class), "rake", rake,
                "initialTotal", initialTotal, "conserved", conserved),
            "pass", chipAgreement && conserved && detailAgrees == fixture.expectDetailAgreement));
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("Usage: OriginalSettlementProbe <reviewed calculator.jar>");
        Path path = Path.of(args[0]);
        String hash = OriginalTreeProbe.sha(Files.readAllBytes(path));
        if (!hash.equals(OriginalTreeProbe.EXPECTED_JAR_SHA)) throw new IllegalArgumentException("Unreviewed artifact: " + hash);
        emit(obj("kind", "metadata", "jarSha256", hash, "java", System.getProperty("java.version"),
            "mode", "original isolated settlement classes", "unit", "integer centichips", "rake", "disabled"));
        OriginalTreeProbe.loader = new OriginalTreeProbe.Isolated(path);
        Object noRake = cls("lH").getConstructor(double.class, long.class, cls("lI"))
            .newInstance(0.0, 0L, cls("lI").getEnumConstants()[0]);
        List<Fixture> fixtures = List.of(
            new Fixture("three_layer_allin", new long[]{0,0,0}, new long[]{100,200,300}, 0, new int[]{3,2,1}, 0, true),
            new Fixture("uncalled_excess_to_losing_big_stack", new long[]{0,0,0}, new long[]{300,200,100}, 0, new int[]{1,3,2}, 0, true),
            new Fixture("folded_contribution_stays_in_pot", new long[]{0,0,50}, new long[]{100,100,100}, 4, new int[]{3,2,99}, 0, true),
            new Fixture("even_two_way_tie", new long[]{0,0,0}, new long[]{100,100,100}, 0, new int[]{2,2,1}, 0, true),
            new Fixture("odd_two_way_tie", new long[]{0,0,0}, new long[]{100,100,1}, 0, new int[]{2,2,1}, 0, false),
            new Fixture("odd_three_way_tie", new long[]{0,0,0,0}, new long[]{100,100,100,1}, 0, new int[]{2,2,2,1}, 0, false),
            new Fixture("bb_ante_odd_tie", new long[]{0,0}, new long[]{100,100}, 0, new int[]{2,2}, 1, false)
        );
        for (Fixture fixture : fixtures) run(fixture, noRake);
        emit(obj("kind", "complete", "cases", fixtures.size()));
    }
}
