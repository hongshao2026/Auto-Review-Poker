import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;

/** Reuses audited numeric-only loader; no GUI/solver/application initialization. */
public final class OriginalRakeProbe {
    static Class<?> cls(String n)throws Exception{return OriginalTreeProbe.cls(n);}
    static long[] ints(String s){return Arrays.stream(s.split(",")).mapToLong(Long::parseLong).toArray();}
    public static void main(String[] args)throws Exception{
        Path jar=Path.of(args[0]);
        if(!OriginalTreeProbe.sha(Files.readAllBytes(jar)).equals(OriginalTreeProbe.EXPECTED_JAR_SHA))throw new IllegalArgumentException("Unreviewed artifact");
        OriginalTreeProbe.loader=new OriginalTreeProbe.Isolated(jar);
        var ctor=cls("lC").getDeclaredConstructor(long.class,long[].class,long[].class,long[].class,int.class,int.class,int.class,int.class,int.class,int.class,int.class);
        ctor.setAccessible(true);
        for(String line:Files.readAllLines(Path.of(args[1]))){
            if(line.isBlank())continue;String[] p=line.split("\t");
            try{
                long[] remaining=ints(p[1]),paid=ints(p[2]),rank=ints(p[4]);int n=remaining.length,all=(1<<n)-1;
                var state=ctor.newInstance(Long.parseLong(p[5]),remaining,paid,new long[n],Integer.parseInt(p[3]),Integer.parseInt(p[6]),all,-1,1,0,all);
                var terminal=OriginalTreeProbe.method(cls("lK"),"a",cls("lK"),cls("lC")).invoke(null,state);
                int[] active=(int[])OriginalTreeProbe.field(terminal,"a",int[].class);
                var handler=cls("lH").getConstructor(double.class,long.class,cls("lI")).newInstance(Double.parseDouble(p[9]),Long.parseLong(p[10]),cls("lI").getEnumConstants()[Integer.parseInt(p[8])]);
                List<Object> actions=new ArrayList<>();
                for(int j=0;j<Integer.parseInt(p[7]);++j)actions.add(OriginalTreeProbe.method(cls("ly"),"b",cls("ly"),int.class,int.class,long.class,boolean.class).invoke(null,0,j%n,100L,false));
                int[] ranks=Arrays.stream(active).map(i->(int)rank[i]).toArray();
                var result=OriginalTreeProbe.method(cls("lH"),"a",cls("lF"),cls("lK"),int[].class,List.class,boolean.class).invoke(handler,terminal,ranks,actions,true);
                long[] stacks=(long[])OriginalTreeProbe.zero(result,"a",long[].class);
                int[][] killers=(int[][])OriginalTreeProbe.zero(result,"a",int[][].class);int[] masks=new int[n];
                for(int i=0;i<n;++i)if(killers[i]!=null)for(int j:killers[i])masks[i]|=1<<j;
                List<Object> pots=new ArrayList<>();long rake=0;int count=(int)OriginalTreeProbe.zero(result,"b",int.class);
                for(int i=0;i<count;++i){var pot=OriginalTreeProbe.invoke(result,"a",cls("lG"),new Class<?>[]{int.class},i);long fee=(long)OriginalTreeProbe.field(pot,"a",long.class);rake+=fee;pots.add(OriginalTreeProbe.ordered("rake",fee,"awards",OriginalTreeProbe.field(pot,"a",long[].class)));}
                OriginalTreeProbe.emit(OriginalTreeProbe.ordered("kind","case","id",p[0],"stacks",stacks,"winner_masks",masks,"rake",rake,"pots",pots,"tied_award",OriginalTreeProbe.zero(result,"a",boolean.class)));
            }catch(InvocationTargetException error){OriginalTreeProbe.emit(OriginalTreeProbe.ordered("kind","case","id",p[0],"error",error.getCause().getClass().getName()));}
        }
    }
}
