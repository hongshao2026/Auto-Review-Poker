import java.nio.file.*;
import java.util.*;

/** Reuses the audited exact allowlist in OriginalTreeProbe. Pure lB/lC/mG only. */
public final class OriginalTreeBuilderProbe {
    static long[] longs(String s) { return Arrays.stream(s.split(",")).mapToLong(Long::parseLong).toArray(); }
    public static void main(String[] args) throws Exception {
        Path jar=Path.of(args[0]);
        if(!OriginalTreeProbe.sha(Files.readAllBytes(jar)).equals(OriginalTreeProbe.EXPECTED_JAR_SHA)) throw new IllegalArgumentException("Unreviewed JAR");
        OriginalTreeProbe.loader=new OriginalTreeProbe.Isolated(jar);
        for(String line:Files.readAllLines(Path.of(args[1]))) {
            if(line.isBlank())continue;
            String[] p=line.split("\t",-1);
            Object blinds=OriginalTreeProbe.cls("ky").getConstructor(long[].class,boolean.class,OriginalTreeProbe.cls("kz"),OriginalTreeProbe.cls("kA"))
                .newInstance(longs(p[2]),false,OriginalTreeProbe.cls("kz").getEnumConstants()[Integer.parseInt(p[3])],OriginalTreeProbe.cls("kA").getEnumConstants()[Integer.parseInt(p[4])]);
            Object config=OriginalTreeProbe.cls("kM").getConstructor(long[].class,OriginalTreeProbe.cls("ky"),boolean.class,OriginalTreeProbe.cls("lH"))
                .newInstance(longs(p[1]),blinds,Boolean.parseBoolean(p[5]),null);
            Object context=OriginalTreeProbe.cls("lB").getConstructor(OriginalTreeProbe.cls("kG")).newInstance(config);
            if(!p[7].equals("-")) for(String step:p[7].split(",")) {
                String[] fields=step.split(":"); int street=Integer.parseInt(fields[0]),kind=Integer.parseInt(fields[1]);
                while((int)OriginalTreeProbe.field(OriginalTreeProbe.field(context,"a",OriginalTreeProbe.cls("lC")),"a",int.class)<street)
                    context=OriginalTreeProbe.zero(context,"a",OriginalTreeProbe.cls("lB"));
                context=switch(kind) {
                    case 0->OriginalTreeProbe.zero(context,"b",OriginalTreeProbe.cls("lB"));
                    case 1->OriginalTreeProbe.zero(context,"c",OriginalTreeProbe.cls("lB"));
                    case 2->OriginalTreeProbe.zero(context,"d",OriginalTreeProbe.cls("lB"));
                    case 3->OriginalTreeProbe.raise(context,Long.parseLong(fields[2]));
                    default->throw new IllegalArgumentException("Unknown action");
                };
            }
            while((int)OriginalTreeProbe.field(OriginalTreeProbe.field(context,"a",OriginalTreeProbe.cls("lC")),"a",int.class)<Integer.parseInt(p[6]))
                context=OriginalTreeProbe.zero(context,"a",OriginalTreeProbe.cls("lB"));
            Map<String,Object> actual=OriginalTreeProbe.snapshot(context);
            Object state=OriginalTreeProbe.field(context,"a",OriginalTreeProbe.cls("lC"));
            actual.put("deadMoney",OriginalTreeProbe.field(state,"a",long.class));
            actual.put("betCount",OriginalTreeProbe.field(state,"d",int.class));
            actual.put("flatCount",OriginalTreeProbe.field(state,"e",int.class));
            if((long)actual.get("minimum")>0) {
                actual.put("geometric66",OriginalTreeProbe.method(OriginalTreeProbe.cls("mG"),"d",long.class,OriginalTreeProbe.cls("lB"),double.class).invoke(null,context,.66));
                actual.put("pot50",OriginalTreeProbe.method(OriginalTreeProbe.cls("mG"),"c",long.class,OriginalTreeProbe.cls("lB"),double.class).invoke(null,context,.5));
            }
            OriginalTreeProbe.emit(OriginalTreeProbe.ordered("kind","builder_case","id",p[0],"actual",actual));
        }
    }
}
