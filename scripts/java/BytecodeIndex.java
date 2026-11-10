import java.io.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import java.util.jar.*;
import jdk.internal.org.objectweb.asm.*;

/** Read-only classfile inventory: no target classes are loaded or initialized. */
public final class BytecodeIndex {
    static PrintWriter out;
    static String q(String s) {
        if (s == null) return "null";
        StringBuilder b = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            switch(c) { case '"': b.append("\\\""); break; case '\\': b.append("\\\\"); break;
                case '\n': b.append("\\n"); break; case '\r': b.append("\\r"); break;
                case '\t': b.append("\\t"); break;
                default: if(c < 32) b.append(String.format("\\u%04x",(int)c)); else b.append(c); }
        }
        return b.append('"').toString();
    }
    static String json(Object o) {
        if (o == null) return "null";
        if (o instanceof Number || o instanceof Boolean) return o.toString();
        if (o instanceof String s) return q(s);
        if (o instanceof Object[] a) return "["+String.join(",",Arrays.stream(a).map(BytecodeIndex::json).toList())+"]";
        return q(o.toString());
    }
    static void emit(Object... kv) {
        StringJoiner s = new StringJoiner(",", "{", "}");
        for (int i=0;i<kv.length;i+=2) s.add(q((String)kv[i])+":"+json(kv[i+1]));
        out.println(s);
    }
    public static void main(String[] args) throws Exception {
        Path target=Path.of(args[0]);
        out=new PrintWriter(Files.newBufferedWriter(Path.of(args[1])));
        emit("kind","metadata","jar",target.toAbsolutePath().toString(),"sha256",HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(target))),"java",System.getProperty("java.version"),"instruction_location","call and field ordinals are visitor-event indices, not bytecode offsets","dispatch","declared targets only; dynamic dispatch and reflection unresolved");
        try(JarFile jar=new JarFile(target.toFile())) {
            var entries=jar.entries(); int ordinal=0;
            while(entries.hasMoreElements()) {
                JarEntry entry=entries.nextElement(); int id=ordinal++;
                if(!entry.getName().endsWith(".class")) continue;
                byte[] bytes=jar.getInputStream(entry).readAllBytes();
                String hash=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
                new ClassReader(bytes).accept(new ClassVisitor(Opcodes.ASM9) {
                    String owner;
                    public void visit(int v,int access,String name,String sig,String parent,String[] interfaces) {
                        owner=name; emit("kind","class","owner",owner,"ordinal",id,"sha256",hash,"version",v,"access",access,"super",parent,"interfaces",interfaces);
                    }
                    public FieldVisitor visitField(int access,String name,String desc,String signature,Object value) {
                        emit("kind","field","owner",owner,"name",name,"descriptor",desc,"access",access); return null;
                    }
                    public MethodVisitor visitMethod(int access,String name,String desc,String signature,String[] exceptions) {
                        String caller=owner+"."+name+desc;
                        emit("kind","method","owner",owner,"name",name,"descriptor",desc,"access",access,"native",(access&Opcodes.ACC_NATIVE)!=0,"abstract",(access&Opcodes.ACC_ABSTRACT)!=0,"exceptions",exceptions);
                        return new MethodVisitor(Opcodes.ASM9) {
                            int callOrdinal=0,fieldOrdinal=0;
                            public void visitMethodInsn(int opcode,String target,String method,String descriptor,boolean itf) {
                                emit("kind","call","caller",caller,"ordinal",callOrdinal++,"opcode",opcode,"owner",target,"name",method,"descriptor",descriptor,"interface",itf);
                            }
                            public void visitFieldInsn(int opcode,String target,String field,String descriptor) {
                                emit("kind","field_access","caller",caller,"ordinal",fieldOrdinal++,"opcode",opcode,"owner",target,"name",field,"descriptor",descriptor);
                            }
                            public void visitInvokeDynamicInsn(String name,String descriptor,Handle bootstrap,Object... arguments) {
                                emit("kind","invokedynamic","caller",caller,"ordinal",callOrdinal++,"name",name,"descriptor",descriptor,"bootstrap",bootstrap.toString());
                                for(Object arg:arguments) if(arg instanceof Handle h)
                                    emit("kind","dynamic_handle","caller",caller,"owner",h.getOwner(),"name",h.getName(),"descriptor",h.getDesc(),"tag",h.getTag());
                            }
                        };
                    }
                },ClassReader.SKIP_DEBUG | ClassReader.SKIP_FRAMES);
            }
        }
        out.close();
    }
}
