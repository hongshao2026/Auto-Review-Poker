import java.io.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.nio.*;
import java.security.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.*;
import java.util.jar.*;

/** Original numerical FGS only: reviewed game math, pinned chance tables/cache dependency. */
public final class OriginalFgsProbe {
    static final String P = "net.holdemresources.internal.";
    static String hash(byte[] b) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(b));
    }
    static final class Isolated extends ClassLoader {
        final Map<String,byte[]> classes = new TreeMap<>(), resources = new TreeMap<>();
        final Set<String> loaded = new TreeSet<>();
        Isolated(Path plugins) throws Exception {
            super(ClassLoader.getPlatformClassLoader());
            Set<String> main = new HashSet<>();
            for (String n : ("kX kY kZ la lb lc ld le lj lk ll kB kG kH kI kK kC kE kV kW kU kF ky kz kA lC ly lz lA lK lL lD lH lI lJ lE lF lG qI qG qR qS qT qD qE rK rL rF rG rH rI rJ oG lN lM lp").split(" ")) main.add(P+n);
            add(plugins.resolve("net.holdemresources.calculator_4.1.0.202603231401.jar"),
                "25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43", main,
                Set.of("net/holdemresources/sngnash/data/handranking/necombined.range"));
            add(plugins.resolve("net.holdemresources.preflopdata.holdem_1.4.1.jar"),
                "721c77d43459c6573b0b4aeb50f259f03d964991a73b80ebeb7a68777111ffa2", null,
                Set.of("net/holdemresources/handevaluation/preflop/hands/data/2wh.dat", "net/holdemresources/handevaluation/preflop/hands/data/3wh.dat"));
            add(plugins.resolve("com.google.guava_33.4.0.jre.jar"),
                "9ceecdbc1c345a0f8c0822337445efc54940d33b3f57e81ddc90882db42d763f", null, Set.of());
            add(plugins.resolve("com.google.guava.failureaccess_1.0.2.jar"),
                "8a8f81cf9b359e3f6dfa691a1e776985c061ef2f223c9b2c80753e1b458e8064", null, Set.of());
        }
        void add(Path jarPath, String expected, Set<String> names, Set<String> resourceNames) throws Exception {
            String observed = hash(Files.readAllBytes(jarPath));
            if (!observed.equals(expected)) throw new IllegalArgumentException("Unreviewed artifact: "+jarPath);
            System.out.println("{\"kind\":\"artifact\",\"file\":\""+jarPath.getFileName()+"\",\"sha256\":\""+observed+"\"}");
            try (JarFile jar = new JarFile(jarPath.toFile())) {
                for (JarEntry entry : Collections.list(jar.entries())) {
                    String member = entry.getName();
                    if (member.endsWith(".class")) {
                        String name = member.substring(0,member.length()-6).replace('/','.');
                        if (names == null || names.contains(name)) classes.put(name,jar.getInputStream(entry).readAllBytes());
                    } else if (resourceNames.contains(member)) {
                        if (Files.exists(Path.of(member))) throw new SecurityException("Working-directory resource shadow: "+member);
                        byte[] b = jar.getInputStream(entry).readAllBytes();
                        resources.put(member,b);
                        System.out.println("{\"kind\":\"resource\",\"name\":\""+member+"\",\"length\":"+b.length+",\"sha256\":\""+hash(b)+"\"}");
                    }
                }
            }
        }
        protected Class<?> findClass(String name) throws ClassNotFoundException {
            byte[] b=classes.get(name);
            if(b==null) throw new ClassNotFoundException("Outside numerical allowlist: "+name);
            loaded.add(name);
            return defineClass(name,b,0,b.length);
        }
        public InputStream getResourceAsStream(String name) {
            byte[] b=resources.get(name);
            if(b==null) throw new SecurityException("Outside chance-resource allowlist: "+name);
            return new ByteArrayInputStream(b);
        }
        public java.net.URL getResource(String name) { throw new SecurityException("No general resource lookup: "+name); }
    }
    static Method method(Class<?> cls, String name, Class<?> returns, Class<?>... params) {
        for(Method m:cls.getMethods()) if(m.getName().equals(name) && m.getReturnType()==returns && Arrays.equals(m.getParameterTypes(),params)) return m;
        throw new IllegalArgumentException("Missing descriptor: "+cls+" "+name+" "+returns);
    }
    static Field field(Class<?> cls, Class<?> type) throws Exception {
        for(Field f:cls.getDeclaredFields()) if(f.getName().equals("a") && f.getType()==type) {f.setAccessible(true);return f;}
        throw new IllegalArgumentException("Missing field: "+cls+" "+type);
    }
    static long[] longs(String text) { return Arrays.stream(text.split(",")).mapToLong(Long::parseLong).toArray(); }
    static double[] doubles(String text) { return Arrays.stream(text.split(",")).mapToDouble(Double::parseDouble).toArray(); }
    static void numericHash(String name,double[] values) throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256");
        ByteBuffer block=ByteBuffer.allocate(65536).order(ByteOrder.LITTLE_ENDIAN);
        for(double value:values) {
            if(block.remaining()<8) {digest.update(block.array());block.clear();}
            block.putDouble(value);
        }
        digest.update(block.array(),0,block.position());
        System.out.println("{\"kind\":\"chance_hash\",\"name\":\""+name+"\",\"doubles\":"+values.length+",\"sha256\":\""+HexFormat.of().formatHex(digest.digest())+"\"}");
    }
    static void outcomes(String id,Object context,Object base,Object fgs,Function<String,Class<?>> cls) throws Exception {
        Class<?> game=cls.apply("kG"),outcome=cls.apply("lE");
        int n=((long[])method(game,"a",long[].class).invoke(context)).length;
        Object settlement=method(game,"a",cls.apply("lH")).invoke(context);
        List<int[]> subsets=new ArrayList<>();
        for(int a=0;a<n;++a)subsets.add(new int[]{a});
        for(int a=0;a<n;++a)for(int b=a+1;b<n;++b)subsets.add(new int[]{a,b});
        for(int a=0;a<n;++a)for(int b=a+1;b<n;++b)for(int c=b+1;c<n;++c)subsets.add(new int[]{a,b,c});
        for(int[] participants:subsets) {
            Object terminalState=method(cls.apply("lL"),"a",cls.apply("lK"),game,int[].class).invoke(null,context,participants);
            Object[] terminals=(Object[])method(cls.apply("lH"),"a",Array.newInstance(outcome,0).getClass(),cls.apply("lK")).invoke(settlement,terminalState);
            for(int r=0;r<terminals.length;++r) {
                Object terminal=terminals[r];long[] stacks=(long[])method(outcome,"a",long[].class).invoke(terminal);
                int[][] winners=(int[][])method(outcome,"a",int[][].class).invoke(terminal);int[] masks=new int[n];
                for(int i=0;i<n;++i)if(winners[i]!=null)for(int winner:winners[i])masks[i]|=1<<winner;
                boolean tied=(boolean)method(outcome,"a",boolean.class).invoke(terminal);
                Object transition=method(game,"a",cls.apply("kH"),outcome).invoke(context,terminal);
                Object next=field(cls.apply("kH"),game).get(transition);
                long[] nextStacks=(long[])method(game,"a",long[].class).invoke(next);
                double[] heads=new double[cls.apply("kI").isInstance(next)?nextStacks.length:0];
                for(int i=0;i<heads.length;++i)heads[i]=(double)method(cls.apply("kI"),"b",double.class,int.class).invoke(next,i);
                double[] values=(double[])method(cls.apply("kK"),"a",double[].class,game,outcome).invoke(base,context,terminal);
                double[] future=(double[])method(cls.apply("kK"),"a",double[].class,game,outcome).invoke(fgs,context,terminal);
                System.out.println("{\"kind\":\"outcome\",\"id\":\""+id+"\",\"participants\":"+Arrays.toString(participants)+",\"result\":"+r
                    +",\"stacks\":"+Arrays.toString(stacks)+",\"winner_masks\":"+Arrays.toString(masks)+",\"tied\":"+tied
                    +",\"next_stacks\":"+Arrays.toString(nextStacks)+",\"mapping\":"+Arrays.toString((int[])field(cls.apply("kH"),int[].class).get(transition))
                    +",\"next_skip_sb\":"+method(game,"a",boolean.class).invoke(next)+",\"next_bounties\":"+Arrays.toString(heads)+",\"ordinary_values\":"+Arrays.toString(values)+",\"fgs_values\":"+Arrays.toString(future)+"}");
            }
        }
    }
    public static void main(String[] args) throws Exception {
        Isolated loader = new Isolated(Path.of(args[0]));
        Function<String,Class<?>> cls = n -> {try{return Class.forName(P+n,true,loader);}catch(Exception e){throw new RuntimeException(e);}};
        Object order = method(cls.apply("rF"),"b",cls.apply("rF")).invoke(null);
        Object two = cls.apply("rK").getConstructor(cls.apply("rF")).newInstance(order);
        Object three = cls.apply("rL").getConstructor(cls.apply("rF")).newInstance(order);
        numericHash("two",(double[])field(cls.apply("rK"),double[].class).get(two));
        numericHash("three",(double[])field(cls.apply("rL"),double[].class).get(three));
        Field marginal=cls.apply("rK").getDeclaredField("b");marginal.setAccessible(true);
        numericHash("marginal",(double[])marginal.get(two));
        Class<?> game=cls.apply("kG"), outcome=cls.apply("lE"), evaluator=cls.apply("kK");
        ForkJoinPool pool = new ForkJoinPool(1);
        try {
            for(String line:Files.readAllLines(Path.of(args[1]))) {
                if(line.isBlank()) continue;
                String[] f=line.split("\t",-1);
                long[] stacks=longs(f[1]), blinds=longs(f[3]);
                double[] prizes=doubles(f[2]);
                int depth=Integer.parseInt(f[4]), depth3=Integer.parseInt(f[5]);
                boolean skip=Boolean.parseBoolean(f[6]), moving=Boolean.parseBoolean(f[7]);
                int ante=f.length>8?Integer.parseInt(f[8]):0, straddle=f.length>9?Integer.parseInt(f[9]):0;
                Object level=cls.apply("ky").getConstructors()[0].newInstance(blinds,moving,cls.apply("kz").getEnumConstants()[ante],cls.apply("kA").getEnumConstants()[straddle]);
                int nextAt=f.length>10?Integer.parseInt(f[10]):-1;
                Object nextLevel=nextAt<0?level:cls.apply("ky").getConstructors()[0].newInstance(longs(f[11]),moving,cls.apply("kz").getEnumConstants()[ante],cls.apply("kA").getEnumConstants()[straddle]);
                Function<Integer,Object> schedule=d->nextAt>=0 && d>=nextAt?nextLevel:level;
                int bountyMode=f.length>12?Integer.parseInt(f[12]):0;
                Object context;
                if(bountyMode==1) context=cls.apply("lj").getConstructor(long[].class,Function.class,int.class,boolean.class,double.class).newInstance(stacks,schedule,0,skip,doubles(f[13])[0]);
                else if(bountyMode==2) context=cls.apply("lk").getConstructor(long[].class,Function.class,int.class,boolean.class,double[].class,double.class).newInstance(stacks,schedule,0,skip,doubles(f[13]),Double.parseDouble(f[14]));
                else context=cls.apply("lc").getConstructor(long[].class,Function.class,int.class,boolean.class).newInstance(stacks,schedule,0,skip);
                Object icm=cls.apply("kW").getConstructor(double[].class).newInstance((Object)prizes);
                Object base=bountyMode==0?cls.apply("kE").getConstructor(cls.apply("kW")).newInstance(icm):cls.apply("ll").getConstructor(double[].class).newInstance((Object)prizes);
                Object immediate=cls.apply("kC").getConstructor(double[].class).newInstance((Object)prizes);
                BiPredicate<Object,Object> predicate=(c,o)->{
                    try{return !(boolean)method(outcome,"a",boolean.class).invoke(o)
                        && ((int)method(cls.apply("lb"),"e",int.class).invoke(c)<depth3 || (int)method(outcome,"a",int.class).invoke(o)<3);}
                    catch(Exception e){throw new RuntimeException(e);}
                };
                long start=System.nanoTime();
                Object fgs=cls.apply("kX").getConstructors()[0].newInstance(pool,immediate,base,predicate,depth,Math.min(Math.max(depth-2,1),4),two,three);
                double[] values=(double[])method(cls.apply("kX"),"a",double[].class,game).invoke(fgs,context);
                System.out.println("{\"kind\":\"fgs\",\"id\":\""+f[0]+"\",\"values\":"+Arrays.toString(values)+",\"nanoseconds\":"+(System.nanoTime()-start)+"}");
                outcomes(f[0],context,base,fgs,cls);
                Object threshold=cls.apply("qI").getConstructor(evaluator,cls.apply("lb")).newInstance(base,context);
                method(cls.apply("qG"),"a",void.class,cls.apply("rK"),cls.apply("rL")).invoke(threshold,two,three);
                Method sweep=method(cls.apply("qI"),"a",void.class), value=method(cls.apply("qG"),"a",double.class,int.class,int.class);
                for(int iteration=0;iteration<=200;iteration++) {
                    if(Set.of(0,1,2,10,50,200).contains(iteration)) {
                        double[] ev=new double[stacks.length];
                        for(int p=0;p<ev.length;p++) ev[p]=(double)value.invoke(threshold,p,0);
                        System.out.println("{\"kind\":\"threshold\",\"id\":\""+f[0]+"\",\"iteration\":"+iteration+",\"values\":"+Arrays.toString(ev)
                            +",\"push\":"+Arrays.toString((int[])field(cls.apply("qG"),int[].class).get(threshold))
                            +",\"call\":"+Arrays.deepToString((int[][])field(cls.apply("qG"),int[][].class).get(threshold))
                            +",\"overcall\":"+Arrays.deepToString((int[][][])field(cls.apply("qG"),int[][][].class).get(threshold))+"}");
                    }
                    if(iteration<200) sweep.invoke(threshold);
                }
            }
        } finally { pool.shutdown(); }
        for(String name:loader.loaded) System.out.println("{\"kind\":\"class\",\"name\":\""+name+"\",\"sha256\":\""+hash(loader.classes.get(name))+"\"}");
    }
}
