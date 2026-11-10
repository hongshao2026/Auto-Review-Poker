import java.io.*;
import java.lang.invoke.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.function.*;
import java.util.jar.*;
import java.util.concurrent.atomic.LongAdder;

/** Original reach extraction, lw/lu and mf scalar/vector bytes. This fixture
 * assembles the audited mn dispatch sequence without loading its application
 * job/controller dependencies. Payoffs are explicitly synthetic constants. */
public final class OriginalSamplingScopeProbe {
 static final String P="net.holdemresources.internal.";
 static OriginalChanceProbe.Loader loader;
 static Class<?> cls(String n)throws Exception{return loader.loadClass(P+n);}
 static MethodType type(String s){return MethodType.fromMethodDescriptorString(s,loader);}
 static MethodHandles.Lookup lookup(String c)throws Exception{return MethodHandles.privateLookupIn(cls(c),MethodHandles.lookup());}
 static Object make(String c,String d,Object...a)throws Throwable{return lookup(c).findConstructor(cls(c),type(d)).invokeWithArguments(a);}
 static Object call(String c,String n,String d,Object self,Object...a)throws Throwable{List<Object>x=new ArrayList<>();x.add(self);x.addAll(Arrays.asList(a));return lookup(c).findVirtual(cls(c),n,type(d)).invokeWithArguments(x);}
 static Object stat(String c,String n,String d,Object...a)throws Throwable{return lookup(c).findStatic(cls(c),n,type(d)).invokeWithArguments(a);}
 static Object get(String c,String n,Class<?> t,Object self)throws Throwable{return lookup(c).findGetter(cls(c),n,t).invoke(self);}
 static void emit(Object row)throws Throwable{Method m=OriginalTraversalProbe.class.getDeclaredMethod("emit",Object.class);m.setAccessible(true);m.invoke(null,row);}
 static Map<String,Object> row(Object...v){Map<String,Object>m=new LinkedHashMap<>();for(int i=0;i<v.length;i+=2)m.put((String)v[i],v[i+1]);return m;}
 static Object[] nodes,stores;
 static int variant;
 static Object build(int id,List<?> incoming,Object tc)throws Throwable{
  if(id%2==1||id==6){Object state=make("lC","(J[J[J[JIIIIIII)V",0L,new long[]{19,19},new long[]{1,1},new long[]{0,0},1,0,3,-1,1,0,3);
   Object term=stat("lK","a","(Lnet/holdemresources/internal/lC;)Lnet/holdemresources/internal/lK;",state);
   Object node=make("mh","(Lnet/holdemresources/internal/mf;Ljava/util/List;Lnet/holdemresources/internal/lK;Lnet/holdemresources/internal/mi;)V",null,incoming,term,tc);
   call("mh","a_","(Ljava/util/List;)V",node,List.of(new double[]{id*3-8,8-id*3}));nodes[id]=node;return node;}
  int actor=id==0?0:id==2?1:variant==1?1:0,first=id==0?1:id==2?3:5;
  Object children=Array.newInstance(cls("mj"),2);
  for(int a=0;a<2;a++){Object action=stat("ly","a","(IIJZ)Lnet/holdemresources/internal/ly;",actor,0,1L,false);Array.set(children,a,build(first+a,List.of(action),tc));}
  Object node=make("mf","(Lnet/holdemresources/internal/mf;Ljava/util/List;[Lnet/holdemresources/internal/mj;[IIII)V",null,incoming,children,new int[]{0,1},actor,0,169);nodes[id]=node;
  for(int child=first;child<=first+1;child++)call(child==2||child==4?"mf":"mh","a","(Lnet/holdemresources/internal/mf;)V",nodes[child],node);
  stores[id]=get("mf","a",cls("mx"),node);return node;
 }
 public static void main(String[] args)throws Throwable{
  Path jar=Path.of(args[0]);loader=new OriginalChanceProbe.Loader(jar,Path.of(args[1]));
  Set<String> extra=Set.of("mE","mA","mt","mx","my","ma","mu","mv","mf","mj","lU","lR","lT","lA","ly","lz","mh","lS","lK","lC","mi","kG","kM","ky","lH","mk","me","lV","lW","lX","lY","lZ","oj","lv","lE");
  try(JarFile file=new JarFile(jar.toFile())){for(String c:extra){String name=P+c;loader.code.put(name,file.getInputStream(file.getJarEntry(name.replace('.','/')+".class")).readAllBytes());}}
  OriginalNestedTraversalProbe.loader=loader;
  Class<?> rngType=loader.loadClass("org.apache.commons.rng.UniformRandomProvider"),samplerType=loader.loadClass("org.apache.commons.rng.sampling.distribution.SharedStateDiscreteSampler");
  Class<?> guide=loader.loadClass("org.apache.commons.rng.sampling.distribution.GuideTableDiscreteSampler");
  var of=MethodHandles.publicLookup().findStatic(guide,"of",MethodType.methodType(samplerType,rngType,double[].class,double.class));
  Class<?> samplerArray=Array.newInstance(samplerType,0).getClass();var ctor=cls("lw").getDeclaredConstructor(samplerArray,rngType);ctor.setAccessible(true);
  for(variant=0;variant<2;variant++)for(int version:new int[]{3,4})for(long seed:new long[]{42,43}){
   nodes=new Object[7];stores=new Object[7];Object game=make("kM","([JLnet/holdemresources/internal/ky;ZLnet/holdemresources/internal/lH;)V",new long[]{20,20},null,false,null);
   Object tc=make("mi","(Lnet/holdemresources/internal/kG;Ljava/util/function/IntBinaryOperator;)V",game,(IntBinaryOperator)(a,b)->0);build(0,List.of(),tc);
   double[] raw=(double[])get("mt","a",double[].class,stores[0]);for(int h=0;h<169;h++){double q=h==168?0:(1+h%3)/4.;raw[1+5*h+3]=1-q;raw[1+5*h+4]=q;}
   double[][] reach=new double[2][];for(int p=0;p<2;p++)reach[p]=(double[])call("lU","f","(I)[D",nodes[2],p);
   int[] targets=variant==0?new int[]{1,0}:new int[]{1};
   OriginalNestedTraversalProbe.Stream stream=new OriginalNestedTraversalProbe.Stream(seed);Object rng=stream.proxy();Object samplers=Array.newInstance(samplerType,2);
   int[] classes=(int[])lookup("ls").findStaticGetter(cls("ls"),"a",int[].class).invoke();
   for(int p=0;p<2;p++){double min=Arrays.stream(reach[p]).min().orElseThrow(),max=Arrays.stream(reach[p]).max().orElseThrow();if(min==max&&max>0)continue;double[] weights=new double[1326];for(int c=0;c<1326;c++)weights[c]=reach[p][classes[c]];Array.set(samplers,p,of.invokeWithArguments(rng,weights,10.));}
   Object dealer=ctor.newInstance(samplers,rng);int mode=(Boolean)call("lw","a","([I)Z",dealer,targets)?1:2;long deals=0;
   for(int step=1;step<=16;step++){int[] combos=new int[2];long[] board=new long[4];
    for(int target:mode==1?new int[]{-1}:targets){long used=(Long)call("lw","a","([IJILjava/util/function/BooleanSupplier;)J",dealer,combos,0L,target,(BooleanSupplier)()->false);stat("lu","a","(Lorg/apache/commons/rng/UniformRandomProvider;[JJ)J",rng,board,used);deals++;
     Object scratch=make("ma","(Lorg/apache/commons/rng/UniformRandomProvider;)V",rng);String fac=version==4?"lY":"lX";Object factory=lookup("lV").findStaticGetter(cls("lV"),"a",cls(fac)).invoke();
     Object context=call(fac,"a","(Lnet/holdemresources/internal/oj;[J[ILnet/holdemresources/internal/ma;)Lnet/holdemresources/internal/lV;",factory,null,board,combos,scratch);
     lookup("lV").findSetter(cls("lV"),"b",int[].class).invoke(context,new int[]{1,2});
     if(mode==1)call("mf","a","(Lnet/holdemresources/internal/lV;I)[D",nodes[2],context,0);
     else call("mf","a","(Lnet/holdemresources/internal/lV;IIDI)D",nodes[2],context,target,0,reach[target][classes[combos[target]]],0);
    }
    List<Object> state=new ArrayList<>();for(int id:new int[]{0,2,4})state.add(row("id",id,"updates",((LongAdder)get("mE","a",LongAdder.class,stores[id])).sum(),"raw",((double[])get("mt","a",double[].class,stores[id])).clone()));
    emit(row("kind","result","variant",variant,"version",version,"seed",seed,"step",step,"mode",mode,"samples",step,"deals",deals,"combos",combos,"board",board,"rng_calls",new long[]{stream.bounded,stream.doubles,stream.ints},"nodes",state));
   }
  }
 }
}
