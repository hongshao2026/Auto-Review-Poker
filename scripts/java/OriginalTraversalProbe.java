import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.lang.invoke.MethodHandle;
import java.lang.invoke.MethodHandles;
import java.lang.invoke.MethodType;
import java.lang.reflect.Array;
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
import java.util.Random;
import java.util.Set;
import java.util.function.IntBinaryOperator;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/**
 * Original-bytecode preflop traversal fixture. Author compiled but DID NOT RUN.
 *
 * Real HRC: combo/board dealer lu, context lV, node mf, terminal mh, ranking lv,
 * outcome selector me, strategy storage mE, and lX/lY mode factories.
 * Synthetic inputs: a two-action one-node tree; user-defined terminal payoff
 * tables; scripted RNG. This is NOT a full HRC settlement/ICM/full-tree solve.
 * No application, licensing, OSGi, GUI, network or job scheduling is loaded.
 */
public final class OriginalTraversalProbe {
    private static final String P="net.holdemresources.internal.";
    private static final String RNG="org.apache.commons.rng.UniformRandomProvider";
    private static final String JAR_HASH="25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43";
    private static final String TABLE="net/holdemresources/gamerules/handeval/data/lookup7card.dat.gz";
    private static final Set<String> ALLOW=Set.of(
        "mE","mA","mt","mx","my","ma","mu","mv","mf","mj","lU","lR",
        "lA","ly","lz","mh","lS","lK","lC","mi","kG","kM","ky","lH",
        "mk","me","lV","lW","lX","lY","lZ","oj","lu","ls","lv","lE"
    );
    private static int checks;
    private static Loader loader;

    private static final class Loader extends ClassLoader implements AutoCloseable {
        private final ZipFile main, rng;
        final List<String> loaded=new ArrayList<>();
        Loader(Path mainPath,Path rngPath) throws IOException {
            super(ClassLoader.getPlatformClassLoader());
            main=new ZipFile(mainPath.toFile()); rng=new ZipFile(rngPath.toFile());
        }
        @Override protected Class<?> loadClass(String name,boolean resolve) throws ClassNotFoundException {
            synchronized(getClassLoadingLock(name)) {
                Class<?> value=findLoadedClass(name);
                if(value==null) {
                    value=(name.startsWith("java.")||name.startsWith("javax.")||name.startsWith("jdk.")||name.startsWith("sun."))
                        ?super.loadClass(name,false):findClass(name);
                }
                if(resolve) resolveClass(value);
                return value;
            }
        }
        @Override protected Class<?> findClass(String name) throws ClassNotFoundException {
            ZipFile jar;
            if(name.equals(RNG)) jar=rng;
            else if(name.startsWith(P)&&ALLOW.contains(name.substring(P.length()))) jar=main;
            else throw new ClassNotFoundException("DENIED by traversal fixture allow-list: "+name);
            String member=name.replace('.','/')+".class";
            ZipEntry entry=jar.getEntry(member);
            if(entry==null) throw new ClassNotFoundException(member);
            try(InputStream input=jar.getInputStream(entry)) {
                byte[] bytes=input.readAllBytes();
                emit(row("kind","loaded_class","class",name,"member",member,"sha256",hash(bytes),"bytes",bytes.length));
                loaded.add(name);
                return defineClass(name,bytes,0,bytes.length);
            } catch(IOException e) { throw new ClassNotFoundException(member,e); }
        }
        @Override public InputStream getResourceAsStream(String name) {
            if(!name.equals(TABLE)) throw new SecurityException("Unapproved class resource: "+name);
            try {
                ZipEntry entry=main.getEntry(name);
                if(entry==null) throw new IOException("Missing original lookup table");
                byte[] bytes=main.getInputStream(entry).readAllBytes();
                emit(row("kind","loaded_resource","member",name,"sha256",hash(bytes),"bytes",bytes.length));
                return new ByteArrayInputStream(bytes);
            } catch(IOException e) { throw new IllegalStateException(e); }
        }
        @Override public void close() throws IOException { try {main.close();} finally {rng.close();} }
    }

    private static Class<?> cls(String simple) throws ClassNotFoundException {return loader.loadClass(P+simple);}
    private static MethodHandles.Lookup lookup(String simple) throws Exception {
        return MethodHandles.privateLookupIn(cls(simple),MethodHandles.lookup());
    }
    private static MethodType type(String descriptor) {return MethodType.fromMethodDescriptorString(descriptor,loader);}
    private static Object construct(String owner,String descriptor,Object... args) throws Throwable {
        return lookup(owner).findConstructor(cls(owner),type(descriptor)).invokeWithArguments(args);
    }
    private static Object call(String owner,String name,String descriptor,Object instance,Object... args) throws Throwable {
        MethodHandle method=lookup(owner).findVirtual(cls(owner),name,type(descriptor));
        List<Object> values=new ArrayList<>(); values.add(instance); values.addAll(Arrays.asList(args));
        return method.invokeWithArguments(values);
    }
    private static Object stat(String owner,String name,String descriptor,Object... args) throws Throwable {
        return lookup(owner).findStatic(cls(owner),name,type(descriptor)).invokeWithArguments(args);
    }
    private static Object field(String owner,String name,Class<?> type,Object instance) throws Throwable {
        return lookup(owner).findGetter(cls(owner),name,type).invokeWithArguments(instance);
    }
    private static Object staticField(String owner,String name,Class<?> type) throws Throwable {
        return lookup(owner).findStaticGetter(cls(owner),name,type).invokeWithArguments();
    }

    private static final class Script {
        final Random dealRandom;
        final int gatingValue;
        final List<Integer> boundedCalls=new ArrayList<>();
        int unboundedCalls, doubleCalls;
        Script(long seed,int gatingValue) {dealRandom=new Random(seed);this.gatingValue=gatingValue;}
        Object proxy() throws Exception {
            Class<?> rng=loader.loadClass(RNG);
            return Proxy.newProxyInstance(loader,new Class<?>[]{rng},(proxy,method,args)-> {
                if(method.getDeclaringClass()==Object.class) return switch(method.getName()) {
                    case "toString" -> "ScriptedTraversalRng";
                    case "hashCode" -> System.identityHashCode(proxy);
                    case "equals" -> proxy==args[0];
                    default -> throw new UnsupportedOperationException(method.toString());
                };
                if(method.getName().equals("nextInt")&&method.getParameterCount()==0) {
                    unboundedCalls++; return 0; // Force mE cached counter refresh.
                }
                if(method.getName().equals("nextInt")&&method.getParameterCount()==1) {
                    int bound=(Integer)args[0]; boundedCalls.add(bound);
                    return gatingValue>=0?Math.min(gatingValue,bound-1):dealRandom.nextInt(bound);
                }
                if(method.getName().equals("nextDouble")&&method.getParameterCount()==0) {
                    doubleCalls++; return .75; // No epsilon exploration; choose action 1 from [.5,.5].
                }
                throw new UnsupportedOperationException("Unexpected RNG call "+method);
            });
        }
    }

    private record Deal(int[] holes,long[] boards,long holeMask,int[] buckets,int[] ranks,int outcome) {}
    private static Deal deal(long seed) throws Throwable {
        Script script=new Script(seed,-1);
        Object rng=script.proxy();
        int[] holes=new int[2]; long[] boards=new long[4];
        long holeMask=(Long)stat("lu","a","(Lorg/apache/commons/rng/UniformRandomProvider;[I)J",rng,holes);
        long all=(Long)stat("lu","a","(Lorg/apache/commons/rng/UniformRandomProvider;[JJ)J",rng,boards,holeMask);
        long[] comboMasks=(long[])staticField("ls","b",long[].class);
        int[] bucketTable=(int[])staticField("ls","a",int[].class);
        check("deal."+seed+".unique_cards",Long.bitCount(all)==9&&Long.bitCount(holeMask)==4
            &&Long.bitCount(boards[1])==3&&Long.bitCount(boards[2])==4&&Long.bitCount(boards[3])==5
            &&(holeMask&boards[3])==0&&((comboMasks[holes[0]]&comboMasks[holes[1]])==0),
            row("holes",holes,"boards",boards,"hole_mask",holeMask,"all_mask",all));
        int[] buckets={bucketTable[holes[0]],bucketTable[holes[1]]};
        int[] ranks={((Short)stat("lv","a","(J)S",boards[3]|comboMasks[holes[0]])).intValue(),
                     ((Short)stat("lv","a","(J)S",boards[3]|comboMasks[holes[1]])).intValue()};
        int outcome=1+Integer.compare(ranks[1],ranks[0]);
        int actualOutcome=(Integer)stat("me","a","([I[I[I)I",ranks,new int[]{0,1},new int[]{0,1});
        check("deal."+seed+".terminal_index",outcome==actualOutcome,row("ranks",ranks,"expected",outcome,"actual",actualOutcome));
        emit(row("kind","original_deal","seed",seed,"rng","scripted java.util.Random for bounded calls; not default HRC XO_SHI_RO",
                 "holes",holes,"board_masks",boards,"buckets",buckets,"original_lv_ranks",ranks,
                 "mh_table_outcome",outcome,"bounded_rng_calls",script.boundedCalls));
        return new Deal(holes,boards,holeMask,buckets,ranks,outcome);
    }

    private record Fixture(Object root,Object foldLeaf,Object showdownLeaf,Object store) {}
    private static Fixture fixture() throws Throwable {
        Object foldAction=stat("ly","a","(II)Lnet/holdemresources/internal/ly;",0,0);
        Object callAction=stat("ly","a","(IIJZ)Lnet/holdemresources/internal/ly;",0,0,1L,false);
        // The actual kM constructor only stores these four fields. ky/lH are
        // unused in this fixture; mi/mh only ask kG for the player count.
        Object game=construct("kM","([JLnet/holdemresources/internal/ky;ZLnet/holdemresources/internal/lH;)V",
                              new long[]{20,20},null,false,null);
        Object terminalContext=construct("mi","(Lnet/holdemresources/internal/kG;Ljava/util/function/IntBinaryOperator;)V",
                                         game,(IntBinaryOperator)(a,b)->0);
        Object[] leaves=new Object[2];
        for(int folded=0;folded<=1;folded++) {
            // lC is a plain state constructor. actedMask=3 satisfies lC.b()'s
            // normal 'all players have acted' invariant; no state gate is patched.
            Object state=construct("lC","(J[J[J[JIIIIIII)V",0L,new long[]{19,19},new long[]{1,1},
                                   new long[]{0,0},folded,0,3,-1,1,0,3);
            Object terminalState=stat("lK","a","(Lnet/holdemresources/internal/lC;)Lnet/holdemresources/internal/lK;",state);
            Object leaf=construct("mh","(Lnet/holdemresources/internal/mf;Ljava/util/List;Lnet/holdemresources/internal/lK;Lnet/holdemresources/internal/mi;)V",
                                  null,List.of(folded==1?foldAction:callAction),terminalState,terminalContext);
            // Explicit synthetic payoff table. The real mh/me/lv code selects
            // its entry. This does NOT claim that HRC settlement produced it.
            List<double[]> table=folded==1?List.of(new double[]{-1,1})
                :List.of(new double[]{10,-10},new double[]{20,-20},new double[]{30,-30});
            call("mh","a_","(Ljava/util/List;)V",leaf,table);
            leaves[folded==1?0:1]=leaf;
        }
        Object children=Array.newInstance(cls("mj"),2);
        Array.set(children,0,leaves[0]); Array.set(children,1,leaves[1]);
        Object root=construct("mf","(Lnet/holdemresources/internal/mf;Ljava/util/List;[Lnet/holdemresources/internal/mj;[IIII)V",
                              null,List.of(),children,new int[]{0,1},0,0,169);
        for(Object leaf:leaves) call("mh","a","(Lnet/holdemresources/internal/mf;)V",leaf,root);
        return new Fixture(root,leaves[0],leaves[1],field("mf","a",cls("mx"),root));
    }

    private static Object context(Deal deal,Script script,boolean v4) throws Throwable {
        Object rng=script.proxy();
        Object scratch=construct("ma","(Lorg/apache/commons/rng/UniformRandomProvider;)V",rng);
        String factoryName=v4?"lY":"lX";
        Object factory=staticField("lV","a",cls(factoryName));
        return call(factoryName,"a","(Lnet/holdemresources/internal/oj;[J[ILnet/holdemresources/internal/ma;)Lnet/holdemresources/internal/lV;",
                    factory,null,deal.boards.clone(),deal.holes.clone(),scratch);
    }

    private static double[] selectedStorage(Fixture fixture,int bucket) throws Throwable {
        double[] raw=(double[])field("mt","a",double[].class,fixture.store);
        int base=1+5*bucket;
        double[] selected={raw[0],raw[base],raw[base+1],raw[base+2],raw[base+3],raw[base+4]};
        boolean otherZero=true;
        for(int i=1;i<raw.length;i++) if((i<base||i>=base+5)&&raw[i]!=0) otherZero=false;
        check("other_buckets_untouched",otherZero,row("bucket",bucket,"array_length",raw.length));
        return selected;
    }
    private static void traversal(Deal deal,boolean v4) throws Throwable {
        Fixture fixture=fixture();
        Script script=new Script(0,1);
        Object context=context(deal,script,v4);
        double[] expected={10.0*(deal.outcome+1),-10.0*(deal.outcome+1)};
        double[] actual=(double[])call("mf","a","(Lnet/holdemresources/internal/lV;I)[D",fixture.root,context,0);
        compare("vector."+(v4?"v4":"v3")+".terminal_return",actual,expected,
                row("input_holes",deal.holes,"input_boards",deal.boards,"synthetic_payoff_table",true));
        int[] cached=(int[])call("lV","a","()[I",context);
        check("vector.original_eval_cache",Arrays.equals(cached,deal.ranks),row("expected",deal.ranks,"actual",cached));
        double advantage=(expected[0]+1)/2;
        compare("vector."+(v4?"v4":"v3")+".store",selectedStorage(fixture,deal.buckets[0]),
                new double[]{1,-advantage,advantage,1,.5,.5},
                row("bucket",deal.buckets[0],"Q",new double[]{-1,expected[0]},"p",new double[]{.5,.5}));
    }
    private static void scalarGate(Deal deal,boolean v4,int gate) throws Throwable {
        Fixture fixture=fixture(); Script script=new Script(0,gate);
        Object context=context(deal,script,v4);
        double expected=10.0*(deal.outcome+1);
        double actual=(Double)call("mf","a","(Lnet/holdemresources/internal/lV;IIDI)D",fixture.root,context,0,0,1.0,0);
        compare("scalar."+(v4?"v4":"v3")+".gate"+gate+".return",new double[]{actual},new double[]{expected},
                row("predicate_nextInt_result",gate,"depth",0,"bounded_calls",script.boundedCalls));
        boolean skip=v4&&gate==0;
        double advantage=(expected+1)/2;
        compare("scalar."+(v4?"v4":"v3")+".gate"+gate+".store",selectedStorage(fixture,deal.buckets[0]),
                skip?new double[6]:new double[]{1,-advantage,advantage,1,.5,.5},
                row("expected_skip",skip,"bounded_calls",script.boundedCalls,
                    "unbounded_rng_calls",script.unboundedCalls,"double_rng_calls",script.doubleCalls));
        check("scalar.predicate_called_only_v4",v4?script.boundedCalls.equals(List.of(2)):script.boundedCalls.isEmpty(),
                row("v4",v4,"bounded_calls",script.boundedCalls));
    }

    public static void main(String[] args) throws Throwable {
        if(args.length!=2) throw new IllegalArgumentException("Arguments: <original main.jar> <rng-client-api.jar>");
        Path main=Path.of(args[0]).toAbsolutePath(),rng=Path.of(args[1]).toAbsolutePath();
        String digest=hash(Files.readAllBytes(main));
        if(!digest.equals(JAR_HASH)) throw new IllegalArgumentException("Original JAR identity mismatch: "+digest);
        emit(row("kind","fixture_scope","jar_sha256",digest,"synthetic_leaf_payoffs",true,
                 "payoff_tables",List.of(List.of(-1,1),List.of(10,-10),List.of(20,-20),List.of(30,-30)),
                 "actual_original_components",List.of("lu deal","ls combo mapping","lV context","mf traversal","mh terminal","lv evaluator","me outcome index","mE storage","lX/lY factories"),
                 "not_tested",List.of("HRC full tree builder","real terminal settlement/ICM table generation","postflop continuation","GUI/licensing/application startup")));
        try(Loader own=new Loader(main,rng)) {
            loader=own;
            Deal first=null;
            for(long seed:new long[]{42,719,20261104,88129}) {
                Deal deal=deal(seed); if(first==null) first=deal;
                traversal(deal,false); traversal(deal,true);
            }
            scalarGate(first,false,0); scalarGate(first,true,0); scalarGate(first,true,1);
            emit(row("kind","summary","checks",checks,"all_passed",true,"loaded_classes",loader.loaded,
                     "interpretation","Original bytecode passed this small synthetic-payoff fixture; not full HRC equivalence."));
        }
    }

    private static void check(String id,boolean pass,Map<String,Object> detail) {
        checks++; emit(row("kind","invariant_check","id",id,"pass",pass,"detail",detail));
        if(!pass) throw new AssertionError(id);
    }
    private static void compare(String id,double[] actual,double[] expected,Map<String,Object> detail) {
        boolean pass=actual.length==expected.length; double error=0;
        if(pass) for(int i=0;i<actual.length;i++) {
            error=Math.max(error,Math.abs(actual[i]-expected[i]));
            if(!Double.isFinite(actual[i])||Math.abs(actual[i]-expected[i])>1e-12) pass=false;
        }
        checks++; emit(row("kind","numeric_check","id",id,"expected",expected,"actual",actual,
                          "max_abs_error",error,"pass",pass,"detail",detail));
        if(!pass) throw new AssertionError(id);
    }
    private static String hash(byte[] bytes) {
        try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));}
        catch(Exception e){throw new IllegalStateException(e);}
    }
    private static Map<String,Object> row(Object... values) {
        Map<String,Object> row=new LinkedHashMap<>();
        for(int i=0;i<values.length;i+=2)row.put((String)values[i],values[i+1]); return row;
    }
    private static void emit(Object value){System.out.println(json(value));}
    private static String json(Object value) {
        if(value==null)return "null";
        if(value instanceof String s)return "\""+s.replace("\\","\\\\").replace("\"","\\\"").replace("\n","\\n").replace("\r","\\r")+"\"";
        if(value instanceof Number n)return Double.isFinite(n.doubleValue())?n.toString():json(n.toString());
        if(value instanceof Boolean b)return b.toString();
        if(value instanceof Map<?,?> map){List<String> p=new ArrayList<>();map.forEach((k,v)->p.add(json(k.toString())+":"+json(v)));return "{"+String.join(",",p)+"}";}
        if(value instanceof Iterable<?> list){List<String> p=new ArrayList<>();list.forEach(v->p.add(json(v)));return "["+String.join(",",p)+"]";}
        if(value.getClass().isArray()){List<String> p=new ArrayList<>();for(int i=0;i<Array.getLength(value);i++)p.add(json(Array.get(value,i)));return "["+String.join(",",p)+"]";}
        throw new IllegalArgumentException(value.getClass().toString());
    }
}
