import java.lang.invoke.*;
import java.nio.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.*;

/** Isolated mx load/save and exact pY lock-setter sequence; no app or GUI. */
public final class OriginalStorageCodecProbe {
 static Object call(String n,String d,Object s,Object...a)throws Throwable{return OriginalExtendedStoreProbe.call(n,d,s,a);}
 static Class<?> cls(String n)throws Exception{return OriginalExtendedStoreProbe.cls(n);}
 static String values(double[] a){return OriginalExtendedStoreProbe.finite(a);}
 public static void main(String[]args)throws Throwable{
  OriginalExtendedStoreProbe.loader=new OriginalExtendedStoreProbe.Loader(Path.of(args[0]));
  for(String line:Files.readAllLines(Path.of(args[1]))){if(line.isBlank())continue;String[] p=line.split("\t");int fmt=Integer.parseInt(p[1]),h=Integer.parseInt(p[2]),k=Integer.parseInt(p[3]),locks=Integer.parseInt(p[4]);byte[] payload=Base64.getDecoder().decode(p[5]);ByteBuffer in=ByteBuffer.wrap(payload).order(ByteOrder.LITTLE_ENDIAN);double[][] locked=new double[k][];
   for(int l=0;l<locks;l++){int a=in.getInt();locked[a]=new double[h];for(int b=0;b<h;b++)locked[a][b]=in.getFloat();}
   byte[] bytes=Arrays.copyOfRange(payload,in.position(),payload.length);
   var factory=MethodHandles.publicLookup().findStatic(cls("mx"),"a",MethodType.methodType(cls("mx"),int.class,int.class,int.class,byte[].class));
   Object base=factory.invoke(fmt,k,h,bytes),store=base;
   double[] before=OriginalExtendedStoreProbe.flatten(base,fmt);long updates=fmt==25?Math.round(before[0]):((LongAdder)OriginalExtendedStoreProbe.field(fmt==23?"mE":fmt==27?"mB":fmt==31?"mD":"mz","a",LongAdder.class).get(base)).sum();
   // Same ascending action replay as pY.a(mf,byte[]); invokes original setters.
   for(int a=0;a<k;a++)if(locked[a]!=null){store=call("a","(I[D)Lnet/holdemresources/internal/my;",store,a,locked[a]);store=call("a","(IZ)Lnet/holdemresources/internal/mx;",store,a,true);}
   StringJoiner rows=new StringJoiner(",","[","]"),display=new StringJoiner(",","[","]"),ev=new StringJoiner(",","[","]");
   for(int a=0;a<k;a++){if(locked[a]==null){rows.add("null");continue;}double[] row=new double[h];for(int b=0;b<h;b++)row[b]=(double)call("a","(II)D",store,b,a);rows.add(values(row));}
   for(int b:new int[]{0,h-1}){display.add(values((double[])call("a","(I)[D",store,b)));ev.add(values((double[])call("b","(I)[D",store,b)));}
   byte[] serialized=(byte[])call("a","()[B",store);
   System.out.println("{\"kind\":\"case\",\"id\":\""+p[0]+"\",\"loaded_raw\":"+values(before)+",\"updates\":"+updates+",\"runtime_locks\":"+rows+",\"display\":"+display+",\"ev\":"+ev+",\"serialized_base64\":\""+Base64.getEncoder().encodeToString(serialized)+"\"}");
  }
 }
}
