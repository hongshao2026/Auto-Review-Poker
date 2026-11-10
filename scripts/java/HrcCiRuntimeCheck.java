import java.lang.instrument.Instrumentation;
import java.lang.reflect.*;
import java.nio.file.*;

/** Pre-timing link check: constructs one detached immutable CI record only. */
public final class HrcCiRuntimeCheck {
  public static void agentmain(String output, Instrumentation inst) throws Exception {
    ClassLoader loader=null;
    for(Class<?> cls:inst.getAllLoadedClasses())if(cls.getName().equals("net.holdemresources.internal.oc"))loader=cls.getClassLoader();
    if(loader==null)throw new IllegalStateException("Original HRC class loader not found");
    Class<?> cls=Class.forName("net.holdemresources.internal.mr",true,loader);
    Constructor<?> ctor=cls.getDeclaredConstructor(int.class,long.class,long.class,double.class);ctor.setAccessible(true);
    Object detached=ctor.newInstance(-1,0L,0L,Double.NaN);
    int fields=0;
    for(Field field:cls.getDeclaredFields())if(!Modifier.isStatic(field.getModifiers())) {
      field.setAccessible(true);Object value=field.get(detached);
      if(field.getType()==int.class&&((Integer)value)!=-1)throw new AssertionError();
      if(field.getType()==long.class&&((Long)value)!=0L)throw new AssertionError();
      if(field.getType()==double.class&&!Double.isNaN((Double)value))throw new AssertionError();
      fields++;
    }
    if(fields!=4)throw new AssertionError("Unexpected original record fields");
    Files.writeString(Path.of(output),"{\"runtime_record_link_check\":\"passed\",\"detached_synthetic_record\":true,\"index\":-1,\"original_epoch_millis\":0,\"excluded_from_timed_run\":true}\n");
  }
}
