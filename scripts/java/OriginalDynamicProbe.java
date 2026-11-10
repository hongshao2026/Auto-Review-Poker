import java.io.*;
import java.lang.invoke.*;
import java.lang.reflect.*;
import java.nio.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import java.util.jar.*;

/** Fixed-board pure key/mapping oracle. No pg registry, data resource or application. */
public final class OriginalDynamicProbe {
 static final String P="net.holdemresources.internal.";
 static Loader loader;
 static String hash(byte[] data)throws Exception{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(data));}
 static class Loader extends ClassLoader {
  final Map<String,byte[]> classes=new HashMap<>();
  Loader(Path path)throws Exception{super(ClassLoader.getPlatformClassLoader());
   if(!hash(Files.readAllBytes(path)).equals("25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43"))throw new SecurityException("Unreviewed artifact");
   try(JarFile jar=new JarFile(path.toFile())){for(String name:"oi ou ot os ow ox oz oy oA oC oB ov or oq oo on op og lt ls".split(" ")){name=P+name;classes.put(name,jar.getInputStream(jar.getJarEntry(name.replace('.','/')+".class")).readAllBytes());}}
  }
  protected Class<?> findClass(String name)throws ClassNotFoundException{byte[] data=classes.get(name);if(data==null)throw new ClassNotFoundException("Outside numerical allowlist "+name);try{System.out.println("{\"kind\":\"class\",\"name\":\""+name+"\",\"sha256\":\""+hash(data)+"\"}");}catch(Exception e){throw new AssertionError(e);}return defineClass(name,data,0,data.length);}
  public InputStream getResourceAsStream(String name){throw new SecurityException("No resource access");}
 }
 static Class<?> cls(String name)throws Exception{return loader.loadClass(P+name);}
 static Object invoke(String owner,String name,String desc,Object self,Object...args)throws Throwable{var method=MethodHandles.publicLookup().findVirtual(cls(owner),name,MethodType.fromMethodDescriptorString(desc,loader));List<Object> input=new ArrayList<>();input.add(self);input.addAll(Arrays.asList(args));return method.invokeWithArguments(input);}
 static long[] longs(String text){return Arrays.stream(text.split(",")).mapToLong(Long::parseLong).toArray();}
 static Object keyer(String mode,long[] prefix,int street)throws Exception{String type=mode.equals("strict")?"ow":mode.equals("balanced")?new String[]{"","ox","oz","oy"}[street]:new String[]{"","oA","oC","oB"}[street];return cls(type).getConstructor(long[].class).newInstance((Object)prefix);}
 static List<long[]> runouts(long[] prefix,int street){List<long[]> out=new ArrayList<>();expand(prefix,street+1-prefix.length,out);return out;}
 static void expand(long[] board,int count,List<long[]> result){if(count==0){result.add(board);return;}long used=board[board.length-1];for(int c=0;c<52;c++)if((used&(1L<<c))==0){long[] next=Arrays.copyOf(board,board.length+1);next[board.length]=used|(1L<<c);expand(next,count-1,result);}}
 static double[][] ranges(){double[][] out=new double[5][];for(int p:new int[]{0,1,3,4})out[p]=new double[1326];Arrays.fill(out[0],1);for(int i=0;i<1326;i++)if(i%11==1||i%11==3)out[1][i]=.25;for(int i:new int[]{0,1,42,100,777,1325})out[3][i]=1;return out;}
 static Object mapper(String mode,long[] prefix,int street,double[][] ranges)throws Throwable{
  if(mode.equals("none"))return cls("op").getConstructor(int.class).newInstance(street);
  if(!mode.equals("perfect"))return cls("ov").getConstructor(long[].class,int.class,cls("ou"),double[][].class).newInstance(prefix,street+1,keyer(mode,prefix,street),ranges);
  if(street==prefix.length-1)return cls("or").getConstructor(long[].class,double[][].class).newInstance(prefix,ranges);
  Object base=cls("oq").getConstructor(long[].class).newInstance((Object)prefix);
  int buckets=(int)invoke("oi","b","()I",base);int[][] mapping=new int[ranges.length][];
  for(int player=0;player<ranges.length;player++)if(ranges[player]!=null){TreeSet<Integer> used=new TreeSet<>();for(long[] board:runouts(prefix,street)){int[] row=(int[])invoke("oi","a","([JI)[I",base,board,player);for(int c=0;c<1326;c++)if(ranges[player][c]>0&&row[c]>=0)used.add(row[c]);}mapping[player]=new int[buckets];Arrays.fill(mapping[player],-1);int index=0;for(int bucket:used)mapping[player][bucket]=index++;}
  Object compressed=cls("oo").getConstructor(cls("oi"),int.class,int[][].class).newInstance(base,street,mapping);
  return cls("on").getConstructor(long[].class,cls("oo"),int.class).newInstance(prefix,compressed,ranges.length);
 }
 static void integer(ByteArrayOutputStream out,int value)throws Exception{out.write(ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putInt(value).array());}
 static void number(ByteArrayOutputStream out,long value)throws Exception{out.write(ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN).putLong(value).array());}
 public static void main(String[]args)throws Throwable{
  loader=new Loader(Path.of(args[0]));Path directory=Path.of(args[2]);Files.createDirectories(directory);
  long[] combos=new long[1326];for(int hi=1;hi<52;hi++)for(int lo=0;lo<hi;lo++)combos[hi*(hi-1)/2+lo]=(1L<<hi)|(1L<<lo);
  Field data=cls("ot").getDeclaredField("a");data.setAccessible(true);
  for(String line:Files.readAllLines(Path.of(args[1]))){if(line.isBlank())continue;String[] fields=line.split("\t");String kind=fields[0],id=fields[1],mode=fields[2];long[] prefix=longs(fields[3]);ByteArrayOutputStream bytes=new ByteArrayOutputStream();int entries=0;int[] effective=new int[0];long start=System.nanoTime();
   if(kind.equals("K")){long[] board=longs(fields[4]);Object keyer=keyer(mode,prefix,board.length-1);for(int combo=0;combo<1326;combo++)if((combos[combo]&board[board.length-1])==0){Object key=invoke("ou","a","([JJ)Lnet/holdemresources/internal/ot;",keyer,board,combos[combo]);long[] values=(long[])data.get(key);integer(bytes,combo);integer(bytes,values.length);for(long value:values)number(bytes,value);entries++;}}
   else{int street=Integer.parseInt(fields[4]);double[][] ranges=ranges();Object map=mapper(mode,prefix,street,ranges);effective=new int[ranges.length];for(int p=0;p<ranges.length;p++)effective[p]=(int)invoke("oi","a","(I)I",map,p);
    for(long[] board:runouts(prefix,street)){int row=0;long previous=prefix[prefix.length-1];for(int i=prefix.length;i<board.length;i++){row=row*52+Long.numberOfTrailingZeros(board[i]^previous);previous=board[i];}integer(bytes,row);
     for(int p=0;p<ranges.length;p++){int[] values=ranges[p]==null?null:(int[])invoke("oi","a","([JI)[I",map,board,p);integer(bytes,values==null?-1:values.length);if(values!=null)for(int value:values)integer(bytes,value);entries+=values==null?0:values.length;}}
   }
   byte[] result=bytes.toByteArray();Files.write(directory.resolve(id+".bin"),result);
   System.out.println("{\"kind\":\"result\",\"id\":\""+id+"\",\"entries\":"+entries+",\"effective\":"+Arrays.toString(effective)+",\"sha256\":\""+hash(result)+"\",\"bytes\":"+result.length+",\"nanoseconds\":"+(System.nanoTime()-start)+"}");
  }
 }
}
