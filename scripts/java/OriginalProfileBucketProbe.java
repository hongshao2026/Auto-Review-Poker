import java.io.*;
import java.lang.reflect.*;
import java.net.*;
import java.nio.*;
import java.nio.file.*;
import java.util.*;

/** Offline validation only. Reuses the reviewed reader-only allowlist.
 * No original sampler, strategy, solver, registry, UI or license class loaded.
 */
public final class OriginalProfileBucketProbe {
    static final String[] DIGEST={"","22804b04d3732210b3f28dbaee3a59fbe7ab7a573b679ee68c876760aba76b94",
        "661d702e82b930222bdd1e7cea3eef35f9306baaad628cec48713091b7e2e398",
        "41e796828302d1cb95d18663fc2e1eee65f2831c90b26339a814d285003785a1"};
    static final int[] BUCKETS={169,1024,256,256};
    public static void main(String[] args) throws Exception {
        Path main=Path.of(args[0]),ec=Path.of(args[1]),cache=Path.of(args[2]),cases=Path.of(args[3]);
        OriginalFlopBucketProbe.pin(main,"25cf800b46085af762325aefcf0a24184e1b44a53c36a57037b8bb00883fca43");
        OriginalFlopBucketProbe.pin(ec,"66a68713b950183831f621278bb6da674f82ca8a2d5bbe312556e9c5ff19610c");
        try(URLClassLoader deps=new URLClassLoader(new URL[]{ec.toUri().toURL()},ClassLoader.getPlatformClassLoader())) {
            OriginalFlopBucketProbe.OriginalOnly loader=new OriginalFlopBucketProbe.OriginalOnly(main,deps);
            Class<?> oh=Class.forName("net.holdemresources.internal.oh",true,loader);
            Class<?> ol=Class.forName("net.holdemresources.internal.ol",true,loader);
            Class<?> lo=Class.forName("net.holdemresources.internal.lo",true,loader);
            Class<?> ls=Class.forName("net.holdemresources.internal.ls",true,loader);
            int[] preflop=null;
            for(Field f:ls.getDeclaredFields())if(f.getName().equals("a")&&f.getType()==int[].class){f.setAccessible(true);preflop=(int[])f.get(null);}
            int index=0;
            for(int hi=1;hi<52;++hi)for(int low=0;low<hi;++low) {
                int a=hi/4,b=low/4;
                int expected=a==b?a*14:((hi%4==low%4)?a*13+b:b*13+a);
                if(preflop[index++]!=expected)throw new AssertionError("Preflop class mismatch");
            }
            System.out.println("{\"preflop_combo_classes\":1326,\"passed\":true}");
            Method parse=OriginalFlopBucketProbe.method(oh,"a",ol,InputStream.class,int.class,String.class);
            Method map=OriginalFlopBucketProbe.method(ol,"a",int[].class,int[].class,long[].class);
            long[][] originalBoards=null;
            for(Field f:lo.getDeclaredFields())if(f.getType()==long[][].class){f.setAccessible(true);originalBoards=(long[][])f.get(null);}
            int total=0;
            List<String> lines=Files.readAllLines(cases);
            for(int street=1;street<=3;++street) {
                Path data=cache.resolve("street"+street+".buckets.u16");
                OriginalFlopBucketProbe.pin(data,DIGEST[street]);
                ByteBuffer originalIndex=ByteBuffer.allocate(originalBoards[street].length*8).order(ByteOrder.LITTLE_ENDIAN);
                for(long mask:originalBoards[street])originalIndex.putLong(mask);
                byte[] independentIndex=Files.readAllBytes(cache.resolve("street"+street+".boards.u64"));
                if(!Arrays.equals(originalIndex.array(),independentIndex))throw new AssertionError("Canonical board order mismatch at street "+street);
                Object mapping;
                try(InputStream in=Files.newInputStream(data)){mapping=parse.invoke(null,in,street,DIGEST[street]);}
                if(mapping==null || (int)OriginalFlopBucketProbe.method(ol,"b",int.class).invoke(mapping)!=BUCKETS[street])throw new AssertionError("Reader/profile rejected");
                int count=0;
                for(String line:lines) {
                    String[] p=line.split("\\t");if(Integer.parseInt(p[0])!=street)continue;
                    long[] boards=new long[4];boards[street]=Long.parseLong(p[1]);
                    int combo=Integer.parseInt(p[2]),expected=Integer.parseInt(p[3]);
                    int actual=((int[])map.invoke(mapping,new int[]{combo},boards))[0];
                    if(actual!=expected)throw new AssertionError("Mismatch street="+street+" board="+boards[street]+" combo="+combo+" actual="+actual+" expected="+expected);
                    count++;
                }
                total+=count;
                System.out.println("{\"street\":"+street+",\"buckets\":"+BUCKETS[street]+",\"canonical_boards\":"+originalBoards[street].length+",\"board_index_exact\":true,\"cases\":"+count+",\"passed\":true}");
                mapping=null;System.gc();
            }
            System.out.println("{\"cases\":"+total+",\"streets\":3,\"all_passed\":true}");
        }
    }
}
