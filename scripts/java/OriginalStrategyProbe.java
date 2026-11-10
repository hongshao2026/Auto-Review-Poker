import java.io.IOException;
import java.lang.invoke.MethodType;
import java.lang.reflect.Array;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/**
 * Isolated original-bytecode strategy probe. Compile with the JDK alone.
 * This source has NOT been executed by its authoring agent.
 *
 * Usage: java -cp <probe-classes> OriginalStrategyProbe <main.jar> <rng-client-api.jar>
 * It never starts HRC, reads a license, modifies target files, opens a socket,
 * creates a worker thread, or loads UI/OSGi/application classes. Original classes
 * are loaded through a strict allow-list and platform-parent ClassLoader.
 * JSONL goes to stdout; a failed numeric comparison throws after emitting its row.
 */
public final class OriginalStrategyProbe {
    private static final String INTERNAL = "net.holdemresources.internal.";
    private static final String RNG = "org.apache.commons.rng.UniformRandomProvider";
    private static final String EXPECTED_MAIN_SHA256 =
        "25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43";
    private static final Set<String> ALLOWED_INTERNAL = Set.of(
        "mE", "mA", "mt", "mx", "my", "ma", "mu", "mv"
    );
    private static int checks = 0;

    private static final class IsolatedLoader extends ClassLoader implements AutoCloseable {
        private final ZipFile main;
        private final ZipFile rng;
        private final List<String> loaded = new ArrayList<>();

        IsolatedLoader(Path mainPath, Path rngPath) throws IOException {
            super(ClassLoader.getPlatformClassLoader());
            main = new ZipFile(mainPath.toFile());
            rng = new ZipFile(rngPath.toFile());
        }

        @Override protected Class<?> loadClass(String name, boolean resolve) throws ClassNotFoundException {
            synchronized (getClassLoadingLock(name)) {
                Class<?> found = findLoadedClass(name);
                if (found == null) {
                    if (name.startsWith("java.") || name.startsWith("javax.")
                            || name.startsWith("jdk.") || name.startsWith("sun.")) {
                        found = super.loadClass(name, false);
                    } else {
                        found = findClass(name);
                    }
                }
                if (resolve) resolveClass(found);
                return found;
            }
        }

        @Override protected Class<?> findClass(String name) throws ClassNotFoundException {
            ZipFile jar;
            if (name.equals(RNG)) {
                jar = rng;
            } else if (name.startsWith(INTERNAL)
                    && ALLOWED_INTERNAL.contains(name.substring(INTERNAL.length()))) {
                jar = main;
            } else {
                throw new ClassNotFoundException("DENIED by probe allow-list: " + name);
            }
            String member = name.replace('.', '/') + ".class";
            ZipEntry entry = jar.getEntry(member);
            if (entry == null) throw new ClassNotFoundException("Missing exact-case member: " + member);
            try {
                byte[] bytes = jar.getInputStream(entry).readAllBytes();
                emit(row("kind", "loaded_class", "class", name, "jar", jar.getName(),
                         "member", member, "sha256", sha256(bytes), "bytes", bytes.length));
                loaded.add(name);
                return defineClass(name, bytes, 0, bytes.length);
            } catch (IOException error) {
                throw new ClassNotFoundException(member, error);
            }
        }

        @Override public void close() throws IOException {
            try { main.close(); } finally { rng.close(); }
        }
    }

    /** Match the full JVM descriptor, including return type. */
    private static Method exact(Class<?> owner, String name, String descriptor) {
        Method result = null;
        for (Method method : owner.getDeclaredMethods()) {
            String candidate = MethodType.methodType(method.getReturnType(), method.getParameterTypes())
                .toMethodDescriptorString();
            if (method.getName().equals(name) && candidate.equals(descriptor)) {
                if (result != null) throw new IllegalStateException("Ambiguous exact method");
                result = method;
            }
        }
        if (result == null) throw new IllegalArgumentException(owner.getName()+"."+name+descriptor);
        result.setAccessible(true);
        return result;
    }

    private static double[] raw(Object store, Class<?> mt) throws ReflectiveOperationException {
        for (Field field : mt.getDeclaredFields()) {
            if (field.getName().equals("a") && field.getType().equals(double[].class)) {
                field.setAccessible(true);
                return ((double[]) field.get(store)).clone();
            }
        }
        throw new NoSuchFieldException("mt.a:[D");
    }

    private static void compare(String id, Map<String,Object> input, double[] actual, double[] expected) {
        boolean pass = actual.length == expected.length;
        double maxError = 0;
        if (pass) {
            for (int i=0; i<actual.length; i++) {
                if (!Double.isFinite(actual[i])) { pass=false; break; }
                maxError = Math.max(maxError, Math.abs(actual[i]-expected[i]));
                if (Math.abs(actual[i]-expected[i]) > 1e-12) pass=false;
            }
        }
        emit(row("kind","numeric_check","id",id,"input",input,"expected",expected,
                 "actual",actual,"max_abs_error",maxError,"pass",pass));
        checks++;
        if (!pass) throw new AssertionError("Original-bytecode mismatch: " + id);
    }

    private static void update(Object store, Object scratch, Class<?> owner, double[] p,
                               double[] q, double w, double z) throws ReflectiveOperationException {
        double[] buffer = {p[0],p[1],q[0],q[1]};
        exact(owner,"a","(Lnet/holdemresources/internal/ma;[DIIDD)V")
            .invoke(store,scratch,buffer,0,0,w,z);
    }

    private static Map<String,Object> updateInput(String cls, int step, double[] p,
                                                 double[] q, double w, double z) {
        return row("class",INTERNAL+cls,"descriptor","(Lnet/holdemresources/internal/ma;[DIIDD)V",
                   "bucket",0,"step",step,"p",p,"Q",q,"w",w,"z",z,"rng_nextInt",0);
    }

    private static void updates(IsolatedLoader loader) throws Exception {
        Class<?> rngInterface = loader.loadClass(RNG);
        Object zeroRng = Proxy.newProxyInstance(loader,new Class<?>[]{rngInterface},(proxy,method,args)-> {
            if (method.getName().equals("nextInt") && method.getParameterCount()==0) return 0;
            if (method.getDeclaringClass()==Object.class) {
                return switch(method.getName()) {
                    case "toString" -> "ProbeNextIntZero";
                    case "hashCode" -> System.identityHashCode(proxy);
                    case "equals" -> proxy==args[0];
                    default -> throw new UnsupportedOperationException(method.toString());
                };
            }
            throw new UnsupportedOperationException("Unexpected RNG method: "+method);
        });
        Class<?> ma = loader.loadClass(INTERNAL+"ma");
        Constructor<?> scratchConstructor = ma.getDeclaredConstructor(rngInterface);
        scratchConstructor.setAccessible(true);
        Object scratch = scratchConstructor.newInstance(zeroRng);
        Class<?> mt = loader.loadClass(INTERNAL+"mt");
        double[] p1={.25,.75}, q1={4,-2}, p2={.5,.5}, q2={2,6};

        Class<?> mE = loader.loadClass(INTERNAL+"mE");
        for (double z : new double[]{0,1,100}) {
            Object store=mE.getDeclaredConstructor(int.class,int.class).newInstance(1,2);
            update(store,scratch,mE,p1,q1,1,z);
            compare("mE.z"+z+".step1.raw",updateInput("mE",1,p1,q1,1,z),raw(store,mt),
                    new double[]{1,4.5,-1.5,1,.25,.75});
            update(store,scratch,mE,p2,q2,1,z);
            compare("mE.z"+z+".step2.raw",updateInput("mE",2,p2,q2,1,z),raw(store,mt),
                    new double[]{2,.5,2.5,3,1.25,1.75});
            compare("mE.z"+z+".average",row("method","mt.a(I)[D","bucket",0),
                    (double[])exact(mt,"a","(I)[D").invoke(store,0),new double[]{5.0/12,7.0/12});
            compare("mE.z"+z+".relative_EV",row("method","mt.b(I)[D","bucket",0),
                    (double[])exact(mt,"b","(I)[D").invoke(store,0),new double[]{0,2.0/3});
        }
        Object half=mE.getDeclaredConstructor(int.class,int.class).newInstance(1,2);
        update(half,scratch,mE,p1,q1,.5,100);
        compare("mE.w_half.avg_not_weighted",updateInput("mE",1,p1,q1,.5,100),raw(half,mt),
                new double[]{1,2.25,-.75,.5,.25,.75});
        Object noUpdate=mE.getDeclaredConstructor(int.class,int.class).newInstance(1,2);
        update(noUpdate,scratch,mE,p1,q1,0,100);
        compare("mE.w_zero.no_update",updateInput("mE",1,p1,q1,0,100),raw(noUpdate,mt),new double[6]);

        Class<?> mA=loader.loadClass(INTERNAL+"mA");
        for (double z : new double[]{0,1}) {
            Object store=mA.getDeclaredConstructor(int.class,int.class).newInstance(1,2);
            update(store,scratch,mA,p1,q1,1,z);
            compare("mA.z"+z+".step1.raw",updateInput("mA",1,p1,q1,1,z),raw(store,mt),
                    new double[]{1,.25*z,.75*z,4.5,-1.5});
            update(store,scratch,mA,p2,q2,1,z);
            compare("mA.z"+z+".step2.raw",updateInput("mA",2,p2,q2,1,z),raw(store,mt),
                    new double[]{2,1.25*z,1.75*z,.5,2.5});
            compare("mA.z"+z+".bucket_current_policy",row("method","mt.a(I)[D","bucket",0),
                    (double[])exact(mt,"a","(I)[D").invoke(store,0),new double[]{1.0/6,5.0/6});
            compare("mA.z"+z+".global_average",row("method","mA.b()[D"),
                    (double[])exact(mA,"b","()[D").invoke(store),
                    z==0?new double[]{.5,.5}:new double[]{5.0/12,7.0/12});
        }
    }

    private static void normalization(IsolatedLoader loader) throws Exception {
        Class<?> mv=loader.loadClass(INTERNAL+"mv");
        Method method=exact(mv,"a","([DIIZ[DI)V");
        double[][] inputs={{4.5,-1.5},{0,0},{-5,-2,-1},{9,-8},{100,-3,-5},
                           {100,-5,-5},{100,-3,-5,-3},{-2,3,1}};
        boolean[] restricted={false,false,false,true,true,true,true,false};
        double[][] expected={{1,0},{.5,.5},{1.0/3,1.0/3,1.0/3},{0,1},{0,1,0},
                             {0,.5,.5},{0,1,0,0},{0,.75,.25}};
        for(int i=0;i<inputs.length;i++) {
            double[] output=new double[inputs[i].length];
            method.invoke(null,inputs[i],0,inputs[i].length,restricted[i],output,0);
            compare("mv.normalization."+i,row("method","mv.a([DIIZ[DI)V","values",inputs[i],
                    "restricted_action_zero",restricted[i]),output,expected[i]);
        }
    }

    public static void main(String[] args) throws Exception {
        if(args.length!=2) throw new IllegalArgumentException(
            "Arguments: <original main JAR> <commons-rng-client-api-1.6.jar>");
        Path main=Path.of(args[0]).toAbsolutePath().normalize();
        Path rng=Path.of(args[1]).toAbsolutePath().normalize();
        String actualHash=sha256(Files.readAllBytes(main));
        if(!actualHash.equals(EXPECTED_MAIN_SHA256)) throw new IllegalArgumentException(
            "Main JAR identity mismatch; refusing to test unreviewed bytes: "+actualHash);
        emit(row("kind","probe_identity","main_jar",main.toString(),"main_sha256",actualHash,
                 "rng_jar",rng.toString(),"rng_sha256",sha256(Files.readAllBytes(rng)),
                 "parent_loader","platform","purpose","original bytecode deterministic numerical checks"));
        try(IsolatedLoader loader=new IsolatedLoader(main,rng)) {
            normalization(loader);
            updates(loader);
            emit(row("kind","summary","checks",checks,"all_passed",true,
                     "loaded_classes",loader.loaded,"scope","pure storage updates and normalization only"));
        }
    }

    private static String sha256(byte[] value) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value)); }
        catch(Exception impossible) { throw new IllegalStateException(impossible); }
    }
    private static Map<String,Object> row(Object... pairs) {
        Map<String,Object> result=new LinkedHashMap<>();
        for(int i=0;i<pairs.length;i+=2) result.put((String)pairs[i],pairs[i+1]);
        return result;
    }
    private static void emit(Map<String,Object> value) { System.out.println(json(value)); }
    private static String json(Object value) {
        if(value==null) return "null";
        if(value instanceof String s) return "\""+s.replace("\\","\\\\").replace("\"","\\\"")
            .replace("\n","\\n").replace("\r","\\r").replace("\t","\\t")+"\"";
        if(value instanceof Number n) return Double.isFinite(n.doubleValue())?n.toString():json(n.toString());
        if(value instanceof Boolean b) return b.toString();
        if(value instanceof Map<?,?> map) {
            List<String> parts=new ArrayList<>();
            map.forEach((k,v)->parts.add(json(k.toString())+":"+json(v)));
            return "{"+String.join(",",parts)+"}";
        }
        if(value instanceof Iterable<?> iterable) {
            List<String> parts=new ArrayList<>();
            iterable.forEach(v->parts.add(json(v)));
            return "["+String.join(",",parts)+"]";
        }
        if(value.getClass().isArray()) {
            List<String> parts=new ArrayList<>();
            for(int i=0;i<Array.getLength(value);i++) parts.add(json(Array.get(value,i)));
            return "["+String.join(",",parts)+"]";
        }
        throw new IllegalArgumentException("Unsupported JSON value: "+value.getClass());
    }
}
