import java.io.*;
import java.lang.reflect.*;
import java.net.*;
import java.nio.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import java.util.jar.*;
import org.brotli.dec.BrotliInputStream;

/** Candidate for parent review/execution. No pg/registry/UI/license classes. */
public final class OriginalFlopBucketProbe {
    static final String DIGEST="5c50391a2dffc81287be70955ad7a86f9f607745f6a1a8f96af159d51db2e22d";
    static final String RESOURCE="abstractions/Johanson13_2021-02/Johanson13_2021-02.64.1."+DIGEST+".dat.br";
    static final List<String> ALLOW=List.of("oh","ol","lo","ls","og","lt","oD","om","oi");
    static String sha(byte[] b) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(b));
    }
    static void pin(Path p,String expected) throws Exception {
        if(!sha(Files.readAllBytes(p)).equals(expected)) throw new IllegalArgumentException("Unreviewed artifact: "+p);
    }
    static final class OriginalOnly extends ClassLoader {
        final Map<String,byte[]> classes=new HashMap<>();
        OriginalOnly(Path jar,ClassLoader dependencies) throws Exception {
            super(dependencies);
            try(JarFile z=new JarFile(jar.toFile())) {
                for(String stem:ALLOW) {
                    String name="net.holdemresources.internal."+stem;
                    classes.put(name,z.getInputStream(z.getJarEntry(name.replace('.','/')+".class")).readAllBytes());
                }
            }
        }
        protected Class<?> findClass(String name) throws ClassNotFoundException {
            byte[] b=classes.get(name);
            if(b==null) throw new ClassNotFoundException("Outside reviewed allowlist: "+name);
            return defineClass(name,b,0,b.length);
        }
    }
    static Method method(Class<?> c,String name,Class<?> ret,Class<?>... params) {
        for(Method m:c.getDeclaredMethods())
            if(m.getName().equals(name)&&m.getReturnType()==ret&&Arrays.equals(m.getParameterTypes(),params))return m;
        throw new AssertionError("Missing descriptor: "+c+"."+name);
    }
    /** Independent card-index and suit ordering oracle; does not call original ls/og. */
    static long exhaustive(Method bulk,Object mapping,long[] canonicalBoards,byte[] raw) throws Exception {
        short[][] table=new short[canonicalBoards.length][1326];
        int[] high=new int[1326],low=new int[1326]; long[] holes=new long[1326];
        int index=0;
        for(int h=1;h<52;h++)for(int l=0;l<h;l++) { high[index]=h;low[index]=l;holes[index++]=(1L<<h)|(1L<<l); }
        int offset=0;
        for(int row=0;row<table.length;row++) {
            Arrays.fill(table[row],(short)-1);
            for(int hole=0;hole<1326;hole++)if((holes[hole]&canonicalBoards[row])==0) {
                table[row][hole]=(short)((raw[offset]&255)|((raw[offset+1]&255)<<8));offset+=2;
            }
        }
        if(offset!=raw.length)throw new AssertionError("Independent schema length");
        long legal=0;int boardCount=0;
        for(int a=0;a<50;a++)for(int b=a+1;b<51;b++)for(int c=b+1;c<52;c++) {
            long board=(1L<<a)|(1L<<b)|(1L<<c);
            int[] ranks=new int[4];
            for(int card:new int[]{a,b,c})ranks[card%4]|=1<<(card/4);
            Integer[] sorted={0,1,2,3};Arrays.sort(sorted,Comparator.comparingInt(s->ranks[s]));
            int[] permutation=new int[4];long canonical=0;
            for(int s=0;s<4;s++) { permutation[sorted[s]]=s;for(int r=0;r<13;r++)if((ranks[sorted[s]]&(1<<r))!=0)canonical|=1L<<(4*r+s); }
            int row=Arrays.binarySearch(canonicalBoards,canonical);
            if(row<0)throw new AssertionError("Independent canonical board absent");
            int[] actual=(int[])bulk.invoke(mapping,new long[]{0,board},0);
            if(actual.length!=1326)throw new AssertionError("Original bulk width");
            for(int hole=0;hole<1326;hole++) {
                int h=4*(high[hole]/4)+permutation[high[hole]%4],l=4*(low[hole]/4)+permutation[low[hole]%4];
                int expected=table[row][Math.max(h,l)*(Math.max(h,l)-1)/2+Math.min(h,l)];
                if(actual[hole]!=expected)throw new AssertionError("Full-domain mismatch board="+board+" hole="+hole+" actual="+actual[hole]+" expected="+expected);
                if((board&holes[hole])==0)legal++;
            }
            boardCount++;
        }
        if(boardCount!=22100||legal!=25989600L)throw new AssertionError("Incomplete enumeration");
        return legal;
    }
    public static void main(String[] args) throws Exception {
        Path main=Path.of(args[0]),data=Path.of(args[1]),ec=Path.of(args[2]),cases=Path.of(args[3]);
        pin(main,"25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43");
        pin(data,"731b654ead51b5b49c91accee59f1a8bfe9471f4597d3104213cc7c8b27582ec");
        pin(ec,"66a68713b950183831f621278bb6da674f82ca8a2d5bbe312556e9c5ff19610c");
        pin(Path.of(BrotliInputStream.class.getProtectionDomain().getCodeSource().getLocation().toURI()),"615c0c3efef990d77831104475fba6a1f7971388691d4bad1471ad84101f6d52");
        byte[] raw;
        try(JarFile z=new JarFile(data.toFile()); InputStream in=z.getInputStream(z.getJarEntry(RESOURCE)); BrotliInputStream br=new BrotliInputStream(in)) {
            raw=br.readAllBytes();
        }
        if(raw.length!=4127760||!sha(raw).equals(DIGEST))throw new AssertionError("Resource schema/hash");
        try(URLClassLoader dependencies=new URLClassLoader(new URL[]{ec.toUri().toURL()},ClassLoader.getPlatformClassLoader())) {
            OriginalOnly loader=new OriginalOnly(main,dependencies);
            Class<?> oh=Class.forName("net.holdemresources.internal.oh",true,loader);
            Class<?> ol=Class.forName("net.holdemresources.internal.ol",true,loader);
            Class<?> lo=Class.forName("net.holdemresources.internal.lo",true,loader);
            Method parse=method(oh,"a",ol,InputStream.class,int.class,String.class);
            Object mapping=parse.invoke(null,new ByteArrayInputStream(raw),1,DIGEST);
            if(mapping==null)throw new AssertionError("Reader rejected matching hash");
            if((int)method(ol,"b",int.class).invoke(mapping)!=64)throw new AssertionError("Bucket count");
            Method map=method(ol,"a",int[].class,int[].class,long[].class);
            int count=0;
            for(String line:Files.readAllLines(cases)) {
                String[] p=line.split("\\t");long board=Long.parseLong(p[1]);int hole=Integer.parseInt(p[2]),expected=Integer.parseInt(p[3]);
                int[] result=(int[])map.invoke(mapping,new int[]{hole},new long[]{0,board});
                if(result[0]!=expected)throw new AssertionError("Mismatch "+p[0]+": "+result[0]+" != "+expected);
                count++;
            }
            long[][] boards=null;
            for(Field f:lo.getDeclaredFields())if(f.getType()==long[][].class){f.setAccessible(true);boards=(long[][])f.get(null);}
            ByteBuffer bytes=ByteBuffer.allocate(boards[1].length*8).order(ByteOrder.LITTLE_ENDIAN);
            for(long b:boards[1])bytes.putLong(b);
            String orderHash=sha(bytes.array());
            if(!orderHash.equals("b5f4eb663ab0657ceb31273943d2aa96c87e025804b65983358464e0c52933ac"))throw new AssertionError("Board order");
            long exhaustiveCases=exhaustive(method(ol,"a",int[].class,long[].class,int.class),mapping,boards[1],raw);
            if(parse.invoke(null,new ByteArrayInputStream(raw),1,"0".repeat(64))!=null)throw new AssertionError("Bad hash accepted");
            boolean truncatedRejected=false;
            try{parse.invoke(null,new ByteArrayInputStream(Arrays.copyOf(raw,raw.length-1)),1,DIGEST);}
            catch(InvocationTargetException e){truncatedRejected=e.getCause() instanceof IOException;}
            if(!truncatedRejected)throw new AssertionError("Truncated row accepted");
            System.out.println("{\"original_reader_cases\":"+count+",\"exhaustive_physical_flops\":22100,\"exhaustive_legal_board_hole_cases\":"+exhaustiveCases+",\"buckets\":64,\"board_count\":"+boards[1].length+",\"board_order_sha256\":\""+orderHash+"\",\"resource_sha256\":\""+DIGEST+"\",\"bad_hash_rejected\":true,\"truncation_rejected\":true,\"all_passed\":true}");
        }
    }
}
