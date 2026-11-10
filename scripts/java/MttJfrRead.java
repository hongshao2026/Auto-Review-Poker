import jdk.jfr.consumer.*;
import java.nio.file.*;
import java.time.*;
import java.util.*;

/** Streams only selected fields, avoiding recursive RecordedClass JSON expansion. */
public final class MttJfrRead {
    private static String quote(String s) {
        return "\""+s.replace("\\","\\\\").replace("\"","\\\"").replace("\n","\\n").replace("\r","\\r")+"\"";
    }
    public static void main(String[] args) throws Exception {
        Instant low=Instant.parse(args[1]), high=Instant.parse(args[2]);
        Set<Long> workers=new HashSet<>();
        for (String id:args[3].split(",")) workers.add(Long.parseLong(id));
        try (RecordingFile file=new RecordingFile(Path.of(args[0]))) {
            while(file.hasMoreEvents()) {
                RecordedEvent e=file.readEvent();
                String kind=e.getEventType().getName();
                boolean sample=kind.equals("jdk.ExecutionSample")||kind.equals("jdk.NativeMethodSample");
                RecordedThread thread=sample?e.getThread("sampledThread"):e.getThread();
                long tid=thread==null?-1:thread.getOSThreadId();
                boolean worker=workers.contains(tid);
                Instant start=e.getStartTime(),end=e.getEndTime();
                if (sample) {
                    if(!worker||start.isBefore(low)||start.isAfter(high))continue;
                } else {
                    if(end.isBefore(low)||start.isAfter(high))continue;
                    if(!worker&&!kind.equals("jdk.GarbageCollection")&&!kind.equals("jdk.GCPhasePause")&&!kind.equals("jdk.Compilation"))continue;
                    if(e.getDuration().isZero())continue;
                }
                StringBuilder out=new StringBuilder("{\"type\":").append(quote(kind))
                    .append(",\"startTime\":").append(quote(start.toString()))
                    .append(",\"durationSeconds\":").append(e.getDuration().toNanos()/1e9)
                    .append(",\"tid\":").append(tid);
                RecordedStackTrace stack=e.getStackTrace();
                out.append(",\"truncated\":").append(stack!=null&&stack.isTruncated()).append(",\"frames\":[");
                String type="unknown"; boolean first=true;
                if(stack!=null) for(RecordedFrame frame:stack.getFrames()) {
                    RecordedMethod method=frame.getMethod();
                    if(first)type=frame.getType();else out.append(',');
                    first=false;
                    out.append(quote(method.getType().getName()+"."+method.getName()+method.getDescriptor()));
                }
                System.out.println(out.append("],\"topFrameType\":").append(quote(type)).append('}'));
            }
        }
    }
}
