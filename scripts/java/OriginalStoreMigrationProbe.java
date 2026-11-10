import java.lang.invoke.*;
import java.nio.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.*;

/** Original pure mz enable/unwrap; fi field edits are reproduced explicitly, no UI executes. */
public final class OriginalStoreMigrationProbe {
 static Object call(String name,String desc,Object self,Object...args)throws Throwable{return OriginalExtendedStoreProbe.call(name,desc,self,args);}
 static Class<?> cls(String name)throws Exception{return OriginalExtendedStoreProbe.cls(name);}
 static String vector(double[] values){return OriginalExtendedStoreProbe.finite(values);}
 static double[] adders(Object store,String name)throws Exception{return Arrays.stream((DoubleAdder[])OriginalExtendedStoreProbe.field("mz",name,DoubleAdder[].class).get(store)).mapToDouble(DoubleAdder::sum).toArray();}
 static String snapshot(Object store)throws Exception{
  return "{\"raw\":"+vector(OriginalExtendedStoreProbe.flatten(store,63))
   +",\"targets\":"+vector((double[])OriginalExtendedStoreProbe.field("mz","b",double[].class).get(store))
   +",\"edges\":"+vector((double[])OriginalExtendedStoreProbe.field("mz","c",double[].class).get(store))
   +",\"edge_sums\":"+vector(adders(store,"a"))+",\"shared_sums\":"+vector(adders(store,"b"))
   +",\"updates\":"+((LongAdder)OriginalExtendedStoreProbe.field("mz","a",LongAdder.class).get(store)).sum()
   +",\"minimum\":"+OriginalExtendedStoreProbe.field("mz","b",double.class).getDouble(store)
   +",\"maximum\":"+OriginalExtendedStoreProbe.field("mz","c",double.class).getDouble(store)+"}";
 }
 public static void main(String[]args)throws Throwable{
  OriginalExtendedStoreProbe.loader=new OriginalExtendedStoreProbe.Loader(Path.of(args[0]));
  for(int format:new int[]{23,25,27,31})for(int k:new int[]{2,3,4}){
   int h=2,width=format==25?k:2*k+(format==27?0:1),header=format==23?1:k+1;
   String type=format==23?"mE":format==25?"mA":format==27?"mB":"mD";
   Object store=OriginalExtendedStoreProbe.make(type,h,k);float[] data=new float[header+h*width];
   for(int i=0;i<data.length;i++)data[i]=(i%7-2)/3.0f;data[0]=16.5f;
   if(format==23||format==31)for(int b=0;b<h;b++)data[header+b*width+k]=b+2;
   ByteBuffer bytes=ByteBuffer.allocate(data.length*4).order(ByteOrder.LITTLE_ENDIAN);for(float value:data)bytes.putFloat(value);call("a","([B)V",store,bytes.array());
   double[] initial=OriginalExtendedStoreProbe.flatten(store,format),targets=new double[k],edges=new double[k];Arrays.fill(targets,Double.NaN);targets[0]=.4;edges[k-1]=.75;
   Object wrapped=MethodHandles.publicLookup().findStatic(cls("mz"),"a",MethodType.methodType(cls("mz"),cls("mx"),double[].class,double[].class)).invoke(store,targets,edges);
   String enabled=snapshot(wrapped);double[] update=new double[2*k];for(int a=0;a<k;a++){update[a]=1.0/k;update[k+a]=a*2.0-1;}
   call("a","(Lnet/holdemresources/internal/ma;[DIIDD)V",wrapped,OriginalExtendedStoreProbe.rng(1),update,0,0,.7,.4);
   String updated=snapshot(wrapped);
   // fi.execute first flushes when collecting the current edge values, then
   // applies these field assignments only after the dialog is accepted.
   call("c","()V",wrapped);
   double[] t=(double[])OriginalExtendedStoreProbe.field("mz","b",double[].class).get(wrapped);
   double[] e=(double[])OriginalExtendedStoreProbe.field("mz","c",double[].class).get(wrapped);
   DoubleAdder[] sums=(DoubleAdder[])OriginalExtendedStoreProbe.field("mz","a",DoubleAdder[].class).get(wrapped);
   for(int a=0;a<k;a++){t[a]=a==0?.65:Double.NaN;e[a]=a==0?0:-.25*a;sums[a].reset();if(a!=0)sums[a].add(e[a]);}
   String edited=snapshot(wrapped);
   Object restored=MethodHandles.publicLookup().findVirtual(cls("mz"),"a",MethodType.methodType(cls("mx"))).invoke(wrapped);
   System.out.println("{\"kind\":\"case\",\"id\":\"migration_"+format+"_"+k+"\",\"format\":"+format+",\"actions\":"+k+",\"initial\":"+vector(initial)+",\"enabled\":"+enabled+",\"updated\":"+updated+",\"edited\":"+edited+",\"restored_format\":"+call("c","()I",restored)+",\"restored_raw\":"+vector(OriginalExtendedStoreProbe.flatten(restored,format))+"}");
  }
 }
}
