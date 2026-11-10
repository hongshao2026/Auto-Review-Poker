import java.lang.instrument.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import java.util.jar.*;
import org.objectweb.asm.*;

/** Read-only identity audit of the original four-field immutable CI record. */
public final class HrcCiBytecodeAuditAgent {
  static byte[] canonical(byte[] b) {
    ClassWriter w=new ClassWriter(0);new ClassReader(b).accept(w,0);return w.toByteArray();
  }
  static String sha(byte[] b) throws Exception {return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(b));}
  public static void agentmain(String options,Instrumentation inst) throws Exception {
    String[] a=options.split("\\|",-1);Path out=Path.of(a[0]);Files.createDirectories(out);
    byte[] original;try(JarFile j=new JarFile(a[1])) {original=j.getInputStream(j.getJarEntry("net/holdemresources/internal/mr.class")).readAllBytes();}
    if(!sha(original).equals("b042666356d6c366321fe3ac6ca61acc57a3b6ad65743be1cc9ec40aa010dd87"))throw new IllegalStateException("Unexpected reference");
    byte[][] received={null};
    ClassFileTransformer t=new ClassFileTransformer(){
      @Override public byte[] transform(Module m,ClassLoader l,String n,Class<?> c,ProtectionDomain d,byte[] b){
        if(n.equals("net/holdemresources/internal/mr"))received[0]=b.clone();return null;
      }
    };
    inst.addTransformer(t,true);
    try {for(Class<?> c:inst.getAllLoadedClasses())if(c.getName().equals("net.holdemresources.internal.mr"))inst.retransformClasses(c);}
    finally {if(!inst.removeTransformer(t))throw new IllegalStateException("Audit transformer removal failed");}
    if(received[0]==null)throw new IllegalStateException("Original class not loaded");
    Files.write(out.resolve("original-mr.class"),original);Files.write(out.resolve("runtime-mr.class"),received[0]);
    Files.write(out.resolve("original-canonical.class"),canonical(original));Files.write(out.resolve("runtime-canonical.class"),canonical(received[0]));
    Files.writeString(out.resolve("audit.json"),"{\"original_sha256\":\""+sha(original)+"\",\"runtime_sha256\":\""+sha(received[0])+"\",\"original_canonical_sha256\":\""+sha(canonical(original))+"\",\"runtime_canonical_sha256\":\""+sha(canonical(received[0]))+"\",\"canonical_equal\":"+Arrays.equals(canonical(original),canonical(received[0]))+",\"audit_transformer_removed\":true}\n");
  }
}
