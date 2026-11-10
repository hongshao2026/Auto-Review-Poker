import java.io.*;
import java.lang.invoke.*;
import java.lang.reflect.*;
import java.nio.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import java.util.concurrent.atomic.*;
import java.util.jar.*;

/** Read-only, isolated original numerical stores 25/27/31; no application entry point. */
public final class OriginalExtendedStoreProbe {
 static final String P="net.holdemresources.internal.", RNG="org.apache.commons.rng.UniformRandomProvider";
 static Loader loader;
 static String hash(byte[] b)throws Exception{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(b));}
 static class Loader extends ClassLoader {
  final Map<String,byte[]> classes=new HashMap<>();
  Loader(Path plugins)throws Exception{super(ClassLoader.getPlatformClassLoader());
   add(plugins.resolve("net.holdemresources.calculator_4.1.0.202603231401.jar"),"25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43",
       Arrays.stream("mx mt mw mB mD mA mE mC mz mu mv ma my oE".split(" ")).map(s->P+s).toList());
   add(plugins.resolve("net.holdemresources.preflopdata.holdem_1.4.1.jar"),"721c77d43459c6573b0b4aeb50f259f03d964991a73b80ebeb7a68777111ffa2",List.of("net.holdemresources.handevaluation.preflop.hands.BitConverter"));
   Path rng=plugins.resolve("net.holdemresources.calculator.mavendependencies_0.2.0/org.apache.commons/commons-rng-client-api-1.6.jar");
   if(!hash(Files.readAllBytes(rng)).equals("9b9cc84858789046b03636216aff2cf8062711a1d68478746e2a8cfc202be429"))throw new SecurityException("Unreviewed RNG interface artifact");
   try(JarFile jar=new JarFile(rng.toFile())){classes.put(RNG,jar.getInputStream(jar.getJarEntry(RNG.replace('.','/')+".class")).readAllBytes());}
   System.out.println("{\"kind\":\"artifact\",\"name\":\"rng\",\"sha256\":\""+hash(Files.readAllBytes(rng))+"\"}");
  }
  void add(Path path,String expected,List<String> names)throws Exception{
   if(!hash(Files.readAllBytes(path)).equals(expected))throw new SecurityException("Unreviewed artifact "+path);
   try(JarFile jar=new JarFile(path.toFile())){for(String name:names)classes.put(name,jar.getInputStream(jar.getJarEntry(name.replace('.','/')+".class")).readAllBytes());}
  }
  protected Class<?> findClass(String name)throws ClassNotFoundException{byte[] bytes=classes.get(name);if(bytes==null)throw new ClassNotFoundException("Outside numerical allowlist: "+name);
   try{System.out.println("{\"kind\":\"class\",\"name\":\""+name+"\",\"sha256\":\""+hash(bytes)+"\"}");}catch(Exception e){throw new AssertionError(e);}return defineClass(name,bytes,0,bytes.length);}
  public InputStream getResourceAsStream(String name){throw new SecurityException("No resource access");}
 }
 static Class<?> cls(String name)throws Exception{return loader.loadClass(P+name);}
 static Object make(String name,int h,int k)throws Throwable{return cls(name).getConstructor(int.class,int.class).newInstance(h,k);}
 static Object call(String name,String desc,Object self,Object...args)throws Throwable{
  var handle=MethodHandles.publicLookup().findVirtual(cls("mx"),name,MethodType.fromMethodDescriptorString(desc,loader));
  List<Object> input=new ArrayList<>();input.add(self);input.addAll(Arrays.asList(args));return handle.invokeWithArguments(input);}
 static Field field(String owner,String name,Class<?> type)throws Exception{for(Field f:cls(owner).getDeclaredFields())if(f.getName().equals(name)&&f.getType()==type){f.setAccessible(true);return f;}throw new NoSuchFieldException(owner+name+type);}
 static double[] nums(String text){return text.equals("-")?new double[0]:Arrays.stream(text.split(",")).mapToDouble(Double::parseDouble).toArray();}
 static int[] ints(String text){return Arrays.stream(text.split(",")).mapToInt(Integer::parseInt).toArray();}
 static Object rng(int value)throws Exception{var type=loader.loadClass(RNG);var object=Proxy.newProxyInstance(loader,new Class<?>[]{type},(p,m,a)->{if(m.getName().equals("nextInt")&&m.getParameterCount()==0)return value;throw new AssertionError(m);});var constructor=cls("ma").getDeclaredConstructor(type);constructor.setAccessible(true);return constructor.newInstance(object);}
 static double[] flatten(Object store,int format)throws Exception{
  if(format!=31)return ((double[])field("mt","a",double[].class).get(store)).clone();
  double[][] chunks=(double[][])field("mw","a",double[][].class).get(store);return Arrays.stream(chunks).flatMapToDouble(Arrays::stream).toArray();}
 static String finite(double[] values){if(values==null)return "null";StringJoiner j=new StringJoiner(",","[","]");for(double x:values)j.add(Double.isFinite(x)?Double.toString(x):"\""+x+"\"");return j.toString();}
 static String snapshot(Object store,int format,int h,int k,int[] buckets)throws Throwable{
  double[] raw=flatten(store,format),header=Arrays.copyOf(raw,k+1);StringJoiner rows=new StringJoiner(",","[","]"),training=new StringJoiner(",","[","]"),special=new StringJoiner(",","[","]"),display=new StringJoiner(",","[","]"),ev=new StringJoiner(",","[","]");
  int width=format==25?k:format==27?2*k:2*k+1;
  for(int b:buckets){rows.add(finite(Arrays.copyOfRange(raw,k+1+b*width,k+1+(b+1)*width)));double[] p=new double[k];call("a","(IZ[DI)V",store,b,false,p,0);training.add(finite(p));call("a","(IZ[DI)V",store,b,true,p,0);special.add(finite(p));display.add(finite((double[])call("a","(I)[D",store,b)));ev.add(finite((double[])call("b","(I)[D",store,b)));}
  long counter=format==25?Math.round(raw[0]):((LongAdder)field(format==27?"mB":"mD","a",LongAdder.class).get(store)).sum();
  double[] sums=format==31?Arrays.stream((DoubleAdder[])field("mD","a",DoubleAdder[].class).get(store)).mapToDouble(DoubleAdder::sum).toArray():Arrays.copyOfRange(raw,1,k+1);
  ByteBuffer buffer=ByteBuffer.allocate(raw.length*8).order(ByteOrder.LITTLE_ENDIAN);for(double x:raw)buffer.putDouble(x);
  String chunks="[]";if(format==31)chunks=Arrays.toString(Arrays.stream((double[][])field("mw","a",double[][].class).get(store)).mapToInt(a->a.length).toArray());
  return "{\"format\":"+format+",\"header\":"+finite(header)+",\"counter\":"+counter+",\"shared_adders\":"+finite(sums)+",\"rows\":"+rows+",\"training\":"+training+",\"special\":"+special+",\"display\":"+display+",\"ev\":"+ev+",\"chunks\":"+chunks+",\"raw_sha256\":\""+hash(buffer.array())+"\"}";
 }
 public static void main(String[]args)throws Throwable{
  loader=new Loader(Path.of(args[0]));for(String line:Files.readAllLines(Path.of(args[1]))){if(line.isBlank())continue;String[] p=line.split("\t",-1);String id=p[0];int format=Integer.parseInt(p[1]),h=Integer.parseInt(p[2]),k=Integer.parseInt(p[3]);int[] selected=ints(p[6]);String type=format==25?"mA":format==27?"mB":"mD";Object store=make(type,h,k);int width=format==25?k:format==27?2*k:2*k+1;
   float[] initial=new float[k+1+h*width];double[] header=nums(p[4]);for(int i=0;i<header.length;i++)initial[i]=(float)header[i];if(!p[5].equals("-"))for(String row:p[5].split(";")){String[] r=row.split(":");int b=Integer.parseInt(r[0]);double[] values=nums(r[1]);for(int i=0;i<values.length;i++)initial[k+1+b*width+i]=(float)values[i];}
   ByteBuffer buffer=ByteBuffer.allocate(initial.length*4).order(ByteOrder.LITTLE_ENDIAN);for(float x:initial)buffer.putFloat(x);call("a","([B)V",store,buffer.array());
   StringJoiner snapshots=new StringJoiner(",","[","]");snapshots.add(snapshot(store,format,h,k,selected));StringJoiner serialized=new StringJoiner(",","[","]");
   for(String operation:p[7].split("\\|")){String[] op=operation.split(";");switch(op[0]){
    case "U":{double[] pr=nums(op[5]),q=nums(op[6]),data=new double[2*k];System.arraycopy(pr,0,data,0,k);System.arraycopy(q,0,data,k,k);call("a","(Lnet/holdemresources/internal/ma;[DIIDD)V",store,rng(Integer.parseInt(op[4])),data,0,Integer.parseInt(op[1]),Double.parseDouble(op[2]),Double.parseDouble(op[3]));break;}
    case "F":call("c","()V",store);break;
    case "G":call("b","()[D",store);break;
    case "C":call("c","(D)V",store,Double.parseDouble(op[1]));break;
    case "R":call("a","(ZZ)V",store,op[1].equals("1"),op[2].equals("1"));break;
    case "D":{var handle=MethodHandles.publicLookup().findVirtual(cls(format==31?"mD":"mB"),format==31?"a":"b",MethodType.methodType(void.class,double.class));handle.invoke(store,Double.parseDouble(op[1]));break;}
    case "V":{var handle=MethodHandles.publicLookup().findStatic(cls("mB"),"a",MethodType.methodType(cls("mB"),cls("mA")));store=handle.invoke(store);format=27;type="mB";break;}
    case "S":{byte[] bytes=(byte[])call("a","()[B",store);serialized.add("\""+hash(bytes)+"\"");Object next=make(type,h,k);call("a","([B)V",next,bytes);store=next;break;}
    default:throw new IllegalArgumentException(operation);
   }snapshots.add(snapshot(store,format,h,k,selected));}
   System.out.println("{\"kind\":\"case\",\"id\":\""+id+"\",\"snapshots\":"+snapshots+",\"serialized_sha256\":"+serialized+"}");
  }
 }
}
