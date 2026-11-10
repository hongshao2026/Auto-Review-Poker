import java.io.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import java.util.function.IntFunction;
import java.util.jar.*;

/** Read-only, allowlisted invocation of reviewed original rule classes; not the HRC application.
 * Compile with Java 21, then supply exactly one reviewed calculator JAR path.
 * Output is JSONL. Expected values describe the static-bytecode hypothesis, not poker standards.
 * No commercial GUI, solver, settings, native library, network or license code is loaded.
 */
public final class OriginalTreeProbe {
    static final String PREFIX = "net.holdemresources.internal.";
    static final String EXPECTED_JAR_SHA = "25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43";
    static final List<String> ALLOW = List.of(
        "kG", "kM", "kJ", "ky", "kz", "kA", "kH", "lE", "lH", "lI", "lD", "lG", "lF", "lK", "lJ",
        "lA", "lz", "ly", "lB", "lC", "mF", "mM", "mI", "mH", "mJ", "mK", "mL", "mG", "rD");
    static final class Isolated extends ClassLoader {
        final Map<String, byte[]> bytes = new HashMap<>();
        Isolated(Path path) throws Exception {
            super(ClassLoader.getPlatformClassLoader());
            try (JarFile jar = new JarFile(path.toFile())) {
                for (String shortName : ALLOW) {
                    String name = PREFIX + shortName;
                    JarEntry entry = jar.getJarEntry(name.replace('.', '/') + ".class");
                    if (entry == null) throw new IllegalArgumentException("Missing reviewed class " + name);
                    byte[] payload;
                    try (InputStream input = jar.getInputStream(entry)) { payload = input.readAllBytes(); }
                    bytes.put(name, payload);
                    emit(Map.of("kind", "class", "name", name, "sha256", sha(payload)));
                }
            }
        }
        @Override protected Class<?> findClass(String name) throws ClassNotFoundException {
            byte[] payload = bytes.get(name);
            if (payload == null) throw new ClassNotFoundException("Outside reviewed allowlist: " + name);
            emit(Map.of("kind", "load", "name", name));
            return defineClass(name, payload, 0, payload.length);
        }
        @Override public InputStream getResourceAsStream(String name) { return null; }
    }
    static Isolated loader;
    static Class<?> cls(String name) throws Exception { return Class.forName(PREFIX + name, false, loader); }
    static Method method(Class<?> type, String name, Class<?> result, Class<?>... parameters) {
        for (Method m : type.getDeclaredMethods()) {
            if (m.getName().equals(name) && m.getReturnType() == result && Arrays.equals(m.getParameterTypes(), parameters)) {
                m.setAccessible(true); return m;
            }
        }
        throw new AssertionError("Missing descriptor: " + type.getName() + "." + name + Arrays.toString(parameters) + result);
    }
    static Object field(Object object, String name, Class<?> type) throws Exception {
        for (Field f : object.getClass().getDeclaredFields()) {
            if (f.getName().equals(name) && f.getType() == type) { f.setAccessible(true); return f.get(object); }
        }
        throw new AssertionError("Missing field descriptor: " + object.getClass() + "." + name + ":" + type);
    }
    static Object invoke(Object object, String name, Class<?> result, Class<?>[] params, Object... values) throws Exception {
        try { return method(object.getClass(), name, result, params).invoke(object, values); }
        catch (InvocationTargetException error) {
            Throwable cause = error.getCause();
            if (cause instanceof Exception ex) throw ex;
            throw error;
        }
    }
    static Object zero(Object object, String name, Class<?> result) throws Exception {
        return invoke(object, name, result, new Class<?>[0]);
    }
    static Object context(long[] stacks) throws Exception {
        // HRC blind tuple is [BB, SB, ante]; internal amounts are integral centichips.
        Object blinds = cls("ky").getConstructor(long[].class, boolean.class, cls("kz"), cls("kA"))
            .newInstance(new long[]{100, 50, 0}, false, cls("kz").getEnumConstants()[0], cls("kA").getEnumConstants()[0]);
        Object config = cls("kM").getConstructor(long[].class, cls("ky"), boolean.class, cls("lH"))
            .newInstance(stacks.clone(), blinds, false, null);
        return cls("lB").getConstructor(cls("kG")).newInstance(config);
    }
    static Object raise(Object context, long size) throws Exception {
        if (!(boolean)zero(context, "a", boolean.class)) throw new IllegalStateException("Harness refuses raise while original canRaise=false");
        return invoke(context, "a", cls("lB"), new Class<?>[]{long.class}, size);
    }
    static Object call(Object context) throws Exception { return zero(context, "d", cls("lB")); }
    static Map<String, Object> action(Object action) throws Exception {
        String[] names = {"fold", "check", "call", "raise"};
        int kind = ((Enum<?>)zero(action, "a", cls("lz"))).ordinal();
        return ordered("kind", names[kind], "actor", field(action, "a", byte.class), "street", field(action, "b", byte.class),
            "amount", field(action, "a", long.class), "allinFlag", field(action, "a", boolean.class));
    }
    static Map<String, Object> snapshot(Object context) throws Exception {
        Object state = field(context, "a", cls("lC"));
        List<?> history = (List<?>)field(context, "a", List.class);
        List<Object> historyJson = new ArrayList<>();
        for (Object act : history) historyJson.add(action(act));
        return ordered("actor", field(context, "a", int.class), "street", field(state, "a", int.class),
            "canRaise", zero(context, "a", boolean.class), "minimum", field(context, "a", long.class),
            "maximum", field(context, "b", long.class), "currentBet", zero(state, "c", long.class),
            "remaining", field(state, "a", long[].class), "streetContributions", field(state, "b", long[].class),
            "previousContributions", field(state, "c", long[].class), "participantsMask", field(state, "b", int.class),
            "foldedMask", field(state, "c", int.class), "history", historyJson);
    }
    static List<Map<String, Object>> children(Object context, int participantCap, long... requestedSizes) throws Exception {
        List<Long> sizes = Arrays.stream(requestedSizes).boxed().toList();
        Class<?> pre = cls("mI");
        // mI has no conflicting return-only overloads; its two hooks are inert input providers.
        Object policy = Proxy.newProxyInstance(loader, new Class<?>[]{pre}, (proxy, method, args) -> {
            if (method.getName().equals("b") && method.getReturnType() == Collection.class) return sizes;
            if (method.getName().equals("c") && method.getReturnType() == boolean.class) return true;
            throw new UnsupportedOperationException(method.toString());
        });
        Object noCounterfactual = cls("mK").getEnumConstants()[0];
        IntFunction<Object> streetPolicy = ignored -> noCounterfactual;
        Object policies = cls("mM").getConstructor(pre, cls("mH"), IntFunction.class).newInstance(policy, null, streetPolicy);
        Object config = field(context, "a", cls("kG"));
        List<?> history = (List<?>)field(context, "a", List.class);
        Object tree = method(cls("mF"), "a", cls("mF"), cls("kG"), int.class, cls("mM"), List.class)
            .invoke(null, config, participantCap, policies, history);
        Class<?> arrayType = Array.newInstance(cls("rD"), 0).getClass();
        Object[] descendants = (Object[])zero(tree, "a", arrayType);
        List<Map<String, Object>> result = new ArrayList<>();
        for (Object descendant : descendants) {
            Object childContext = field(descendant, "a", cls("lB"));
            List<?> childHistory = (List<?>)field(childContext, "a", List.class);
            // Child normalization may append zero-stack calls; record the first actual edge.
            result.add(action(childHistory.get(history.size())));
        }
        return result;
    }
    static void check(String id, Object context, Map<String, Object> expected, int cap, long... sizes) throws Exception {
        Map<String, Object> actual = snapshot(context);
        List<Map<String, Object>> edges = children(context, cap, sizes);
        actual.put("generatedActions", edges);
        List<Object> raiseAmounts = new ArrayList<>();
        for (Map<String, Object> edge : edges) if (edge.get("kind").equals("raise")) raiseAmounts.add(edge.get("amount"));
        actual.put("generatedRaiseTo", raiseAmounts);
        boolean pass = true;
        for (Map.Entry<String, Object> entry : expected.entrySet()) pass &= json(entry.getValue()).equals(json(actual.get(entry.getKey())));
        Object config = field(context, "a", cls("kG"));
        emit(ordered("kind", "tree_case", "id", id, "input", ordered("stacks", field(config, "a", long[].class), "blinds", new long[]{100, 50, 0},
            "participantCap", cap, "requestedSizes", sizes), "expectedBasis", "static original-bytecode hypothesis",
            "expected", expected, "actual", actual, "pass", pass));
    }
    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("Usage: OriginalTreeProbe <reviewed calculator.jar>");
        Path path = Path.of(args[0]);
        String jarHash = sha(Files.readAllBytes(path));
        if (!EXPECTED_JAR_SHA.equals(jarHash)) throw new IllegalArgumentException("Unreviewed artifact: " + jarHash);
        emit(ordered("kind", "metadata", "jarSha256", jarHash, "java", System.getProperty("java.version"),
            "positions3", List.of("BTN", "SB", "BB"), "unit", "centichips", "mode", "original isolated classes"));
        loader = new Isolated(path);
        Object initial = context(new long[]{2000, 400, 2000});
        check("initial_btn", initial, ordered("actor", 0, "minimum", 200L, "maximum", 2000L, "canRaise", true,
            "generatedRaiseTo", List.of(200L, 300L, 2000L)), 3, 150, 300, 9999);
        Object a300 = raise(initial, 300);
        check("sb_short_stack", a300, ordered("actor", 1, "minimum", 500L, "maximum", 400L, "canRaise", true,
            "generatedRaiseTo", List.of(400L)), 3, 400, 500, 9999);
        Object b400 = raise(a300, 400);
        check("fresh_bb_after_short_allin", b400, ordered("actor", 2, "minimum", 500L, "maximum", 2000L, "canRaise", true,
            "generatedRaiseTo", List.of(500L, 600L, 2000L)), 3, 450, 500, 600, 9999);
        Object afterCall = call(b400);
        check("original_raiser_after_short_and_call", afterCall, ordered("actor", 0, "minimum", -1L, "canRaise", false,
            "generatedRaiseTo", List.of()), 3, 500, 1000);
        Object c500 = raise(b400, 450);
        check("request450_normalized_to500_reopens", c500, ordered("actor", 0, "minimum", 700L, "canRaise", true,
            "generatedRaiseTo", List.of(700L, 2000L)), 3, 650, 700, 9999);
        Object effective = context(new long[]{2000, 400, 1000});
        check("effective_cap_before_raise", effective, ordered("actor", 0, "maximum", 1000L,
            "generatedRaiseTo", List.of(1000L)), 3, 9999);
        // Use the concrete edge emitted by mF, not an unchecked request passed directly to lB.
        List<Map<String, Object>> effectiveEdges = children(effective, 3, 9999);
        long generatedSize = (long)effectiveEdges.stream().filter(edge -> edge.get("kind").equals("raise")).findFirst().orElseThrow().get("amount");
        Object capped = raise(effective, generatedSize);
        check("generated_effective_allin_leaves_actor_chips", capped, ordered("actor", 1, "remaining", new long[]{1000, 350, 900},
            "canRaise", false, "generatedRaiseTo", List.of()), 3, 9999);
        // Preserve the observed lower-level distinction: lB checks own-stack cap first.
        Object unchecked = raise(effective, 9999);
        check("direct_low_level9999_exceeds_effective_cap", unchecked, ordered("actor", 1, "remaining", new long[]{0, 350, 900},
            "currentBet", 2000L, "canRaise", false, "generatedRaiseTo", List.of()), 3, 9999);
        emit(ordered("kind", "complete", "cases", 8));
    }
    static Map<String, Object> ordered(Object... pairs) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int i = 0; i < pairs.length; i += 2) result.put((String)pairs[i], pairs[i + 1]);
        return result;
    }
    static String sha(byte[] data) throws Exception { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(data)); }
    static void emit(Object value) { System.out.println(json(value)); }
    static String json(Object value) {
        if (value == null) return "null";
        if (value instanceof String s) return "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r") + "\"";
        if (value instanceof Map<?, ?> map) {
            List<String> entries = new ArrayList<>();
            for (Map.Entry<?, ?> entry : map.entrySet()) entries.add(json(entry.getKey().toString()) + ":" + json(entry.getValue()));
            return "{" + String.join(",", entries) + "}";
        }
        if (value instanceof Collection<?> list) return "[" + String.join(",", list.stream().map(OriginalTreeProbe::json).toList()) + "]";
        if (value.getClass().isArray()) {
            List<String> parts = new ArrayList<>();
            for (int i = 0; i < Array.getLength(value); i++) parts.add(json(Array.get(value, i)));
            return "[" + String.join(",", parts) + "]";
        }
        return value.toString();
    }
}
