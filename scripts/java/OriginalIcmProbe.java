import java.io.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import java.util.jar.*;

/** Executes only the unmodified kV/kU/kW original classfiles, not HRC's application. */
public final class OriginalIcmProbe {
    static final class Isolated extends ClassLoader {
        final Map<String,byte[]> bytes=new HashMap<>();
        Isolated(Path path) throws Exception {
            super(ClassLoader.getPlatformClassLoader());
            try(JarFile jar=new JarFile(path.toFile())) {
                for(String shortName:List.of("kV","kU","kW")) {
                    String name="net.holdemresources.internal."+shortName;
                    byte[] b=jar.getInputStream(jar.getJarEntry(name.replace('.','/')+".class")).readAllBytes();
                    bytes.put(name,b);
                    System.out.println("{\"kind\":\"class\",\"name\":\""+name+"\",\"sha256\":\""+HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(b))+"\"}");
                }
            }
        }
        protected Class<?> findClass(String name) throws ClassNotFoundException {
            byte[] b=bytes.get(name);
            if(b==null) throw new ClassNotFoundException("Outside reviewed allowlist: "+name);
            return defineClass(name,b,0,b.length);
        }
    }
    static double[] vector(String s) { return Arrays.stream(s.split(",")).mapToDouble(Double::parseDouble).toArray(); }
    public static void main(String[] args) throws Exception {
        Path jar=Path.of(args[0]);
        String hash=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(jar)));
        if(!hash.equals("25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43")) throw new IllegalArgumentException("Unreviewed artifact hash "+hash);
        System.out.println("{\"kind\":\"metadata\",\"jar_sha256\":\""+hash+"\",\"java\":\""+System.getProperty("java.version")+"\"}");
        Class<?> cls=Class.forName("net.holdemresources.internal.kW",true,new Isolated(jar));
        Method vector=null,matrix=null;
        for(Method m:cls.getMethods()) if(m.getName().equals("a") && Arrays.equals(m.getParameterTypes(),new Class<?>[]{double[].class})) {
            if(m.getReturnType()==double[].class) vector=m;
            if(m.getReturnType()==double[][].class) matrix=m;
        }
        if(vector==null || matrix==null) throw new AssertionError("Expected descriptors missing");
        for(String line:Files.readAllLines(Path.of(args[1]))) {
            if(line.isBlank()) continue;
            String[] parts=line.split("\\t");
            double[] stacks=vector(parts[1]), prizes=vector(parts[2]);
            Object instance=cls.getConstructor(double[].class).newInstance((Object)prizes);
            double[] values=(double[])vector.invoke(instance,(Object)stacks);
            double[][] ranks=(double[][])matrix.invoke(instance,(Object)stacks);
            System.out.println("{\"kind\":\"case\",\"id\":\""+parts[0]+"\",\"stacks\":"+Arrays.toString(stacks)+",\"prizes\":"+Arrays.toString(prizes)+",\"values\":"+Arrays.toString(values)+",\"rank_values\":"+Arrays.deepToString(ranks)+"}");
        }
    }
}
