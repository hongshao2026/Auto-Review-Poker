import java.lang.reflect.*;
import java.lang.invoke.MethodHandles;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.atomic.LongAdder;
import java.util.function.IntBinaryOperator;

/**
 * Fixed synthetic nested-tree audit. Reuses the already reviewed strict loader
 * in OriginalTraversalProbe. All utility tables and cached abstraction buckets
 * are explicitly synthetic inputs; no application/GUI/solver job is started.
 * This fixture never reads saved strategies, resource profiles or license state.
 */
public final class OriginalNestedTraversalProbe {
    static ClassLoader loader;
    static final String P="net.holdemresources.internal.";
    static final String RNG="org.apache.commons.rng.UniformRandomProvider";
    static Object helper(String name,Class<?>[] types,Object... args) throws Throwable {
        Method m=OriginalTraversalProbe.class.getDeclaredMethod(name,types); m.setAccessible(true);
        try {return m.invoke(null,args);} catch(InvocationTargetException e){throw e.getCause();}
    }
    static Object make(String owner,String desc,Object... args) throws Throwable {
        return helper("construct",new Class<?>[]{String.class,String.class,Object[].class},owner,desc,args);
    }
    static Object call(String owner,String name,String desc,Object self,Object... args) throws Throwable {
        return helper("call",new Class<?>[]{String.class,String.class,String.class,Object.class,Object[].class},owner,name,desc,self,args);
    }
    static Object stat(String owner,String name,String desc,Object... args) throws Throwable {
        return helper("stat",new Class<?>[]{String.class,String.class,String.class,Object[].class},owner,name,desc,args);
    }
    static Object field(String owner,String name,Class<?> type,Object self) throws Throwable {
        return helper("field",new Class<?>[]{String.class,String.class,Class.class,Object.class},owner,name,type,self);
    }
    static Object staticField(String owner,String name,Class<?> type) throws Throwable {
        return helper("staticField",new Class<?>[]{String.class,String.class,Class.class},owner,name,type);
    }
    static void emit(Object value) throws Throwable {helper("emit",new Class<?>[]{Object.class},value);}
    static Map<String,Object> row(Object... values) {
        Map<String,Object> result=new LinkedHashMap<>();
        for(int i=0;i<values.length;i+=2)result.put((String)values[i],values[i+1]); return result;
    }
    static Class<?> cls(String name) throws Exception{return loader.loadClass(P+name);}
    static final class Stream {
        final long[] s=new long[4];
        long bounded,doubles,ints; final List<Integer> bounds=new ArrayList<>();
        Stream(long seed){for(int i=0;i<4;i++){long z=(seed+=0x9e3779b97f4a7c15L);z=(z^(z>>>30))*0xbf58476d1ce4e5b9L;z=(z^(z>>>27))*0x94d049bb133111ebL;s[i]=z^(z>>>31);}}
        long next(){long r=Long.rotateLeft(s[1]*5,7)*9,t=s[1]<<17;s[2]^=s[0];s[3]^=s[1];s[1]^=s[2];s[0]^=s[3];s[2]^=t;s[3]=Long.rotateLeft(s[3],45);return r;}
        int bound(int n){bounded++;bounds.add(n);long v,threshold=Long.remainderUnsigned(-((long)n),n);do{v=next();}while(Long.compareUnsigned(v,threshold)<0);return (int)Long.remainderUnsigned(v,n);}
        Object proxy() throws Exception {
            return Proxy.newProxyInstance(loader,new Class<?>[]{loader.loadClass(RNG)},(self,m,a)->{
                if(m.getDeclaringClass()==Object.class)return switch(m.getName()) {
                    case "toString"->"FixedXoshiroFixture";case "hashCode"->System.identityHashCode(self);case "equals"->self==a[0];default->throw new UnsupportedOperationException();};
                if(m.getName().equals("nextInt")&&m.getParameterCount()==0){ints++;return (int)(next()>>>32);}
                if(m.getName().equals("nextInt")&&m.getParameterCount()==1)return bound((Integer)a[0]);
                if(m.getName().equals("nextDouble")&&m.getParameterCount()==0){doubles++;return (next()>>>11)*0x1.0p-53;}
                throw new UnsupportedOperationException("Unexpected numeric RNG method: "+m);
            });
        }
    }
    static final class Spec {
        int id,actor=-1,street,special; int[] children=new int[0]; double[] payoff; Object original,store;
    }
    static final class Case {
        String name;long seed;boolean v4;int target,depth,steps;double marker;
        List<Spec> nodes=new ArrayList<>();
    }
    static List<Case> parse(Path input) throws Exception {
        List<Case> cases=new ArrayList<>();Case c=null;
        for(String line:Files.readAllLines(input)){
            if(line.isBlank()||line.startsWith("#"))continue;String[] t=line.split(" ");
            switch(t[0]){
                case "CASE"->{c=new Case();c.name=t[1];c.seed=Long.parseLong(t[2]);c.v4=t[3].equals("4");c.target=Integer.parseInt(t[4]);c.depth=Integer.parseInt(t[5]);c.marker=Double.parseDouble(t[6]);c.steps=Integer.parseInt(t[7]);cases.add(c);}
                case "NODE"->{Spec n=new Spec();n.id=Integer.parseInt(t[1]);n.actor=Integer.parseInt(t[2]);n.street=Integer.parseInt(t[3]);n.special=Integer.parseInt(t[4]);n.children=Arrays.stream(Arrays.copyOfRange(t,5,t.length)).mapToInt(Integer::parseInt).toArray();if(n.id!=c.nodes.size())throw new IllegalArgumentException("ID order");c.nodes.add(n);}
                case "LEAF"->{Spec n=new Spec();n.id=Integer.parseInt(t[1]);n.payoff=new double[]{Double.parseDouble(t[2]),Double.parseDouble(t[3])};if(n.id!=c.nodes.size())throw new IllegalArgumentException("ID order");c.nodes.add(n);}
                case "END"->{} default->throw new IllegalArgumentException(line);
            }
        }return cases;
    }
    static Object action(boolean check,int actor,int street) throws Throwable {
        return check?stat("ly","b","(II)Lnet/holdemresources/internal/ly;",actor,street)
            :stat("ly","a","(IIJZ)Lnet/holdemresources/internal/ly;",actor,street,1L,false);
    }
    static Object build(Case c,int id,List<?> incoming,Object terminalContext) throws Throwable {
        Spec n=c.nodes.get(id);
        if(n.payoff!=null){
            // One live player forces the original terminal to use our single
            // constant synthetic payoff row; no card evaluator is invoked.
            Object state=make("lC","(J[J[J[JIIIIIII)V",0L,new long[]{19,19},new long[]{1,1},new long[]{0,0},1,0,3,-1,1,0,3);
            Object terminal=stat("lK","a","(Lnet/holdemresources/internal/lC;)Lnet/holdemresources/internal/lK;",state);
            n.original=make("mh","(Lnet/holdemresources/internal/mf;Ljava/util/List;Lnet/holdemresources/internal/lK;Lnet/holdemresources/internal/mi;)V",null,incoming,terminal,terminalContext);
            call("mh","a_","(Ljava/util/List;)V",n.original,List.of(n.payoff));return n.original;
        }
        Object children=Array.newInstance(cls("mj"),n.children.length);
        for(int a=0;a<n.children.length;a++)Array.set(children,a,build(c,n.children[a],List.of(action(n.special>0&&a==1,n.actor,n.street)),terminalContext));
        n.original=make("mf","(Lnet/holdemresources/internal/mf;Ljava/util/List;[Lnet/holdemresources/internal/mj;[IIII)V",null,incoming,children,new int[]{0,1},n.actor,n.street,2);
        for(int child:n.children){Spec ch=c.nodes.get(child);call(ch.payoff!=null?"mh":"mf","a","(Lnet/holdemresources/internal/mf;)V",ch.original,n.original);}
        n.store=field("mf","a",cls("mx"),n.original);return n.original;
    }
    static void run(Case c) throws Throwable {
        Object game=make("kM","([JLnet/holdemresources/internal/ky;ZLnet/holdemresources/internal/lH;)V",new long[]{20,20},null,false,null);
        Object terminalContext=make("mi","(Lnet/holdemresources/internal/kG;Ljava/util/function/IntBinaryOperator;)V",game,(IntBinaryOperator)(a,b)->0);
        Object root=build(c,0,List.of(),terminalContext);Stream stream=new Stream(c.seed);
        Object scratch=make("ma","(Lorg/apache/commons/rng/UniformRandomProvider;)V",stream.proxy());
        String factoryName=c.v4?"lY":"lX";
        Object factory=staticField("lV","a",cls(factoryName));
        Object context=call(factoryName,"a","(Lnet/holdemresources/internal/oj;[J[ILnet/holdemresources/internal/ma;)Lnet/holdemresources/internal/lV;",factory,null,new long[4],new int[]{0,1},scratch);
        int[][] cache=(int[][])field("lV","a",int[][].class,context);
        for(int st=0;st<4;st++)cache[st]=new int[]{0,1}; // Explicit synthetic abstraction input.
        // mh asks for the cached rank vector even for the fixed one-row leaf.
        // Supply it as an explicit fixture input, avoiding real rank evaluation
        // of the deliberately synthetic holes/board used above.
        MethodHandles.Lookup contextLookup=(MethodHandles.Lookup)helper("lookup",new Class<?>[]{String.class},"lV");
        contextLookup.findSetter(cls("lV"),"b",int[].class).invokeWithArguments(context,new int[]{1,2});
        for(int step=1;step<=c.steps;step++){
            double[] value=c.target<0?(double[])call("mf","a","(Lnet/holdemresources/internal/lV;I)[D",root,context,0)
                :new double[]{(Double)call("mf","a","(Lnet/holdemresources/internal/lV;IIDI)D",root,context,c.target,c.depth,c.marker,0)};
            List<Object> nodes=new ArrayList<>();
            for(Spec n:c.nodes)if(n.payoff==null){double[] raw=(double[])field("mt","a",double[].class,n.store);
                long updates=n.street==0?((LongAdder)field("mE","a",LongAdder.class,n.store)).sum():Math.round(raw[0]);
                nodes.add(row("id",n.id,"updates",updates,"raw",raw.clone()));}
            emit(row("kind","nested_result","case",c.name,"step",step,"value",value,"nodes",nodes,"rng_calls",new long[]{stream.bounded,stream.doubles,stream.ints},"bounded_arguments",stream.bounds));
        }
    }
    public static void main(String[] args) throws Throwable {
        if(args.length!=3)throw new IllegalArgumentException("<original.jar> <rng-api.jar> <synthetic-cases.txt>");
        String hash=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(Path.of(args[0]))));
        if(!hash.equals("25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43"))throw new IllegalArgumentException("Original identity mismatch");
        Class<?> loaderClass=Class.forName("OriginalTraversalProbe$Loader");Constructor<?> ctor=loaderClass.getDeclaredConstructor(Path.class,Path.class);ctor.setAccessible(true);
        try(AutoCloseable own=(AutoCloseable)ctor.newInstance(Path.of(args[0]),Path.of(args[1]))){
            loader=(ClassLoader)own;Field f=OriginalTraversalProbe.class.getDeclaredField("loader");f.setAccessible(true);f.set(null,loader);
            emit(row("kind","scope","original_jar_sha256",hash,"synthetic_payoffs",true,"synthetic_cached_buckets",true,"synthetic_cached_ranks",true,"context_weight",1,"full_application_started",false));
            for(Case c:parse(Path.of(args[2])))run(c);
        }
    }
}
