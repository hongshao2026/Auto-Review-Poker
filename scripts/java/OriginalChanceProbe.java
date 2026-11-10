import java.io.*;
import java.lang.invoke.*;
import java.lang.reflect.*;
import java.nio.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import java.util.function.BooleanSupplier;
import java.util.jar.*;

/** Only audited numeric lw/lu/ls and Commons RNG; no HRC app, license or resources. */
public final class OriginalChanceProbe {
 static final String P="net.holdemresources.internal.";
 static Loader loader;
 static String hash(byte[] bytes)throws Exception{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));}
 static class Loader extends ClassLoader {
  final Map<String,byte[]> code=new HashMap<>();
  Loader(Path jar,Path dependency)throws Exception{super(ClassLoader.getPlatformClassLoader());
   load(jar,"25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43",false);
   String[] names={"client-api","sampling","core","simple"};
   String[] hashes={"9b9cc84858789046b03636216aff2cf8062711a1d68478746e2a8cfc202be429","87c53aa15fd3a764a70d2253f417e0101af00679cb62c25d59a703a0f15675a8","52653f3032c49a2b2b77872a9e2ad1f570127933824b84d0bb8cd8c0e18a1520","3a96ef9bc03b79ec336c685b7f59177df5996f9350e4cf95a1ebc2d926fbf06b"};
   for(int i=0;i<names.length;i++)load(dependency.resolve("commons-rng-"+names[i]+"-1.6.jar"),hashes[i],true);
  }
  void load(Path path,String expected,boolean dependency)throws Exception{
   if(!hash(Files.readAllBytes(path)).equals(expected))throw new SecurityException("Unreviewed artifact "+path);
   try(JarFile jar=new JarFile(path.toFile())){var entries=jar.entries();while(entries.hasMoreElements()){var entry=entries.nextElement();String name=entry.getName();if(!name.endsWith(".class"))continue;String cls=name.substring(0,name.length()-6).replace('/','.');
    if(dependency?cls.startsWith("org.apache.commons.rng."):Set.of(P+"lw",P+"lu",P+"ls",P+"lt").contains(cls))code.put(cls,jar.getInputStream(entry).readAllBytes());}}
  }
  protected Class<?> findClass(String name)throws ClassNotFoundException{byte[] bytes=code.get(name);if(bytes==null)throw new ClassNotFoundException("Outside numeric allowlist: "+name);try{System.out.println("{\"kind\":\"class\",\"name\":\""+name+"\",\"sha256\":\""+hash(bytes)+"\"}");}catch(Exception e){throw new AssertionError(e);}return defineClass(name,bytes,0,bytes.length);}
  public InputStream getResourceAsStream(String name){throw new SecurityException("Resource access prohibited");}
 }
 static long[] longs(String value){return Arrays.stream(value.split(",")).mapToLong(Long::parseLong).toArray();}
 static double[] doubles(String value){return Arrays.stream(value.split(",")).mapToDouble(Double::parseDouble).toArray();}
 static class Script implements InvocationHandler {
  final double[] doubles;final long[] integers;int di=0,ii=0;final ByteArrayOutputStream calls=new ByteArrayOutputStream();
  Script(String ds,String is){doubles=doubles(ds);integers=longs(is);}
  void record(int tag,long data)throws Exception{calls.write(ByteBuffer.allocate(12).order(ByteOrder.LITTLE_ENDIAN).putInt(tag).putLong(data).array());}
  public Object invoke(Object proxy,Method method,Object[] args)throws Throwable{
   if(method.getName().equals("nextDouble")&&method.getParameterCount()==0){double x=doubles[di++%doubles.length];record(0,Double.doubleToRawLongBits(x));return x;}
   if(method.getName().equals("nextInt")&&method.getParameterCount()==1){int bound=(int)args[0],x=(int)(integers[ii++%integers.length]%bound);record(bound,x);return x;}
   if(method.getName().equals("toString"))return "fixed-input-rng";
   throw new AssertionError("Unexpected RNG call "+method);
  }
 }
 public static void main(String[] args)throws Throwable{
  loader=new Loader(Path.of(args[0]),Path.of(args[1]));
  Class<?> rngType=loader.loadClass("org.apache.commons.rng.UniformRandomProvider"),samplerType=loader.loadClass("org.apache.commons.rng.sampling.distribution.SharedStateDiscreteSampler");
  Class<?> guide=loader.loadClass("org.apache.commons.rng.sampling.distribution.GuideTableDiscreteSampler"),lw=loader.loadClass(P+"lw"),lu=loader.loadClass(P+"lu");
  Class<?> samplerArray=Array.newInstance(samplerType,0).getClass();var ctor=lw.getDeclaredConstructor(samplerArray,rngType);ctor.setAccessible(true);
  var of=MethodHandles.publicLookup().findStatic(guide,"of",MethodType.methodType(samplerType,rngType,double[].class,double.class));
  var sample=MethodHandles.publicLookup().findVirtual(samplerType,"sample",MethodType.methodType(int.class));
  var deal=MethodHandles.publicLookup().findVirtual(lw,"a",MethodType.methodType(long.class,int[].class,long.class,int.class,BooleanSupplier.class));
  var runout=MethodHandles.publicLookup().findStatic(lu,"a",MethodType.methodType(long.class,rngType,long[].class,long.class,long[].class));
  long[] masks=new long[1326];for(int hi=1;hi<52;hi++)for(int lo=0;lo<hi;lo++)masks[hi*(hi-1)/2+lo]=(1L<<hi)|(1L<<lo);
  for(String line:Files.readAllLines(Path.of(args[2]))){if(line.isBlank())continue;String[] v=line.split("\t");String id=v[0];long[] prefix=longs(v[1]);String[] rows=v[2].split(";");Script script=new Script(v[3],v[4]);int skip=Integer.parseInt(v[5]);
   Object rng=Proxy.newProxyInstance(loader,new Class<?>[]{rngType},script),samplers=Array.newInstance(samplerType,rows.length);int first=-1;for(int p=0;p<rows.length;p++)if(!rows[p].equals("-")&&p!=skip){first=p;break;}int leading=first;long[] attempts={first<0?1:0};
   for(int p=0;p<rows.length;p++)if(!rows[p].equals("-")){String[] specification=rows[p].split("\\|",-1);double[] weights=new double[1326];Arrays.fill(weights,Double.parseDouble(specification[0]));if(!specification[1].isBlank())for(String term:specification[1].split(",")){String[] pair=term.split(":");weights[Integer.parseInt(pair[0])]=Double.parseDouble(pair[1]);}
    for(int c=0;c<1326;c++)if((masks[c]&prefix[prefix.length-1])!=0)weights[c]=0;
    Object actual=of.invokeWithArguments(rng,weights,10.0);int seat=p;
    Object wrapper=Proxy.newProxyInstance(loader,new Class<?>[]{samplerType},(proxy,method,values)->{if(method.getName().equals("sample")){if(seat==leading)attempts[0]++;try{return (int)sample.invokeWithArguments(actual);}catch(Throwable e){throw new RuntimeException(e);}}throw new AssertionError("Unexpected sampler call "+method);});
    Array.set(samplers,p,wrapper);
   }
   Object instance=ctor.newInstance(samplers,rng);int[] combos=new int[rows.length];Arrays.fill(combos,-1);int[] cancellations={0};BooleanSupplier cancel=()->{cancellations[0]++;return true;};
   long used=(long)deal.invokeWithArguments(instance,combos,prefix[prefix.length-1],skip,cancel);long[] board=new long[4];if(used>=0)used=(long)runout.invokeWithArguments(rng,board,used,prefix);
   System.out.println("{\"kind\":\"result\",\"id\":\""+id+"\",\"combos\":"+Arrays.toString(combos)+",\"board\":"+Arrays.toString(board)+",\"used\":"+used+",\"attempts\":"+attempts[0]+",\"double_calls\":"+script.di+",\"integer_calls\":"+script.ii+",\"cancel_checks\":"+cancellations[0]+",\"calls_sha256\":\""+hash(script.calls.toByteArray())+"\"}");
  }
 }
}
