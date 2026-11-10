import java.io.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import java.util.jar.*;

/** Audited allowlist: card bitmask helpers, byte decoding, seven-card evaluator and its lookup. */
public final class OriginalCardsProbe {
    static final String RESOURCE="net/holdemresources/gamerules/handeval/data/lookup7card.dat.gz";
    static final class Isolated extends ClassLoader {
        final Map<String,byte[]> bytes=new HashMap<>();
        byte[] lookup;
        Isolated(Path path) throws Exception {
            super(ClassLoader.getPlatformClassLoader());
            try(JarFile jar=new JarFile(path.toFile())) {
                for(String shortName:List.of("og","oD","lv","lt")) {
                    String name="net.holdemresources.internal."+shortName;
                    byte[] b=jar.getInputStream(jar.getJarEntry(name.replace('.','/')+".class")).readAllBytes();
                    bytes.put(name,b); emitHash("class",name,b);
                }
                lookup=jar.getInputStream(jar.getJarEntry(RESOURCE)).readAllBytes();
                emitHash("resource",RESOURCE,lookup);
            }
        }
        protected Class<?> findClass(String name) throws ClassNotFoundException {
            byte[] b=bytes.get(name);
            if(b==null) throw new ClassNotFoundException("Outside reviewed allowlist: "+name);
            return defineClass(name,b,0,b.length);
        }
        public InputStream getResourceAsStream(String name) {
            return name.equals(RESOURCE)? new ByteArrayInputStream(lookup):null;
        }
    }
    static void emitHash(String kind,String name,byte[] b) throws Exception {
        System.out.println("{\"kind\":\""+kind+"\",\"name\":\""+name+"\",\"sha256\":\""+HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(b))+"\"}");
    }
    static Method method(Class<?> c,String name,Class<?> ret,Class<?>... params) {
        for(Method m:c.getDeclaredMethods()) if(m.getName().equals(name) && m.getReturnType()==ret && Arrays.equals(m.getParameterTypes(),params)) return m;
        throw new AssertionError("Missing descriptor for "+c+"."+name+" "+ret);
    }
    public static void main(String[] args) throws Exception {
        Path jar=Path.of(args[0]);
        String hash=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(jar)));
        if(!hash.equals("25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43")) throw new IllegalArgumentException("Unreviewed artifact");
        Isolated loader=new Isolated(jar);
        Class<?> og=Class.forName("net.holdemresources.internal.og",true,loader),lv=Class.forName("net.holdemresources.internal.lv",true,loader),od=Class.forName("net.holdemresources.internal.oD",true,loader);
        Method canonical=method(og,"a",long.class,long.class),permutation=method(og,"b",int[].class,long.class),apply=method(og,"a",long.class,long.class,int[].class),evaluate=method(lv,"a",short.class,long.class);
        Method shortRead=method(od,"a",short.class,byte[].class,int.class),intRead=method(od,"a",int.class,byte[].class,int.class),longRead=method(od,"a",long.class,byte[].class,int.class);
        for(String line:Files.readAllLines(Path.of(args[1]))) {
            String[] p=line.split("\\t"); long mask=Long.parseLong(p[1]);
            long canon=(long)canonical.invoke(null,mask); int[] perm=(int[])permutation.invoke(null,mask);
            long applied=(long)apply.invoke(null,mask,perm);
            String rank=Long.bitCount(mask)==7?evaluate.invoke(null,mask).toString():"null";
            System.out.println("{\"kind\":\"cards\",\"id\":\""+p[0]+"\",\"mask\":"+mask+",\"canonical\":"+canon+",\"permutation\":"+Arrays.toString(perm)+",\"applied\":"+applied+",\"rank\":"+rank+"}");
        }
        Random rng=new Random(20261104L);
        for(int i=0;i<32;i++) {
            byte[] data=new byte[13]; rng.nextBytes(data); int offset=i%6;
            System.out.println("{\"kind\":\"endian\",\"hex\":\""+HexFormat.of().formatHex(data)+"\",\"offset\":"+offset+",\"short\":"+shortRead.invoke(null,data,offset)+",\"int\":"+intRead.invoke(null,data,offset)+",\"long\":"+longRead.invoke(null,data,offset)+"}");
        }
    }
}
