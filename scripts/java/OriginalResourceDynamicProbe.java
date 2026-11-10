import java.io.*;
import java.lang.invoke.*;
import java.net.*;
import java.nio.*;
import java.nio.file.*;
import java.util.*;
import java.util.jar.*;

/** Pure original resource reader + oo/on wrappers. qa/pg/application excluded. */
public final class OriginalResourceDynamicProbe {
 static final String P="net.holdemresources.internal.";
 static OriginalFlopBucketProbe.OriginalOnly loader;
 static Class<?> cls(String stem)throws Exception{return loader.loadClass(P+stem);}
 static Object invoke(String owner,String name,String descriptor,Object self,Object...args)throws Throwable{
  var method=MethodHandles.publicLookup().findVirtual(cls(owner),name,MethodType.fromMethodDescriptorString(descriptor,loader));
  List<Object> all=new ArrayList<>();all.add(self);all.addAll(Arrays.asList(args));return method.invokeWithArguments(all);
 }
 static double[][] ranges(){double[][] out=new double[5][];for(int p:new int[]{0,1,3,4})out[p]=new double[1326];Arrays.fill(out[0],1);for(int i=0;i<1326;i++)if(i%11==1||i%11==3)out[1][i]=.25;for(int i:new int[]{0,1,42,100,777,1325})out[3][i]=1;return out;}
 static List<long[]> boards(long flop,int street){List<long[]> output=new ArrayList<>();for(int turn=0;turn<52;turn++)if((flop&(1L<<turn))==0){long t=flop|(1L<<turn);if(street==2)output.add(new long[]{0,flop,t});else for(int river=0;river<52;river++)if((t&(1L<<river))==0)output.add(new long[]{0,flop,t,t|(1L<<river)});}return output;}
 static void integer(OutputStream stream,int n)throws IOException{stream.write(ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putInt(n).array());}
 public static void main(String[] args)throws Throwable{
  Path main=Path.of(args[0]),ec=Path.of(args[1]),cache=Path.of(args[2]),out=Path.of(args[4]);Files.createDirectories(out);
  OriginalFlopBucketProbe.pin(main,"25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43");
  OriginalFlopBucketProbe.pin(ec,"66a68713b950183831f621278bb6da674f82ca8a2d5bbe312556e9c5ff19610c");
  try(URLClassLoader dependencies=new URLClassLoader(new URL[]{ec.toUri().toURL()},ClassLoader.getPlatformClassLoader())){
   loader=new OriginalFlopBucketProbe.OriginalOnly(main,dependencies);
   try(JarFile jar=new JarFile(main.toFile())){for(String stem:new String[]{"oo","on"}){String name=P+stem;loader.classes.put(name,jar.getInputStream(jar.getJarEntry(name.replace('.','/')+".class")).readAllBytes());}}
   for(var entry:loader.classes.entrySet())System.out.println("{\"kind\":\"allowlist\",\"name\":\""+entry.getKey()+"\",\"sha256\":\""+OriginalFlopBucketProbe.sha(entry.getValue())+"\"}");
   var parse=MethodHandles.publicLookup().findStatic(cls("oh"),"a",MethodType.methodType(cls("ol"),InputStream.class,int.class,String.class));
   for(int street:new int[]{2,3}){
    String digest=street==2?"741bd150aec01478de0204b90775758d730248df0458d8d4a3a534bc90deb8a7":"40624adecddaa224acf4cf2cf59e1e6f5e92d2080099d2465beac417cb6393a4";
    Path data=cache.resolve("street"+street+".buckets.u16");OriginalFlopBucketProbe.pin(data,digest);Object base;try(InputStream stream=Files.newInputStream(data)){base=parse.invokeWithArguments(stream,street,digest);}
    if(base==null||(int)invoke("oi","b","()I",base)!=16384)throw new AssertionError("Unexpected profile");
    for(String line:Files.readAllLines(Path.of(args[3]))){String[] fields=line.split("\t");if(Integer.parseInt(fields[1])!=street)continue;String id=fields[0];long flop=Long.parseLong(fields[2]);var runouts=boards(flop,street);double[][] ranges=ranges();Object mapping;
     if(street==2){var compress=MethodHandles.publicLookup().findStatic(cls("oo"),"a",MethodType.methodType(cls("on"),cls("oi"),long.class,double[][].class));mapping=compress.invokeWithArguments(base,flop,ranges);}
     else {
      // Replays qa.java's inline reachable-ID construction; qa itself is NOT
      // executed. Every base row and the final oo mapping execute original code.
      int[][] compression=new int[ranges.length][];
      for(int p=0;p<ranges.length;p++)if(ranges[p]!=null){TreeSet<Integer> used=new TreeSet<>();for(long[] board:runouts){int[] row=(int[])invoke("oi","a","([JI)[I",base,board,p);for(int c=0;c<1326;c++)if(ranges[p][c]>0&&row[c]>=0)used.add(row[c]);}compression[p]=new int[16384];Arrays.fill(compression[p],-1);int index=0;for(int bucket:used)compression[p][bucket]=index++;}
      mapping=cls("oo").getConstructor(cls("oi"),int.class,int[][].class).newInstance(base,3,compression);
     }
     int[] effective=new int[ranges.length];for(int p=0;p<ranges.length;p++)effective[p]=(int)invoke("oi","a","(I)I",mapping,p);
     Path file=out.resolve(id+".bin");long entries=0;try(OutputStream stream=new BufferedOutputStream(Files.newOutputStream(file))){for(long[] board:runouts){int row=Long.numberOfTrailingZeros(board[2]^flop);if(street==3)row=row*52+Long.numberOfTrailingZeros(board[3]^board[2]);integer(stream,row);for(int p=0;p<ranges.length;p++){int[] values=(int[])invoke("oi","a","([JI)[I",mapping,board,p);integer(stream,values==null?-1:values.length);if(values!=null)for(int value:values)integer(stream,value);entries+=values==null?0:values.length;}}}
     System.out.println("{\"kind\":\"result\",\"id\":\""+id+"\",\"entries\":"+entries+",\"effective\":"+Arrays.toString(effective)+",\"sha256\":\""+OriginalFlopBucketProbe.sha(Files.readAllBytes(file))+"\"}");
    }
    base=null;System.gc();
   }
  }
 }
}
