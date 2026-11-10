import java.io.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import java.util.jar.*;

/** Bounded numerical oracle. No application classes, resources, GUI or solver. */
public final class OriginalMttProbe {
    static String hash(byte[] b) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(b));
    }
    static final class Isolated extends ClassLoader {
        final Map<String,byte[]> bytes = new TreeMap<>();
        Isolated(Path main, Path quant, Path commons) throws Exception {
            super(ClassLoader.getPlatformClassLoader());
            if (!hash(Files.readAllBytes(quant)).equals("40f8865f741e4a23b40771b829d3812cb3b80759901538b7cfeee15b345ee973")
                || !hash(Files.readAllBytes(commons)).equals("359b55232d2d39b5ba9caf8956dc1bbe9ba92e89cb87303dba1aba6cd33c2574"))
                throw new IllegalArgumentException("Unreviewed numerical dependency artifact");
            add(main, List.of("net.holdemresources.internal.lg", "net.holdemresources.internal.kV"));
            add(commons, List.of("org.apache.commons.lang3.ArrayUtils"));
            add(quant, List.of("org.jquantlib.QL", "org.jquantlib.lang.exceptions.LibraryException",
                "org.jquantlib.math.Constants", "org.jquantlib.math.ErrorFunction", "org.jquantlib.math.Ops$DoubleOp",
                "org.jquantlib.math.distributions.Derivative", "org.jquantlib.math.distributions.NormalDistribution",
                "org.jquantlib.math.distributions.CumulativeNormalDistribution", "org.jquantlib.math.integrals.Integrator",
                "org.jquantlib.math.integrals.KronrodIntegral", "org.jquantlib.math.integrals.GaussKronrodNonAdaptive"));
        }
        void add(Path path, List<String> names) throws Exception {
            System.out.println("{\"kind\":\"artifact\",\"file\":\""+path.getFileName()+"\",\"sha256\":\""+hash(Files.readAllBytes(path))+"\"}");
            try (JarFile jar = new JarFile(path.toFile())) {
                for (String name : names) bytes.put(name, jar.getInputStream(jar.getJarEntry(name.replace('.', '/')+".class")).readAllBytes());
            }
        }
        protected Class<?> findClass(String name) throws ClassNotFoundException {
            byte[] b = bytes.get(name);
            if (b == null) throw new ClassNotFoundException("Outside audited numerical allowlist: "+name);
            try { System.out.println("{\"kind\":\"class\",\"name\":\""+name+"\",\"sha256\":\""+hash(b)+"\"}"); }
            catch (Exception e) { throw new ClassNotFoundException(name,e); }
            return defineClass(name,b,0,b.length);
        }
        public java.net.URL getResource(String name) { throw new SecurityException("No resource access: "+name); }
        public InputStream getResourceAsStream(String name) { throw new SecurityException("No resource access: "+name); }
    }
    static double[] vector(String s) {
        return s.isEmpty() ? new double[0] : Arrays.stream(s.split(",")).mapToDouble(Double::parseDouble).toArray();
    }
    static String jsonVector(double[] values) {
        StringJoiner result = new StringJoiner(",", "[", "]");
        for (double x : values) result.add(Double.isFinite(x) ? Double.toString(x) : "\""+x+"\"");
        return result.toString();
    }
    public static void main(String[] args) throws Exception {
        Path main = Path.of(args[0]);
        if (!hash(Files.readAllBytes(main)).equals("25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43"))
            throw new IllegalArgumentException("Unreviewed main artifact");
        Isolated loader = new Isolated(main,Path.of(args[1]),Path.of(args[2]));
        Class<?> cls = Class.forName("net.holdemresources.internal.lg",true,loader);
        Method evaluate = cls.getMethod("a",double[].class);
        for (String line : Files.readAllLines(Path.of(args[3]))) {
            if (line.isBlank()) continue;
            String[] fields = line.split("\t",-1);
            double[] table=vector(fields[1]), prizes=vector(fields[2]), outside=vector(fields[3]);
            Object instance = cls.getConstructor(double[].class,double[].class).newInstance(prizes,outside);
            long start = System.nanoTime();
            try {
                double[] values = (double[])evaluate.invoke(instance,(Object)table);
                System.out.println("{\"kind\":\"case\",\"id\":\""+fields[0]+"\",\"values\":"+jsonVector(values)+",\"nanoseconds\":"+(System.nanoTime()-start)+"}");
            } catch (InvocationTargetException e) {
                System.out.println("{\"kind\":\"case\",\"id\":\""+fields[0]+"\",\"error\":\""+e.getCause().getClass().getName()+"\"}");
            }
        }
    }
}
