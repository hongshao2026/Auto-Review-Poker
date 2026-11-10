import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.jar.*;

/** Only audited lB/lC and qp/qw sizing/context methods, without the application or JS runtime. */
public final class OriginalGeneralContextProbe {
    static long[] longs(String s){return Arrays.stream(s.split(",")).mapToLong(Long::parseLong).toArray();}
    static List<String> tokens(String s){return s.isEmpty()?List.of():Arrays.stream(s.split(";")).map(x->new String(Base64.getDecoder().decode(x),StandardCharsets.UTF_8)).toList();}
    public static void main(String[] args)throws Exception{
        Path jar=Path.of(args[0]);if(!OriginalTreeProbe.sha(Files.readAllBytes(jar)).equals(OriginalTreeProbe.EXPECTED_JAR_SHA))throw new IllegalArgumentException("Unreviewed JAR");
        OriginalTreeProbe.loader=new OriginalTreeProbe.Isolated(jar);
        try(JarFile z=new JarFile(jar.toFile())){
            List<String> names=new ArrayList<>();for(String name:List.of("qp","qr","qt","qw","qx","qy","qz","qA","qC"))names.add(OriginalTreeProbe.PREFIX+name);
            for(String name:List.of("IDecisionContext","IPlayerAction","IPotState"))names.add("net.holdemresources.scripting.treescripts.api."+name);
            for(String name:names){byte[] bytes=z.getInputStream(z.getJarEntry(name.replace('.','/')+".class")).readAllBytes();OriginalTreeProbe.loader.bytes.put(name,bytes);OriginalTreeProbe.emit(OriginalTreeProbe.ordered("kind","class","name",name,"sha256",OriginalTreeProbe.sha(bytes)));}
        }
        for(String line:Files.readAllLines(Path.of(args[1]))){if(line.isBlank())continue;String[] p=line.split("\t",-1);
            Object blinds=OriginalTreeProbe.cls("ky").getConstructor(long[].class,boolean.class,OriginalTreeProbe.cls("kz"),OriginalTreeProbe.cls("kA")).newInstance(longs(p[2]),Boolean.parseBoolean(p[8]),OriginalTreeProbe.cls("kz").getEnumConstants()[Integer.parseInt(p[3])],OriginalTreeProbe.cls("kA").getEnumConstants()[Integer.parseInt(p[4])]);
            Object config=OriginalTreeProbe.cls("kM").getConstructor(long[].class,OriginalTreeProbe.cls("ky"),boolean.class,OriginalTreeProbe.cls("lH")).newInstance(longs(p[1]),blinds,Boolean.parseBoolean(p[5]),null);
            Object context=OriginalTreeProbe.cls("lB").getConstructor(OriginalTreeProbe.cls("kG")).newInstance(config);
            if(!p[7].equals("-"))for(String step:p[7].split(",")){String[] a=step.split(":");int street=Integer.parseInt(a[0]),kind=Integer.parseInt(a[1]);
                while((int)OriginalTreeProbe.field(OriginalTreeProbe.field(context,"a",OriginalTreeProbe.cls("lC")),"a",int.class)<street)context=OriginalTreeProbe.zero(context,"a",OriginalTreeProbe.cls("lB"));
                context=switch(kind){case 0->OriginalTreeProbe.zero(context,"b",OriginalTreeProbe.cls("lB"));case 1->OriginalTreeProbe.zero(context,"c",OriginalTreeProbe.cls("lB"));case 2->OriginalTreeProbe.zero(context,"d",OriginalTreeProbe.cls("lB"));case 3->OriginalTreeProbe.raise(context,Long.parseLong(a[2]));default->throw new IllegalArgumentException();};
            }
            Object state=OriginalTreeProbe.field(context,"a",OriginalTreeProbe.cls("lC"));
            while((int)OriginalTreeProbe.field(state,"a",int.class)<Integer.parseInt(p[6])){context=OriginalTreeProbe.zero(context,"a",OriginalTreeProbe.cls("lB"));state=OriginalTreeProbe.field(context,"a",OriginalTreeProbe.cls("lC"));}
            Map<String,Object> out=OriginalTreeProbe.snapshot(context);out.put("deadMoney",OriginalTreeProbe.field(state,"a",long.class));out.put("bets",OriginalTreeProbe.field(state,"d",int.class));out.put("flats",OriginalTreeProbe.field(state,"e",int.class));out.put("live",OriginalTreeProbe.zero(state,"a",int.class));
            Object ctx=OriginalTreeProbe.cls("qp").getConstructor(OriginalTreeProbe.cls("lB")).newInstance(context);
            for(String method:List.of("getNumberOfPlayers","getPlayerIndexSmallBlind","getPlayerIndexBigBlind","getPlayerIndexButton"))out.put(method,OriginalTreeProbe.zero(ctx,method,int.class));
            int n=longs(p[1]).length;boolean[][] ip=new boolean[n][n];for(int i=0;i<n;++i)for(int j=0;j<n;++j)ip[i][j]=(boolean)OriginalTreeProbe.invoke(ctx,"isPlayerInPosition",boolean.class,new Class<?>[]{int.class,int.class},i,j);out.put("ip",ip);
            if((int)out.get("actor")>=0){out.put("closing",OriginalTreeProbe.zero(ctx,"isClosingAction",boolean.class));out.put("donk",OriginalTreeProbe.zero(ctx,"isDonkBet",boolean.class));
                if((long)out.get("minimum")>0){out.put("spr",OriginalTreeProbe.zero(ctx,"getStackPotRatio",double.class));
                    for(int f=0;f<2;++f){Map<String,Object> values=new LinkedHashMap<>();for(String text:tokens(p[9+f]))values.put(text,OriginalTreeProbe.invoke(ctx,f==0?"sizingsPreflop":"sizingsPostflop",long[].class,new Class<?>[]{String.class},text));out.put(f==0?"pre_sizes":"post_sizes",values);}}
            }
            OriginalTreeProbe.emit(OriginalTreeProbe.ordered("kind","case","id",p[0],"actual",out));
        }
    }
}
