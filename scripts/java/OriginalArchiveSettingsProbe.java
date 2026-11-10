import java.io.*;
import java.lang.invoke.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import java.util.jar.*;

/** Isolated numeric oL prize-step expansion and kF chip-unit conversion only. */
public final class OriginalArchiveSettingsProbe {
 static String hash(byte[] b)throws Exception{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(b));}
 static final String PREFIX="net.holdemresources.internal.";
 static class Loader extends ClassLoader {
  final Map<String,byte[]> classes=new HashMap<>();
  Loader(Path path)throws Exception {
   super(ClassLoader.getPlatformClassLoader());
   if(!hash(Files.readAllBytes(path)).equals("25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43"))throw new SecurityException("Unreviewed original jar");
   try(JarFile jar=new JarFile(path.toFile())){
    for(String stem:List.of("oL","oM","kF")){
     String name=PREFIX+stem;classes.put(name,jar.getInputStream(jar.getJarEntry(name.replace('.','/')+".class")).readAllBytes());
    }
   }
   Path gson=path.getParent().resolve("com.google.gson_2.12.1.jar");
   if(!hash(Files.readAllBytes(gson)).equals("ea2495f032b239dcf63c642f33cc9fae8f83db7551ad7de20ba5f8b99dbd3da7"))throw new SecurityException("Unreviewed Gson jar");
   try(JarFile jar=new JarFile(gson.toFile())){
    for(JarEntry entry:Collections.list(jar.entries()))if(entry.getName().startsWith("com/google/gson/")&&entry.getName().endsWith(".class")){
     String name=entry.getName().substring(0,entry.getName().length()-6).replace('/','.');classes.put(name,jar.getInputStream(entry).readAllBytes());
    }
   }
  }
  protected Class<?> findClass(String name)throws ClassNotFoundException {
   byte[] bytes=classes.get(name);if(bytes==null)throw new ClassNotFoundException("Outside pure settings allowlist: "+name);
   try{System.out.println("{\"kind\":\"class\",\"name\":\""+name+"\",\"sha256\":\""+hash(bytes)+"\"}");}catch(Exception e){throw new AssertionError(e);}
   return defineClass(name,bytes,0,bytes.length);
  }
  public InputStream getResourceAsStream(String name){throw new SecurityException("No resource access");}
 }
 public static void main(String[] args)throws Throwable {
  var loader=new Loader(Path.of(args[0]));var lookup=MethodHandles.publicLookup();
  Class<?> klass=loader.loadClass(PREFIX+"oL");
  var ctor=lookup.findConstructor(klass,MethodType.methodType(void.class));
  var setter=lookup.findVirtual(klass,"setPrizes",MethodType.methodType(void.class,TreeMap.class));
  var expand=lookup.findVirtual(klass,"createStructure",MethodType.methodType(double[].class));
  for(String line:Files.readAllLines(Path.of(args[1]))){
   var parts=line.split("\t",-1);var map=new TreeMap<Integer,Double>();
   if(!parts[1].isEmpty())for(String term:parts[1].split(",")){var pair=term.split(":");map.put(Integer.valueOf(pair[0]),Double.valueOf(pair[1]));}
   Object object=ctor.invoke();setter.invoke(object,map);double[] result=(double[])expand.invoke(object);
   System.out.println("{\"kind\":\"prizes\",\"id\":\""+parts[0]+"\",\"values\":"+Arrays.toString(result)+"}");
  }
  Class<?> units=loader.loadClass(PREFIX+"kF");
  var convert=lookup.findStatic(units,"a",MethodType.methodType(double[].class,long[].class));
  long[] chips={0,1,50,99,100,101,10000,150000,123456789,140737488355328L};
  System.out.println("{\"kind\":\"units\",\"internal\":"+Arrays.toString(chips)+",\"values\":"+Arrays.toString((double[])convert.invoke(chips))+"}");
 }
}
