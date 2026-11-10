import java.io.*;
import java.lang.invoke.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import java.util.function.Function;
import java.util.jar.*;

/** Original pure terminal mathematics only: no application, licensing or solver loop.
 * The only initialized application classes are the audited numeric contexts,
 * immutable result/context records, ICM recurrence and three enum constants.
 * lH is an allowed descriptor dependency, but none of its methods is invoked.
 */
public final class OriginalBountyProbe {
    static final String P = "net.holdemresources.internal.";
    static final String HASH = "25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43";
    static Isolated loader;
    static final class Isolated extends ClassLoader {
        final Map<String,byte[]> bytes = new HashMap<>();
        Isolated(Path path) throws Exception {
            super(ClassLoader.getPlatformClassLoader());
            String sha = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(path)));
            if (!sha.equals(HASH)) throw new IllegalArgumentException("Unreviewed main artifact: " + sha);
            try (JarFile jar = new JarFile(path.toFile())) {
                for (String shortName : List.of("kV","kU","kW","kC","kB","kE","ll","lk","lj","lc","lb",
                        "kG","kI","kK","kH","kF","lE","lF","lG","lD","ky","kz","kA","lH","lI","lK")) {
                    String name = P + shortName;
                    bytes.put(name, jar.getInputStream(jar.getJarEntry(name.replace('.', '/') + ".class")).readAllBytes());
                }
            }
        }
        protected Class<?> findClass(String name) throws ClassNotFoundException {
            byte[] value = bytes.get(name);
            if (value == null) throw new ClassNotFoundException("Outside audited allowlist: " + name);
            try {
                System.out.println("{\"kind\":\"class\",\"name\":\"" + name + "\",\"sha256\":\"" +
                    HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value)) + "\"}");
            } catch (NoSuchAlgorithmException e) { throw new AssertionError(e); }
            return defineClass(name, value, 0, value.length);
        }
    }
    static Class<?> cls(String name) throws Exception { return loader.loadClass(P + name); }
    static Object make(String name, String descriptor, Object... args) throws Throwable {
        return MethodHandles.publicLookup().findConstructor(cls(name), MethodType.fromMethodDescriptorString(descriptor, loader)).invokeWithArguments(args);
    }
    static Object call(String name, String descriptor, Object self, Object... args) throws Throwable {
        MethodHandle m = MethodHandles.publicLookup().findVirtual(cls(name), "a", MethodType.fromMethodDescriptorString(descriptor, loader));
        List<Object> arguments = new ArrayList<>(); arguments.add(self); arguments.addAll(Arrays.asList(args));
        return m.invokeWithArguments(arguments);
    }
    static Object field(Object self, Class<?> type) throws Exception {
        for (Field field : self.getClass().getDeclaredFields()) if (field.getType() == type) { field.setAccessible(true); return field.get(self); }
        throw new AssertionError("Missing field type " + type);
    }
    static long[] longs(String s) { return s.equals("-") ? new long[0] : Arrays.stream(s.split(",")).mapToLong(Long::parseLong).toArray(); }
    static double[] doubles(String s) { return s.equals("-") ? new double[0] : Arrays.stream(s.split(",")).mapToDouble(Double::parseDouble).toArray(); }
    static double[] subtract(double[] a, double[] b) { double[] out = a.clone(); for(int i=0;i<out.length;i++)out[i]-=b[i];return out; }

    public static void main(String[] args) throws Throwable {
        loader = new Isolated(Path.of(args[0]));
        System.out.println("{\"kind\":\"metadata\",\"jar_sha256\":\"" + HASH + "\",\"scope\":\"unmodified original terminal ICM/KO/PKO contexts and evaluators; supplied synthetic settlement outcomes\"}");
        Object blinds = make("ky", "([JZLnet/holdemresources/internal/kz;Lnet/holdemresources/internal/kA;)V", new long[]{50,100}, false, null, null);
        Function<Integer,Object> levels = ignored -> blinds;
        for (String line : Files.readAllLines(Path.of(args[1]))) {
            if (line.isBlank()) continue;
            String[] p = line.split("\t", -1);
            if (p.length != 14 || Integer.parseInt(p[2]) != 1) throw new IllegalArgumentException("Only the 14-field local ICM terminal protocol is accepted");
            int mode = Integer.parseInt(p[3]); long[] initial = longs(p[4]), end = longs(p[5]), bits = longs(p[9]);
            double[] payouts = doubles(p[6]), heads = doubles(p[7]); double alpha = Double.parseDouble(p[8]);
            int n = initial.length; int[][] killers = new int[n][]; int[] active = new int[n];
            for (int i=0; i<n; i++) {
                active[i]=i;
                if (bits[i] != 0) { int k=0; killers[i]=new int[Long.bitCount(bits[i])]; for(int j=0;j<n;j++) if((bits[i]&(1L<<j))!=0) killers[i][k++]=j; }
            }
            Object outcome = make("lF", "([J[IZ[[ILjava/util/List;)V", end, active, false, killers, null);
            String contextName = mode==0 ? "lc" : mode==1 ? "lj" : "lk";
            Object context = mode==0 ? make("lc", "([JLjava/util/function/Function;IZ)V", initial, levels, 0, false)
                : mode==1 ? make("lj", "([JLjava/util/function/Function;IZD)V", initial, levels, 0, false, heads[0])
                : make("lk", "([JLjava/util/function/Function;IZ[DD)V", initial, levels, 0, false, heads, alpha);
            Object evaluator = mode==0
                ? make("kE", "(Lnet/holdemresources/internal/kW;)V", make("kW", "([D)V", (Object)payouts))
                : make("ll", "([D)V", (Object)payouts);
            String evaluatorName = mode==0 ? "kE" : "ll";
            double[] baseline = (double[])call(evaluatorName, "(Lnet/holdemresources/internal/kG;)[D", evaluator, context);
            double[] total = (double[])call(evaluatorName, "(Lnet/holdemresources/internal/kG;Lnet/holdemresources/internal/lE;)[D", evaluator, context, outcome);
            double[] immediate = (double[])call("kC", "(Lnet/holdemresources/internal/kG;Lnet/holdemresources/internal/lE;)[D",
                make("kC", "([D)V", (Object)payouts), context, outcome);
            double[] bounty = mode==0 ? new double[n] : (double[])call(contextName, "(Lnet/holdemresources/internal/lE;)[D", context, outcome);
            Object next = call(contextName, "(Lnet/holdemresources/internal/lE;)Lnet/holdemresources/internal/kH;", context, outcome);
            int[] mapping = (int[])field(next, int[].class);
            Object nextContext = field(next, cls("kG"));
            double[] remaining = new double[n];
            if (mode!=0) {
                MethodHandle fullHead = MethodHandles.publicLookup().findVirtual(cls(contextName), "b", MethodType.methodType(double.class, int.class));
                for(int i=0;i<n;i++) if(mapping[i]>=0) remaining[i]=(double)fullHead.invoke(nextContext, mapping[i]);
            }
            System.out.println("{\"kind\":\"case\",\"id\":\"" + p[0] + "\",\"total\":" + Arrays.toString(total) +
                ",\"baseline\":" + Arrays.toString(baseline) + ",\"immediate_prizes\":" + Arrays.toString(subtract(immediate,bounty)) +
                ",\"immediate_bounties\":" + Arrays.toString(bounty) + ",\"remaining_bounties\":" + Arrays.toString(remaining) +
                ",\"future_equities\":" + Arrays.toString(subtract(total,immediate)) + ",\"survivor_mapping\":" + Arrays.toString(mapping) + "}");
        }
    }
}
