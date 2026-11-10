import java.lang.invoke.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import java.util.concurrent.atomic.*;
import java.util.jar.*;

/** Original my/mx/mz and numeric storage only. Platform-parent allowlist loader.
 * No application entry point, worker, licensing, UI or OSGi initializer executes. */
public final class OriginalPolicyProbe {
 static final String P="net.holdemresources.internal.", RNG="org.apache.commons.rng.UniformRandomProvider";
 static final String HASH="25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43";
 static Loader loader;
 static class Loader extends ClassLoader {
  final Map<String,byte[]> bytes=new HashMap<>();
  Loader(Path main,Path rng) throws Exception {super(ClassLoader.getPlatformClassLoader());
   String hash=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(main)));if(!hash.equals(HASH))throw new IllegalArgumentException("Unreviewed artifact");
   try(JarFile jar=new JarFile(main.toFile())){for(String s:List.of("mx","my","mz","mt","mE","mA","ma","mu","mv","mq","mr","ms","mf","mj","lR","lU","lS","lT","lA","ly","lz")){String name=P+s;bytes.put(name,jar.getInputStream(jar.getJarEntry(name.replace('.','/')+".class")).readAllBytes());}}
   try(JarFile jar=new JarFile(rng.toFile())){bytes.put(RNG,jar.getInputStream(jar.getJarEntry(RNG.replace('.','/')+".class")).readAllBytes());}
  }
  protected Class<?> findClass(String name)throws ClassNotFoundException {byte[] b=bytes.get(name);if(b==null)throw new ClassNotFoundException("Outside audited allowlist: "+name);try{System.out.println("{\"kind\":\"class\",\"name\":\""+name+"\",\"sha256\":\""+HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(b))+"\"}");}catch(Exception e){throw new AssertionError(e);}return defineClass(name,b,0,b.length);}
 }
 static Class<?> cls(String name)throws Exception{return loader.loadClass(P+name);}
 static Object make(String name,String desc,Object...args)throws Throwable{return MethodHandles.publicLookup().findConstructor(cls(name),MethodType.fromMethodDescriptorString(desc,loader)).invokeWithArguments(args);}
 static Object call(String owner,String name,String desc,Object self,Object...args)throws Throwable {MethodHandle h=MethodHandles.publicLookup().findVirtual(cls(owner),name,MethodType.fromMethodDescriptorString(desc,loader));List<Object>a=new ArrayList<>();a.add(self);a.addAll(Arrays.asList(args));return h.invokeWithArguments(a);}
 static Field field(Class<?>owner,String name,Class<?>type)throws Exception{for(Field f:owner.getDeclaredFields())if(f.getName().equals(name)&&f.getType()==type){f.setAccessible(true);return f;}throw new NoSuchFieldException(owner+"."+name+":"+type);}
 static double[] nums(String s){return s.equals("-")?new double[0]:Arrays.stream(s.split(",")).mapToDouble(Double::parseDouble).toArray();}
 static Object rng(int value)throws Exception {Class<?> type=loader.loadClass(RNG);Object r=Proxy.newProxyInstance(loader,new Class<?>[]{type},(p,m,a)->{if(m.getName().equals("nextInt")&&m.getParameterCount()==0)return value;throw new AssertionError("Unexpected RNG: "+m);});Constructor<?>c=cls("ma").getDeclaredConstructor(type);c.setAccessible(true);return c.newInstance(r);}
 static double[] raw(Object s)throws Exception{return ((double[])field(cls("mt"),"a",double[].class).get(s)).clone();}
 static double[] adders(Object s,String name)throws Exception {DoubleAdder[] a=(DoubleAdder[])field(cls("mz"),name,DoubleAdder[].class).get(s);return Arrays.stream(a).mapToDouble(DoubleAdder::doubleValue).toArray();}
 static String matrix(Object s,String name,String desc,int h,boolean special)throws Throwable {StringJoiner j=new StringJoiner(",","[","]");for(int b=0;b<h;b++){double[] v;if(desc.equals("(IZ[DI)V")){int k=(int)call("mx","a","()I",s);v=new double[k];call("mx",name,desc,s,b,special,v,0);}else v=(double[])call("mx",name,desc,s,b);j.add(Arrays.toString(v));}return j.toString();}
 static String freq(Object s,int h)throws Throwable {return "{\"raw\":"+Arrays.toString(raw(s))+",\"edges\":"+Arrays.toString((double[])field(cls("mz"),"c",double[].class).get(s))+",\"edge_sums\":"+Arrays.toString(adders(s,"a"))+",\"shared_sums\":"+Arrays.toString(adders(s,"b"))+",\"updates\":"+((LongAdder)field(cls("mz"),"a",LongAdder.class).get(s)).longValue()+",\"minimum\":"+field(cls("mz"),"b",double.class).get(s)+",\"maximum\":"+field(cls("mz"),"c",double.class).get(s)+",\"strategy\":"+matrix(s,"a","(IZ[DI)V",h,false)+",\"special\":"+matrix(s,"a","(IZ[DI)V",h,true)+",\"display\":"+matrix(s,"a","(I)[D",h,false)+",\"ev\":"+matrix(s,"b","(I)[D",h,false)+"}";}
 static Object shiftedRecord(Object record,long shift)throws Exception {if(record==null)return null;Constructor<?> c=cls("mr").getDeclaredConstructor(int.class,long.class,long.class,double.class);c.setAccessible(true);return c.newInstance(field(cls("mr"),"a",int.class).get(record),field(cls("mr"),"a",long.class).getLong(record)+shift,field(cls("mr"),"b",long.class).get(record),field(cls("mr"),"a",double.class).get(record));}
 @SuppressWarnings("unchecked") static void shiftCI(Object tracker,long shift)throws Exception {
  Field last=field(cls("mq"),"b",long.class);last.setLong(tracker,last.getLong(tracker)+shift);
  Field first=field(cls("mq"),"a",cls("mr"));first.set(tracker,shiftedRecord(first.get(tracker),shift));
  LinkedList<Object> history=(LinkedList<Object>)field(cls("mq"),"a",LinkedList.class).get(tracker);
  for(int i=0;i<history.size();i++)history.set(i,shiftedRecord(history.get(i),shift));
 }
 static void setSnapshots(Object[] stores,double[] counts,String[] policies)throws Throwable {
  for(int i=0;i<stores.length;i++){double[] p=nums(policies[i]);for(int b=0;b<p.length/2;b++)call("mt","a","(I[D)V",stores[i],b,Arrays.copyOfRange(p,b*2,b*2+2));call("mE","c","(D)V",stores[i],counts[i]);}
 }
 @SuppressWarnings("unchecked") static String ci(Object tracker,boolean accepted,long shift)throws Throwable {
  LinkedList<Object> history=(LinkedList<Object>)field(cls("mq"),"a",LinkedList.class).get(tracker);StringJoiner rows=new StringJoiner(",","[","]");
  for(Object record:history)rows.add("["+field(cls("mr"),"a",int.class).get(record)+","+(field(cls("mr"),"a",long.class).getLong(record)-shift)+","+field(cls("mr"),"b",long.class).get(record)+","+field(cls("mr"),"a",double.class).get(record)+"]");
  StringJoiner progress=new StringJoiner(",","[","]");Object first=field(cls("mq"),"a",cls("mr")).get(tracker);
  for(double target:new double[]{1,5,50,500})progress.add(String.valueOf(call("mq","a","(DLnet/holdemresources/internal/mr;)D",tracker,target,first)));
  return "{\"accepted\":"+accepted+",\"ci\":"+field(cls("mq"),"a",double.class).get(tracker)+",\"speed\":"+call("mq","a","()D",tracker)+",\"interval\":"+field(cls("mq"),"c",long.class).get(tracker)+",\"last_time\":"+(field(cls("mq"),"b",long.class).getLong(tracker)-shift)+",\"history\":"+rows+",\"progress\":"+progress+"}";
 }
 public static void main(String[] args)throws Throwable{loader=new Loader(Path.of(args[0]),Path.of(args[1]));for(String line:Files.readAllLines(Path.of(args[2]))){if(line.isBlank())continue;String[] p=line.split("\t",-1);
  if(p[0].equals("L")){int k=Integer.parseInt(p[2]),h=Integer.parseInt(p[3]);double[] r=nums(p[4]),av=nums(p[5]);Object base=make("mE","(II)V",h,k);for(int b=0;b<h;b++){call("mt","b","(I[D)V",base,b,Arrays.copyOfRange(r,b*k,(b+1)*k));call("mt","a","(I[D)V",base,b,Arrays.copyOfRange(av,b*k,(b+1)*k));}String[] rs=p[6].split("/");double[][] rows=new double[k][];for(int a=0;a<k;a++)if(!rs[a].equals("-"))rows[a]=nums(rs[a]);Object s=make("my","(Lnet/holdemresources/internal/mx;[[D)V",base,rows);
   if(!p[7].equals("-"))for(String edit:p[7].split(";")){String[] e=edit.split(":");int a=Integer.parseInt(e[0]);s=e[1].equals("-")||e[1].equals("+")?call("mx","a","(IZ)Lnet/holdemresources/internal/mx;",s,a,e[1].equals("+")):call("mx","a","(I[D)Lnet/holdemresources/internal/my;",s,a,nums(e[1]));}
   StringJoiner actualrows=new StringJoiner(",","[","]");for(int a=0;a<k;a++){boolean locked=(boolean)call("mx","b","(I)Z",s,a);double[] row=new double[locked?h:0];if(locked)for(int b=0;b<h;b++)row[b]=(double)call("mx","a","(II)D",s,b,a);actualrows.add(Arrays.toString(row));}
   System.out.println("{\"id\":\""+p[1]+"\",\"display\":"+matrix(s,"a","(I)[D",h,false)+",\"training\":"+matrix(s,"a","(IZ[DI)V",h,Boolean.parseBoolean(p[8].equals("1")?"true":"false"))+",\"rows\":"+actualrows+"}");
  }else if(p[0].equals("F")){int h=Integer.parseInt(p[2]),k=Integer.parseInt(p[3]);Object s=make("mz","(II[D[DI)V",h,k,nums(p[4]),nums(p[5]),23);StringJoiner snaps=new StringJoiner(",","[","]");snaps.add(freq(s,h));
   for(String st:p[6].split("\\|")){String[]v=st.split(";");int b=Integer.parseInt(v[0]);double[] pr=nums(v[4]),q=nums(v[5]),buffer=new double[2*k];System.arraycopy(pr,0,buffer,0,k);System.arraycopy(q,0,buffer,k,k);call("mz","a","(Lnet/holdemresources/internal/ma;[DIIDD)V",s,rng(Integer.parseInt(v[3])),buffer,0,b,Double.parseDouble(v[1]),Double.parseDouble(v[2]));if(v[6].equals("1"))call("mt","c","()V",s);if(v[7].equals("1")||v[8].equals("1"))call("mz","a","(ZZ)V",s,v[7].equals("1"),v[8].equals("1"));snaps.add(freq(s,h));}
   System.out.println("{\"id\":\""+p[1]+"\",\"snapshots\":"+snaps+"}");
  }else if(p[0].equals("C")){double[] counts=nums(p[2]);String[]policies=p[3].split("/");Object[] nodes=new Object[counts.length],stores=new Object[counts.length];Object parent=null;
   for(int i=0;i<nodes.length;i++){Object children=Array.newInstance(cls("mj"),2);nodes[i]=make("mf","(Lnet/holdemresources/internal/mf;Ljava/util/List;[Lnet/holdemresources/internal/mj;[IIII)V",parent,List.of(),children,new int[]{0,1},0,0,nums(policies[i]).length/2);if(parent!=null)call("mf","a","(ILnet/holdemresources/internal/mj;)V",parent,0,nodes[i]);parent=nodes[i];stores[i]=field(cls("mf"),"a",cls("mx")).get(parent);}
   setSnapshots(stores,counts,policies);Object tracker=make("mq","(Lnet/holdemresources/internal/mf;)V",nodes[0]);long initial=field(cls("mq"),"b",long.class).getLong(tracker);shiftCI(tracker,-initial);StringJoiner snapshots=new StringJoiner(",","[","]");
   for(String st:p[4].split("\\|")){String[]v=st.split(";");long logical=Long.parseLong(v[0]),samples=Long.parseLong(v[1]);counts=nums(v[3]);policies=v[4].split("/");setSnapshots(stores,counts,policies);
    if(v[5].equals("1")){tracker=make("mq","(Lnet/holdemresources/internal/mf;)V",nodes[0]);shiftCI(tracker,logical-field(cls("mq"),"b",long.class).getLong(tracker));}
    long shift=System.currentTimeMillis()-logical;shiftCI(tracker,shift);boolean accepted=(boolean)call("mq","a","(J)Z",tracker,samples);snapshots.add(ci(tracker,accepted,shift));shiftCI(tracker,-shift);
   }
   System.out.println("{\"id\":\""+p[1]+"\",\"snapshots\":"+snapshots+"}");
  }else throw new IllegalArgumentException("Unknown opcode "+p[0]);
 }}
}
