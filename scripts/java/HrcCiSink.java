package rea.hrcbench;

import java.nio.file.*;
import java.nio.charset.StandardCharsets;

/** Observation only: never reads or changes solver fields; all failures contained. */
public final class HrcCiSink {
  private static volatile Path output;
  public static void configure(String path) { output=Path.of(path); }
  public static void record(int index,long millis,long samples,double ci) {
    try {
      Path destination=output;
      if(destination!=null) {
        String value=Double.isFinite(ci)?Double.toString(ci):"null";
        String row="{\"event\":\"original_mr_constructor\",\"index\":"+index+
          ",\"original_epoch_millis\":"+millis+",\"original_samples\":"+samples+
          ",\"ci\":"+value+",\"observed_epoch_millis\":"+System.currentTimeMillis()+
          ",\"observed_nano_time\":"+System.nanoTime()+"}\n";
        Files.writeString(destination,row,StandardCharsets.UTF_8,StandardOpenOption.CREATE,StandardOpenOption.APPEND);
      }
    } catch(Throwable ignored) { /* Observation must never change the solver's outcome. */ }
  }
}
