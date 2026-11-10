import java.io.*;
import java.lang.invoke.*;
import java.lang.reflect.*;
import java.nio.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import java.util.function.BiFunction;
import java.util.jar.*;
import org.objectweb.asm.*;

/** Original lq recursion and lR/lU default ancestry over synthetic policy nodes.
 * ASM implements obfuscated return-type overloads; no app/GUI/solver is loaded. */
public final class OriginalReachProbe {
 static final String P="net.holdemresources.internal.";
 static final int[] BUCKETS={169,7,11,13};static Loader loader;
 static String hash(byte[] b)throws Exception{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(b));}
 static class Loader extends ClassLoader {
  final Map<String,byte[]> code=new HashMap<>();
  Loader(Path path)throws Exception{super(ClassLoader.getPlatformClassLoader());if(!hash(Files.readAllBytes(path)).equals("25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43"))throw new SecurityException("Unreviewed main jar");
   try(JarFile jar=new JarFile(path.toFile())){for(String stem:"lq lR lU lA ly lz lr oj oi ls lt lO lQ".split(" ")){String name=P+stem;code.put(name,jar.getInputStream(jar.getJarEntry(name.replace('.','/')+".class")).readAllBytes());}}
  }
  protected Class<?> findClass(String name)throws ClassNotFoundException{byte[] bytes=code.get(name);if(bytes==null)throw new ClassNotFoundException("Outside pure reach allowlist: "+name);try{System.out.println("{\"kind\":\"class\",\"name\":\""+name+"\",\"sha256\":\""+hash(bytes)+"\"}");}catch(Exception e){throw new AssertionError(e);}return defineClass(name,bytes,0,bytes.length);}
  public InputStream getResourceAsStream(String name){throw new SecurityException("No resource access");}
 }
 static Class<?> cls(String name)throws Exception{return loader.loadClass(P+name);}
 static Object call(String owner,String name,String descriptor,Object receiver,Object...args)throws Throwable{
  var method=MethodHandles.publicLookup().findVirtual(cls(owner),name,MethodType.fromMethodDescriptorString(descriptor,loader));List<Object> input=new ArrayList<>();input.add(receiver);input.addAll(Arrays.asList(args));return method.invokeWithArguments(input);
 }
 static Object stat(String owner,String name,String descriptor,Object...args)throws Throwable{return MethodHandles.privateLookupIn(cls(owner),MethodHandles.lookup()).findStatic(cls(owner),name,MethodType.fromMethodDescriptorString(descriptor,loader)).invokeWithArguments(args);}
 static void box(MethodVisitor v,org.objectweb.asm.Type type){if(type.getSort()==org.objectweb.asm.Type.INT||type.getSort()==org.objectweb.asm.Type.BOOLEAN){String c=type.getSort()==org.objectweb.asm.Type.BOOLEAN?"java/lang/Boolean":"java/lang/Integer";v.visitMethodInsn(Opcodes.INVOKESTATIC,c,"valueOf","("+type.getDescriptor()+")L"+c+";",false);}else if(type.getSort()!=org.objectweb.asm.Type.OBJECT&&type.getSort()!=org.objectweb.asm.Type.ARRAY)throw new AssertionError(type);}
 static Class<?> adapter(String stem,String iface,boolean rootRange)throws Exception{
  String internal="probe/"+stem;ClassWriter writer=new ClassWriter(ClassWriter.COMPUTE_MAXS);writer.visit(Opcodes.V17,Opcodes.ACC_PUBLIC,internal,null,"java/lang/Object",new String[]{P.replace('.','/')+iface});
  writer.visitField(Opcodes.ACC_PUBLIC,"dispatch","Ljava/util/function/BiFunction;",null,null).visitEnd();
  MethodVisitor ctor=writer.visitMethod(Opcodes.ACC_PUBLIC,"<init>","()V",null,null);ctor.visitCode();ctor.visitVarInsn(Opcodes.ALOAD,0);ctor.visitMethodInsn(Opcodes.INVOKESPECIAL,"java/lang/Object","<init>","()V",false);ctor.visitInsn(Opcodes.RETURN);ctor.visitMaxs(0,0);ctor.visitEnd();
  List<String[]> methods=new ArrayList<>();
  for(String source:iface.equals("lR")?new String[]{"lR","lU"}:new String[]{iface})new ClassReader(loader.code.get(P+source)).accept(new ClassVisitor(Opcodes.ASM9){
   public MethodVisitor visitMethod(int access,String name,String descriptor,String signature,String[] exceptions){if((access&Opcodes.ACC_STATIC)==0&&((access&Opcodes.ACC_ABSTRACT)!=0||rootRange&&name.equals("f")))methods.add(new String[]{name,descriptor});return null;}
  },ClassReader.SKIP_CODE|ClassReader.SKIP_DEBUG|ClassReader.SKIP_FRAMES);
  for(String[] method:methods){
   String descriptor=method[1];MethodVisitor v=writer.visitMethod(Opcodes.ACC_PUBLIC,method[0],descriptor,null,null);v.visitCode();v.visitVarInsn(Opcodes.ALOAD,0);v.visitFieldInsn(Opcodes.GETFIELD,internal,"dispatch","Ljava/util/function/BiFunction;");v.visitLdcInsn(method[0]+descriptor);
   var args=org.objectweb.asm.Type.getArgumentTypes(descriptor);v.visitLdcInsn(args.length);v.visitTypeInsn(Opcodes.ANEWARRAY,"java/lang/Object");int local=1;
   for(int i=0;i<args.length;i++){v.visitInsn(Opcodes.DUP);v.visitLdcInsn(i);v.visitVarInsn(args[i].getOpcode(Opcodes.ILOAD),local);box(v,args[i]);v.visitInsn(Opcodes.AASTORE);local+=args[i].getSize();}
   v.visitMethodInsn(Opcodes.INVOKEINTERFACE,"java/util/function/BiFunction","apply","(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;",true);var type=org.objectweb.asm.Type.getReturnType(descriptor);
   if(type.getSort()==org.objectweb.asm.Type.VOID){v.visitInsn(Opcodes.POP);v.visitInsn(Opcodes.RETURN);}
   else if(type.getSort()==org.objectweb.asm.Type.INT||type.getSort()==org.objectweb.asm.Type.BOOLEAN){boolean bool=type.getSort()==org.objectweb.asm.Type.BOOLEAN;String c=bool?"java/lang/Boolean":"java/lang/Integer";v.visitTypeInsn(Opcodes.CHECKCAST,c);v.visitMethodInsn(Opcodes.INVOKEVIRTUAL,c,bool?"booleanValue":"intValue","()"+type.getDescriptor(),false);v.visitInsn(Opcodes.IRETURN);}
   else{v.visitTypeInsn(Opcodes.CHECKCAST,type.getInternalName());v.visitInsn(Opcodes.ARETURN);}
   v.visitMaxs(0,0);v.visitEnd();
  }
  writer.visitEnd();loader.code.put(internal.replace('/','.'),writer.toByteArray());return loader.loadClass(internal.replace('/','.'));
 }
 static double probability(int node,int bucket,int edge){int sum=0;for(int a=0;a<3;a++)sum+=((node+1)*7+(bucket+3)*(a+1))%11;return sum==0?1./3:(((node+1)*7+(bucket+3)*(edge+1))%11)/(double)sum;}
 static double[] initial(int player,int street){double[] row=new double[street==0?169:1326];for(int c=0;c<row.length;c++)row[c]=street==0?1.:((c+3*player)%17)/16.;return row;}
 static class Node {
  int id,actor,street,edge=-1;Node parent;Object self;Object[] children=new Object[3];int rootStreet;
  Object dispatch(String key,Object[] args)throws Throwable{
   return switch(key){
    case "a()Lnet/holdemresources/internal/lR;" -> parent==null?null:parent.self;
    case "a()Ljava/util/List;" -> List.of();case "a()[I" -> new int[]{0,1,2};
    case "a(I)Lnet/holdemresources/internal/lU;" -> children[(int)args[0]];
    case "a()I" -> 3;case "b()I" -> actor;case "c()I" -> street;
    case "a(I)Z" -> false;case "a(IZ)V" -> null;
    case "f(I)[D" -> parent==null?initial((int)args[0],rootStreet):(double[])call("lR","a","(Lnet/holdemresources/internal/lU;I)[D",parent.self,self,args[0]);
    case "b(I)[D" -> {double[] row=new double[BUCKETS[street]];for(int h=0;h<row.length;h++)row[h]=probability(id,h,(int)args[0]);yield row;}
    case "a(I)[D" -> {double[] row=(double[])dispatch("f(I)[D",new Object[]{actor});for(int h=0;h<row.length;h++)row[h]*=probability(id,h,(int)args[0]);yield row;}
    case "c(I)[D" -> new double[]{probability(id,(int)args[0],0),probability(id,(int)args[0],1),probability(id,(int)args[0],2)};
    case "d(I)[D","e(I)[D" -> new double[3];
    default -> throw new AssertionError("Unexpected node method "+key);
   };
  }
 }
 static long[] masks=new long[1326];
 static int[] map(int street,long[] boards,int player){int[] out=new int[1326];for(int c=0;c<1326;c++)out[c]=(masks[c]&boards[street])!=0?-1:(c+player*3+street*5)%BUCKETS[street];return out;}
 static void bind(Object object,BiFunction<String,Object[],Object> callback)throws Exception{object.getClass().getField("dispatch").set(object,callback);}
 public static void main(String[]args)throws Throwable{
  loader=new Loader(Path.of(args[0]));Path out=Path.of(args[2]);Files.createDirectories(out);for(int hi=1;hi<52;hi++)for(int lo=0;lo<hi;lo++)masks[hi*(hi-1)/2+lo]=(1L<<hi)|(1L<<lo);
  Class<?> nodeType=adapter("ReachNode","lR",true),mapperType=adapter("ReachMapper","oj",false);Object mapper=mapperType.getConstructor().newInstance();
  bind(mapper,(key,values)->{if(key.equals("a(I[JI)[I"))return map((int)values[0],(long[])values[1],(int)values[2]);if(key.equals("a(I)I")||key.equals("a(II)I"))return BUCKETS[(int)values[0]];throw new AssertionError(key);});
  for(String line:Files.readAllLines(Path.of(args[1]))){if(line.isBlank())continue;String[] fields=line.split("\t");String id=fields[0];int[] streets=Arrays.stream(fields[1].split(",")).mapToInt(Integer::parseInt).toArray();long[] board=Arrays.stream(fields[2].split(",")).mapToLong(Long::parseLong).toArray();
   Node[] nodes=new Node[streets.length];for(int i=0;i<nodes.length;i++){Node n=nodes[i]=new Node();n.id=i;n.street=streets[i];n.rootStreet=streets[0];n.actor=(i/2+i)%3;n.self=nodeType.getConstructor().newInstance();bind(n.self,(key,values)->{try{return n.dispatch(key,values);}catch(Throwable e){throw new RuntimeException(e);}});if(i>0){n.parent=nodes[i-1];n.edge=(i-1)%3;n.parent.children[n.edge]=n.self;}}
   for(int i=0;i<nodes.length;i++)if(streets[i]>0){ByteArrayOutputStream bytes=new ByteArrayOutputStream();for(int p=0;p<3;p++){
     double[] range=(double[])stat("lq","a","(Lnet/holdemresources/internal/lR;Lnet/holdemresources/internal/oj;[JI)[D",nodes[i].self,mapper,board,p);
     range=(double[])stat("lq","b","([DJ)[D",range,board[board.length-1]);for(double value:range)bytes.write(ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN).putDouble(value).array());
    }
    byte[] data=bytes.toByteArray();String key=id+"_"+i;Files.write(out.resolve(key+".bin"),data);System.out.println("{\"kind\":\"result\",\"id\":\""+key+"\",\"doubles\":3978,\"sha256\":\""+hash(data)+"\"}");
   }
  }
  // Canonical board and explicit range text/parse probes; no UI formatter init.
  for(int precision:new int[]{0,1,2,3,4,5,6,12}){double[] values=new double[1326];double threshold=.5*Math.pow(10,-precision);double[] samples={0,Math.nextDown(threshold),threshold,Math.nextUp(threshold),.125,.375,.9999999,1,1.25,1e-20,.2675};System.arraycopy(samples,0,values,0,samples.length);
   String text=(String)stat("lO","a","([DI)Ljava/lang/String;",values,precision);double[] parsed=(double[])stat("lQ","a","(Ljava/lang/String;)[D",text);ByteBuffer bytes=ByteBuffer.allocate(1326*8).order(ByteOrder.LITTLE_ENDIAN);for(double value:parsed)bytes.putDouble(value);Files.write(out.resolve("format_"+precision+".txt"),text.getBytes(java.nio.charset.StandardCharsets.UTF_8));Files.write(out.resolve("format_"+precision+".bin"),bytes.array());System.out.println("{\"kind\":\"format\",\"precision\":"+precision+",\"sha256\":\""+hash(bytes.array())+"\"}");
  }
 }
}
