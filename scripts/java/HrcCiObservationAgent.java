import java.lang.instrument.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.util.*;
import java.util.jar.JarFile;
import org.objectweb.asm.*;

/** Exact single-constructor observation hook; no field/return/control changes. */
public final class HrcCiObservationAgent {
  private static final String TARGET="net/holdemresources/internal/mr";
  private static ClassFileTransformer transformer;
  private static Instrumentation owner;
  private static Path log;
  private static String originalHash;
  private static int transforms;
  private static String sha(byte[] data) throws Exception {
    return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(data));
  }
  private static void event(String body) throws Exception {
    Files.writeString(log,"{\"epoch_millis\":"+System.currentTimeMillis()+","+body+"}\n",
      StandardCharsets.UTF_8,StandardOpenOption.CREATE,StandardOpenOption.APPEND);
  }
  public static void premain(String options,Instrumentation inst) throws Exception { agentmain(options,inst); }
  public static synchronized void agentmain(String options,Instrumentation inst) throws Exception {
    String[] args=options.split("\\|",-1);
    if(args[0].equals("stop")) {
      if(transformer==null)throw new IllegalStateException("No installed transformer");
      if(owner==null||!owner.removeTransformer(transformer))throw new IllegalStateException("Registered transformer was not removed");
      transformer=null;
      for(Class<?> cls:owner.getAllLoadedClasses())if(cls.getName().equals(TARGET.replace('/','.')))owner.retransformClasses(cls);
      event("\"event\":\"removed_and_original_class_restored\",\"remove_returned_true\":true");owner=null;return;
    }
    if(!args[0].equals("start")||args.length!=4||transformer!=null)throw new IllegalArgumentException("start|outputDirectory|sinkJar|originalMrSha256");
    Path out=Path.of(args[1]);Files.createDirectories(out);log=out.resolve("agent-events.jsonl");originalHash=args[3];
    inst.appendToBootstrapClassLoaderSearch(new JarFile(args[2]));
    Class<?> sink=Class.forName("rea.hrcbench.HrcCiSink",true,null);
    sink.getMethod("configure",String.class).invoke(null,out.resolve("original-ci.jsonl").toString());
    transformer=new ClassFileTransformer() {
      @Override public byte[] transform(Module module,ClassLoader loader,String name,Class<?> cls,ProtectionDomain domain,byte[] bytes) throws IllegalClassFormatException {
        if(!TARGET.equals(name))return null;
        try {
          if(!sha(bytes).equals(originalHash))throw new IllegalStateException("Unexpected mr bytecode hash");
          ClassReader reader=new ClassReader(bytes);ClassWriter writer=new ClassWriter(reader,ClassWriter.COMPUTE_MAXS);
          int[] constructors={0},returns={0};
          reader.accept(new ClassVisitor(Opcodes.ASM9,writer) {
            @Override public MethodVisitor visitMethod(int access,String name,String descriptor,String signature,String[] exceptions) {
              MethodVisitor delegate=super.visitMethod(access,name,descriptor,signature,exceptions);
              if(!name.equals("<init>")||!descriptor.equals("(IJJD)V"))return delegate;
              constructors[0]++;
              return new MethodVisitor(Opcodes.ASM9,delegate) {
                @Override public void visitInsn(int opcode) {
                  if(opcode==Opcodes.RETURN) {
                    returns[0]++;
                    super.visitVarInsn(Opcodes.ILOAD,1);super.visitVarInsn(Opcodes.LLOAD,2);
                    super.visitVarInsn(Opcodes.LLOAD,4);super.visitVarInsn(Opcodes.DLOAD,6);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC,"rea/hrcbench/HrcCiSink","record","(IJJD)V",false);
                  }
                  super.visitInsn(opcode);
                }
              };
            }
          },0);
          if(constructors[0]!=1||returns[0]!=1)throw new IllegalStateException("Unexpected mr constructor shape");
          byte[] result=writer.toByteArray();transforms++;
          event("\"event\":\"single_constructor_transformed\",\"original_sha256\":\""+sha(bytes)+"\",\"transformed_sha256\":\""+sha(result)+"\",\"constructors\":1,\"return_hooks\":1");
          return result;
        } catch(Exception failure) { try {event("\"event\":\"transform_failed\",\"type\":\""+failure.getClass().getName()+"\"");}catch(Exception ignored){}throw new IllegalClassFormatException(failure.toString()); }
      }
    };
    owner=inst;inst.addTransformer(transformer,true);
    Integer workers=null;
    for(Class<?> cls:inst.getAllLoadedClasses()) {
      if(cls.getName().equals(TARGET.replace('/','.')))inst.retransformClasses(cls);
      if(cls.getName().equals("net.holdemresources.internal.oc")) {
        for(Field field:cls.getDeclaredFields())if(Modifier.isStatic(field.getModifiers())&&field.getType()==int.class) {
          field.setAccessible(true);workers=field.getInt(null);
        }
      }
    }
    event("\"event\":\"installed\",\"original_worker_count\":"+workers+",\"transforms_so_far\":"+transforms);
  }
}
